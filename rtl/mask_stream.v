// Output streamer of architecture A3: packs the despeckled binary frame and sends it, followed by the candidate list of the labeller, to the
// MCU over an 8-bit strobed parallel bus (captured by an RP2350 PIO state machine + DMA).  There is no frame store in the FPGA: the mask
// leaves at the pixel rate (one byte per 4 core clocks = 16 beats), the candidate list is read from a small RAM filled by run_ccl.
//
// One packet per accepted frame, all words little-endian, bytes sent LSB first:
//   header   4 words  H0 = 0x4D335441 ("AT3M")  H1 = frame sequence number  H2/H3 = device time (us) at the frame start (low / high)
//   mask     32000 words = 800 rows x 40 words, bit (x % 32) of word y*40 + x/32 = pixel (x, y), 1 = black (despeckled)
//   trailer  4 words  T0 = {8'h0, cand_count[7:0], 4'h0, ccl_flags[3:0], 8'h0 | status[7:0]}   status: [0] CSI frame bad  [1] threshold busy error
//                          [2] mask FIFO overflow  [3] mask shorter than 800 rows (zero padded)  [4] labeller result missing (timeout)
//                     T1 = sum of all pixels (auto exposure)   T2 = {16'h0, max_row_cycles}   T3 = ~H1
//   cands    1024 words = 64 records x 16 words (run_ccl record format; only the first cand_count records are valid)
// = 132,128 bytes.  Bus: bus_d[7:0] changes one core clock before bus_clk rises, bus_clk is high for 2 of the 4 clocks of a byte slot, bus_fs is
// high from before the first byte to after the last.  The strobe stops (bus_fs stays high) if the next word is late, so the receiver only
// needs to count bytes.  A new frame start while a packet is still in flight aborts it (bus_fs drops early, `aborts` counts).
`timescale 1ns/1ps
module mask_stream #(
    parameter MASK_WORDS = 32000,
    parameter CAND_WORDS = 1024,
    parameter WAIT_TIMEOUT = 20'd100000,       // clocks to wait for the labeller after the mask: ~1.2 ms at 85.7 MHz (it normally answers within ~200)
    parameter IDLE_END = 16'd4096              // clocks without a mask beat after the sensor frame ended before the rest of the mask is padded
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        enable,
    // despeckled binary stream (2 pixels per beat; bit x%32 of a word = pixel x)
    input  wire        d_valid,
    input  wire        d_b0,
    input  wire        d_b1,
    input  wire        d_last,          // last beat of a row
    input  wire        d_fs,            // pulse shortly before the first beat of a frame
    input  wire        d_fe,            // pulse with the last beat of the frame
    input  wire        csi_fe,          // pulse: the sensor frame ended (good or bad); a frame that lost lines never produces d_fe
    // candidate list from run_ccl
    input  wire        c_we,
    input  wire [9:0]  c_waddr,
    input  wire [31:0] c_wdata,
    input  wire        ccl_done,
    input  wire [7:0]  ccl_count,
    input  wire [3:0]  ccl_flags,
    input  wire [15:0] ccl_maxrow,
    // per-frame side information
    input  wire [63:0] ts,
    input  wire [31:0] frame_sum,
    input  wire        frame_bad,
    input  wire        busy_err,
    // MCU bus
    output reg  [7:0]  bus_d,
    output reg         bus_clk,
    output reg         bus_fs,
    // status
    output reg  [31:0] frames_sent,                 // packets completely sent
    output reg  [15:0] aborts,
    output reg  [15:0] fifo_ovf,
    output reg  [7:0]  last_count,
    output wire        busy,
    output reg         pkt_end         // pulse: packet fully sent
);
    localparam [31:0] MAGIC = 32'h4D335441;
    localparam [2:0] W_IDLE = 0, W_HDR = 1, W_MASK = 2, W_WAIT = 3, W_TRL = 4, W_CAND = 5;

    // ------------------------------------------------------------------ candidate RAM (written by run_ccl, read here)
    reg [31:0] cand [0:CAND_WORDS-1];
    reg [9:0]  cand_ra; reg [31:0] cand_q;
    always @(posedge clk) begin
        if (c_we) cand[c_waddr] <= c_wdata;
        cand_q <= cand[cand_ra];
    end
`ifndef SYNTHESIS
    integer zi; initial for (zi = 0; zi < CAND_WORDS; zi = zi + 1) cand[zi] = 0;
