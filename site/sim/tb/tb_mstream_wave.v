// Waveform scenario copy of tb/tb_mstream.v (same stimulus, same checks; run with +frames=1): adds signal aliases and a dump window
// (frame start, packet header, first and last mask words, WAIT/trailer, start of the candidate list) so the VCD stays small.
// Self-checking testbench of rtl/mask_stream.v: plays despeckled-frame beats at the real line timing (640 beats in a 686-clock line, 85.714 MHz
// clock), writes a candidate list, pulses ccl_done, and checks every byte on the MCU bus (the receiver samples on the rising edge of bus_clk like the
// RP2350 PIO does).  +frames=N (default 3), +late=1 delays ccl_done by 3000 clocks, +short=1 ends the second frame after 500 rows,
// +abort=1 restarts a frame in the middle of the previous packet.   Prints "PASS" or "FAIL ...".
`timescale 1ns/1ps
module tb;
    reg clk = 0, rst = 1;
    always #5.833 clk = ~clk;                           // 85.714 MHz
    reg d_valid = 0, d_b0 = 0, d_b1 = 0, d_last = 0, d_fs = 0, d_fe = 0;
    reg c_we = 0; reg [9:0] c_waddr = 0; reg [31:0] c_wdata = 0; reg ccl_done = 0;
    reg [7:0] ccl_count = 0; reg [3:0] ccl_flags = 0; reg [15:0] ccl_maxrow = 0;
    reg [63:0] ts = 64'h0000_0001_2345_6789; reg [31:0] frame_sum = 32'hCAFE0001; reg frame_bad = 0, busy_err = 0;
    wire [7:0] bus_d; wire bus_clk, bus_fs, busy, pkt_end;
    wire [31:0] frames_sent; wire [15:0] aborts, fifo_ovf; wire [7:0] last_count;
    mask_stream dut(.clk(clk), .rst(rst), .enable(1'b1), .d_valid(d_valid), .d_b0(d_b0), .d_b1(d_b1), .d_last(d_last), .d_fs(d_fs), .d_fe(d_fe), .csi_fe(1'b0),
        .c_we(c_we), .c_waddr(c_waddr), .c_wdata(c_wdata), .ccl_done(ccl_done), .ccl_count(ccl_count), .ccl_flags(ccl_flags), .ccl_maxrow(ccl_maxrow),
        .ts(ts), .frame_sum(frame_sum), .frame_bad(frame_bad), .busy_err(busy_err), .bus_d(bus_d), .bus_clk(bus_clk), .bus_fs(bus_fs),
        .frames_sent(frames_sent), .aborts(aborts), .fifo_ovf(fifo_ovf), .last_count(last_count), .busy(busy), .pkt_end(pkt_end));

    // ---- signals shown in the viewer
    wire frame_start_in = d_fs, in_valid = d_valid, in_black0 = d_b0, in_black1 = d_b1, in_row_last = d_last, frame_end_in = d_fe;
    wire cand_write = c_we; wire [9:0] cand_waddr_w = c_waddr; wire [31:0] cand_wdata_w = c_wdata;
    wire labeller_done = ccl_done; wire [7:0] labeller_count = ccl_count;
    wire [2:0] pkt_state = dut.ws;
    wire [15:0] word_index = dut.widx;
    wire [4:0] fifo_fill = dut.wp - dut.rp;
    wire [7:0] mcu_d = bus_d; wire mcu_clk = bus_clk, mcu_fs = bus_fs;
    wire pkt_done = pkt_end, streamer_busy = busy;
    reg won = 0; integer fsw = 0;
    always @(posedge clk) begin
        if (d_fs) fsw <= 40; else if (fsw > 0) fsw <= fsw - 1;
    end
    wire inwin = (fsw > 0) || (dut.ws == 3'd1) || (dut.ws == 3'd2 && (dut.widx < 6 || dut.widx >= 16'd31997)) || (dut.ws == 3'd3) || (dut.ws == 3'd4) || (dut.ws == 3'd5 && dut.widx < 6);
    always @(posedge clk) begin
        if (inwin && !won) begin won <= 1; $dumpon; end
        if (!inwin && won) begin won <= 0; $dumpoff; end
    end
    initial begin $dumpfile("ms.vcd"); $dumpvars(1, tb); $dumpoff; end
    function pixel; input integer x, y; input integer f;
        reg [31:0] h;
        begin h = (x * 32'h9E3779B1) ^ (y * 32'h85EBCA6B) ^ (f * 32'hC2B2AE35); h = h ^ (h >> 15); h = h * 32'h2C1B3C6D; h = h ^ (h >> 12);
              pixel = (h[3:0] < 6); end
    endfunction

    // ---------------------------------------------------------------- receiver
    reg [7:0] rx [0:140000]; integer nrx = 0; integer errors = 0; integer packets = 0; integer cur_frame = 0;
    reg rx_open = 0; integer clk_rises = 0;
    always @(posedge bus_clk) begin rx[nrx] <= bus_d; nrx <= nrx + 1; end
    // stability of the data around the strobe: bus_d must not change within 1 clock before / 2 clocks after the rising edge (checked on clk)
    reg [7:0] d_prev; reg clk_prev = 0; integer since_rise = 99;
    always @(posedge clk) begin
        d_prev <= bus_d; clk_prev <= bus_clk;
        if (bus_clk && !clk_prev) since_rise <= 0; else since_rise <= since_rise + 1;
        if (bus_d !== d_prev && since_rise < 2 && bus_clk !== 1'bx) begin errors = errors + 1; $display("FAIL data changed %0d clocks after strobe rise", since_rise); end
        if (bus_clk && !clk_prev && bus_d !== d_prev) begin errors = errors + 1; $display("FAIL data not stable at rise"); end
    end
    reg fs_prev = 0;
    integer expect_frame [0:15]; integer expect_cnt [0:15]; integer expect_len [0:15]; integer expect_rows [0:15]; integer nexp = 0;
    task check_packet; input integer k; input integer len;
        integer i, w, x, y, f, rows, cnt; reg [31:0] word, exp;
        begin
            f = expect_frame[k]; cnt = expect_cnt[k]; rows = expect_rows[k];
            if (len != 132128) begin errors = errors + 1; $display("FAIL packet %0d length %0d", k, len); end
            word = {rx[3], rx[2], rx[1], rx[0]}; if (word !== 32'h4D335441) begin errors = errors + 1; $display("FAIL magic %h", word); end
            word = {rx[7], rx[6], rx[5], rx[4]}; if (word !== k + 1 + (expect_frame[k] >= 100 ? 0 : 0)) begin $display("INFO seq %0d (packet %0d)", word, k); end
            word = {rx[11], rx[10], rx[9], rx[8]}; if (word !== ts[31:0]) begin errors = errors + 1; $display("FAIL ts lo %h", word); end
            for (y = 0; y < 800; y = y + 1)
                for (w = 0; w < 40; w = w + 1) begin
                    exp = 0;
                    if (y < rows) for (x = 0; x < 32; x = x + 1) exp[x] = pixel(w * 32 + x, y, f);
                    i = 16 + 4 * (y * 40 + w);
                    word = {rx[i + 3], rx[i + 2], rx[i + 1], rx[i]};
                    if (word !== exp) begin errors = errors + 1; if (errors < 10) $display("FAIL mask pkt %0d y=%0d w=%0d got %h exp %h", k, y, w, word, exp); end
                end
            i = 16 + 128000;
            word = {rx[i + 2], rx[i + 1], rx[i], rx[i]};
            word = {rx[i + 3], rx[i + 2], rx[i + 1], rx[i]};
            if (word[23:16] !== cnt) begin errors = errors + 1; $display("FAIL trailer count %h", word); end
            if (rows < 800 && !word[3]) begin errors = errors + 1; $display("FAIL short flag %h", word); end
            word = {rx[i + 7], rx[i + 6], rx[i + 5], rx[i + 4]}; if (word !== frame_sum) begin errors = errors + 1; $display("FAIL frame_sum %h", word); end
            word = {rx[i + 15], rx[i + 14], rx[i + 13], rx[i + 12]}; if (word !== ~{rx[7], rx[6], rx[5], rx[4]}) begin errors = errors + 1; $display("FAIL t3 %h", word); end
            for (w = 0; w < 1024; w = w + 1) begin
                i = 16 + 128000 + 16 + 4 * w;
                word = {rx[i + 3], rx[i + 2], rx[i + 1], rx[i]};
                exp = (w < 16 * cnt) ? (32'hA5000000 ^ (f << 16) ^ w) : 32'h0;
                if (w < 16 * cnt && word !== exp) begin errors = errors + 1; if (errors < 10) $display("FAIL cand w=%0d got %h exp %h", w, word, exp); end
            end
        end
    endtask
    integer pk_start;
    always @(posedge clk) begin
        fs_prev <= bus_fs;
        if (bus_fs && !fs_prev) begin pk_start = nrx; end                       // first strobe comes after the first fs clock; rx index restarts below
        if (!bus_fs && fs_prev) begin
            if (nexp > packets && expect_rows[packets] >= 0) begin
                $display("packet %0d: %0d bytes", packets, nrx);
                check_packet(packets, nrx);
            end
            packets = packets + 1; nrx = 0;
        end
    end

    // ---------------------------------------------------------------- sensor side
    integer nframes, late, shortf, abortf, fr, y, b, i, cnt, rows, use_cnt;
    task play_frame; input integer f; input integer nrows; input integer cand_cnt; input integer delay_done;
        integer yy, bb, ii;
        begin : play_frame_body
            expect_frame[nexp] = f; expect_cnt[nexp] = cand_cnt; expect_rows[nexp] = (abortf && f == 1) ? -1 : nrows; nexp = nexp + 1;
            @(posedge clk); d_fs <= 1; @(posedge clk); d_fs <= 0; @(posedge clk);
            for (yy = 0; yy < nrows; yy = yy + 1) begin
                for (bb = 0; bb < 640; bb = bb + 1) begin
                    d_valid <= 1; d_b0 <= pixel(2 * bb, yy, f); d_b1 <= pixel(2 * bb + 1, yy, f); d_last <= (bb == 639);
                    d_fe <= (bb == 639) && (yy == nrows - 1);
                    @(posedge clk);
                end
                d_valid <= 0; d_last <= 0; d_fe <= 0;
                repeat (686 - 640) @(posedge clk);
            end
            if (abortf && f == 1) disable play_frame_body;
            // candidate list (written by the labeller just before done)
            for (ii = 0; ii < 16 * cand_cnt; ii = ii + 1) begin c_we <= 1; c_waddr <= ii; c_wdata <= 32'hA5000000 ^ (f << 16) ^ ii; @(posedge clk); end
            c_we <= 0; repeat (185 + delay_done) @(posedge clk);
            ccl_count <= cand_cnt; ccl_flags <= 4'h0; ccl_maxrow <= 16'd590; ccl_done <= 1; @(posedge clk); ccl_done <= 0;
        end
    endtask
    initial begin
        if (!$value$plusargs("frames=%d", nframes)) nframes = 3;
        late = 0; shortf = 0; abortf = 0;
        if ($value$plusargs("late=%d", late)) ;
        if ($value$plusargs("short=%d", shortf)) ;
        if ($value$plusargs("abort=%d", abortf)) ;
        repeat (10) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        for (fr = 0; fr < nframes; fr = fr + 1) begin
            rows = (shortf && fr == 1) ? 500 : (abortf && fr == 1) ? 100 : 800;
            cnt = 7;
            play_frame(fr, rows, cnt, late ? 3000 : 0);
            repeat (4000) @(posedge clk);                       // inter-frame gap
            if (!(abortf && fr == 1)) begin : drain
                integer guard; guard = 0;
                while ((busy || bus_fs) && guard < 600000) begin @(posedge clk); guard = guard + 1; end   // a short frame is padded: the packet still takes 528k clocks
            end
            repeat (1000) @(posedge clk);
            ts <= ts + 64'h1_0000_0000 + 8333;
            frame_sum <= frame_sum + 1;
        end
        repeat (30000) @(posedge clk);
        if (packets != nframes) begin errors = errors + 1; $display("FAIL expected %0d packets got %0d", nframes, packets); end
        if (abortf && aborts != 1) begin errors = errors + 1; $display("FAIL aborts=%0d", aborts); end
        if (fifo_ovf != 0) begin errors = errors + 1; $display("FAIL fifo overflow %0d", fifo_ovf); end
        if (errors == 0) $display("PASS %0d packets", packets); else $display("FAIL %0d errors", errors);
        $finish;
    end
    initial begin #3000000000; $display("FAIL timeout"); $finish; end
endmodule