`endif

    // ------------------------------------------------------------------ pixel packer -> FIFO
    reg [31:0] pack; reg [3:0] ocol;
    wire [31:0] pack_n = {d_b1, d_b0, pack[31:2]};
    wire        push = d_valid && ocol == 4'd15;
    reg  [31:0] fifo [0:15];
    reg  [4:0]  wp, rp;
    wire [4:0]  fcnt = wp - rp;
    reg  [2:0]  ws;
    reg         accept;                                  // pushes are accepted from the frame start until the mask is complete
    reg         pop;
    always @(posedge clk) begin
        if (rst) begin ocol <= 0; wp <= 0; fifo_ovf <= 0; end
        else begin
            if (d_valid) begin pack <= pack_n; ocol <= d_last ? 4'd0 : ocol + 4'd1; end
            if (d_fs) begin wp <= 0; ocol <= 0; end
            else if (push && accept) begin
                if (fcnt == 5'd16) fifo_ovf <= fifo_ovf + 1;
                else begin fifo[wp[3:0]] <= pack_n; wp <= wp + 1; end
            end
        end
    end

    // ------------------------------------------------------------------ packet walker: produces the next word into nxt
    reg [31:0] nxt; reg nxt_v, nxt_last; wire nxt_take;
    reg [15:0] widx; reg [1:0] cph;
    reg        fe_seen, done_seen, short_f, ovf_f;
    reg [19:0] wait_cnt; reg fe_hint; reg [15:0] idle_cnt;
    reg [31:0] seq;
    reg [31:0] h1, h2, h3;
    reg [31:0] t0, t1, t2, t3;
    reg [7:0]  s_count; reg [3:0] s_flags; reg [15:0] s_maxrow;
    reg        abort_tx;
    wire [31:0] hdr_w = widx[1:0] == 2'd0 ? MAGIC : widx[1:0] == 2'd1 ? h1 : widx[1:0] == 2'd2 ? h2 : h3;
    wire [31:0] trl_w = widx[1:0] == 2'd0 ? t0 : widx[1:0] == 2'd1 ? t1 : widx[1:0] == 2'd2 ? t2 : t3;
    reg txa;
    assign busy = ws != W_IDLE || txa;
    reg [15:0] ovf_at_start;

    always @(posedge clk) begin
        abort_tx <= 0;
        if (rst) begin
            ws <= W_IDLE; nxt_v <= 0; nxt_last <= 0; widx <= 0; cph <= 0; accept <= 0; rp <= 0; fe_seen <= 0; fe_hint <= 0; idle_cnt <= 0; done_seen <= 0;
            aborts <= 0; seq <= 0; last_count <= 0; short_f <= 0; ovf_f <= 0; wait_cnt <= 0; cand_ra <= 0;
        end else begin
            if (ccl_done) begin done_seen <= 1; s_count <= ccl_count; s_flags <= ccl_flags; s_maxrow <= ccl_maxrow; end
            if (d_fe) fe_seen <= 1;
            if (csi_fe) fe_hint <= 1;
            if (d_valid) idle_cnt <= 0; else if (idle_cnt != 16'hFFFF) idle_cnt <= idle_cnt + 1;
            if (fe_hint && idle_cnt >= IDLE_END && ws == W_MASK) fe_seen <= 1;        // lines are missing: pad the mask, the frame is flagged bad
            if (d_fs && enable) begin
                if (ws != W_IDLE) begin aborts <= aborts + 1; abort_tx <= 1; end
                ws <= W_HDR; widx <= 0; nxt_v <= 0; rp <= 0; cph <= 0; accept <= 1; fe_seen <= 0; fe_hint <= 0; done_seen <= 0; short_f <= 0; ovf_f <= 0;
                seq <= seq + 1; h1 <= seq + 1; h2 <= ts[31:0]; h3 <= ts[63:32]; ovf_at_start <= fifo_ovf;
            end else begin
                if (nxt_take) nxt_v <= 0;
                case (ws)
                W_HDR: if (!nxt_v && !nxt_take) begin
                    nxt <= hdr_w; nxt_v <= 1; nxt_last <= 0;
                    if (widx == 16'd3) begin ws <= W_MASK; widx <= 0; end else widx <= widx + 1;
                end
                W_MASK: begin
                    if (fifo_ovf != ovf_at_start) ovf_f <= 1;
                    if (!nxt_v && !nxt_take) begin
                        if (fcnt != 0) begin
                            nxt <= fifo[rp[3:0]]; nxt_v <= 1; nxt_last <= 0; rp <= rp + 1; widx <= widx + 1;
                            if (widx == MASK_WORDS - 1) begin ws <= W_WAIT; accept <= 0; wait_cnt <= 0; end
                        end else if (fe_seen) begin                        // frame ended early: pad with zeros
                            nxt <= 32'd0; nxt_v <= 1; nxt_last <= 0; widx <= widx + 1; short_f <= 1;
                            if (widx == MASK_WORDS - 1) begin ws <= W_WAIT; accept <= 0; wait_cnt <= 0; end
                        end
                    end
                end
                W_WAIT: begin
                    wait_cnt <= wait_cnt + 1;
                    if ((done_seen || wait_cnt == WAIT_TIMEOUT) && !nxt_v) begin
                        if (!done_seen) begin s_count <= 0; s_flags <= 0; s_maxrow <= 0; end
                        ws <= W_TRL; widx <= 0;
                        t0 <= {8'h00, done_seen ? s_count : 8'd0, 4'h0, done_seen ? s_flags : 4'd0,
                               3'b000, !done_seen, short_f, ovf_f, busy_err, frame_bad};
                        t1 <= frame_sum; t2 <= {16'd0, done_seen ? s_maxrow : 16'd0}; t3 <= ~h1;
                        last_count <= done_seen ? s_count : 8'd0;
                    end
                end
                W_TRL: if (!nxt_v && !nxt_take) begin
                    nxt <= trl_w; nxt_v <= 1; nxt_last <= 0;
                    if (widx == 16'd3) begin ws <= W_CAND; widx <= 0; cph <= 0; end else widx <= widx + 1;
                end
                W_CAND: if (!nxt_v && !nxt_take) begin
                    if (cph == 2'd0) begin cand_ra <= widx[9:0]; cph <= 2'd1; end
                    else if (cph == 2'd1) cph <= 2'd2;
                    else begin
                        nxt <= cand_q; nxt_v <= 1; cph <= 0; widx <= widx + 1;
                        if (widx == CAND_WORDS - 1) begin nxt_last <= 1; ws <= W_IDLE; end else nxt_last <= 0;
                    end
                end
                default: ;
                endcase
            end
        end
    end

    // ------------------------------------------------------------------ byte transmitter: 4 core clocks per byte
    //   slot 0: bus_d changes, clk low   slot 1,2: clk high   slot 3: clk low        (receiver samples on the rising edge)
    reg [31:0] cur; reg cur_last; reg [1:0] bidx, slot; reg kill;
    assign nxt_take = nxt_v && !kill && ((!txa) || (slot == 2'd3 && bidx == 2'd3 && !cur_last));
    always @(posedge clk) begin
        pkt_end <= 0;
        if (rst) begin
            txa <= 0; bus_fs <= 0; bus_clk <= 0; bus_d <= 0; kill <= 0; frames_sent <= 0; slot <= 0; bidx <= 0; cur_last <= 0; cur <= 0;
        end else begin
            if (!txa) begin
                bus_clk <= 0;
                if (kill) begin bus_fs <= 0; kill <= 0; end
                else if (nxt_v) begin
                    cur <= nxt; cur_last <= nxt_last; bus_d <= nxt[7:0]; bus_fs <= 1; txa <= 1; slot <= 0; bidx <= 0;
                end
            end else begin
                slot <= slot + 1;
                case (slot)
                    2'd0: bus_clk <= 1;
                    2'd2: bus_clk <= 0;
                    2'd3: begin
                        if (bidx != 2'd3) begin
                            bidx <= bidx + 1; bus_d <= cur[8 * (bidx + 1) +: 8];
                        end else if (kill) begin
                            txa <= 0; bus_fs <= 0; kill <= 0;
                        end else if (cur_last) begin
                            txa <= 0; bus_fs <= 0; pkt_end <= 1; frames_sent <= frames_sent + 1;
                        end else if (nxt_v) begin
                            cur <= nxt; cur_last <= nxt_last; bus_d <= nxt[7:0]; bidx <= 0;
                        end else txa <= 0;                       // next word late: pause the strobe, bus_fs stays high
                    end
                    default: ;
                endcase
            end
            if (abort_tx) kill <= 1;
        end
    end
endmodule
