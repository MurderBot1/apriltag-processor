// AprilTag camera core: CSI-2 in -> threshold -> binary frame store + CCL -> TPU (edge refine + decode) -> results,
// plus register file, SPI slave bridge and OV9281 I2C bring-up.  Two ping-pong banks of
// {binary frame, candidate list, result list} let the sensor stream at full 120 fps while the TPU works on the
// previous frame.  A frame is dropped (and counted) only if the TPU is still busy with the bank it would overwrite.
`timescale 1ns/1ps
module cam_core #(
    parameter LINE_CYC_DEFAULT = 686,          // core clocks per sensor line: 8.0 us @ 85.714 MHz (use 800 @ 100 MHz)
    parameter POWERUP_CLKS = 2_000_000,
    parameter MS_CLKS = 100_000,
    parameter US_NUM = 1,                      // device clock tick (1 MHz) = US_NUM / US_DEN core clocks, exact: 1/100 @ 100 MHz,
    parameter US_DEN = 100,                    // 7/600 @ 85.714 MHz (=600/7 MHz)
    parameter I2C_QDIV = 62,
    parameter SENSOR_HEX = "rtl/sensor_init.hex"
) (
    input  wire        clk,
    input  wire        rst,
    // CSI-2 D-PHY RX output (byte aligned, HS burst valid)
    input  wire        hs_valid,
    input  wire [7:0]  lane0,
    input  wire [7:0]  lane1,
    // SPI slave (MCU)
    input  wire        sck,
    input  wire        cs_n,
    input  wire        mosi,
    output wire        miso,
    output wire        miso_oe,
    // sensor I2C (open drain)
    output wire        scl_oe,
    output wire        sda_oe,
    input  wire        sda_i,
    // misc
    output wire        csi_pkt_end,    // to the D-PHY receiver: packet consumed, re-arm sync hunt
    output reg         irq,            // level: a new result set is ready (cleared on status read)
    output wire [3:0]  leds
);
    wire [23:0] bus_addr; wire bus_re, bus_we; wire [31:0] bus_wdata; reg [31:0] bus_rdata;
    wire bus_re_pulse = bus_re;
    // ------------------------------------------------------------------ registers
    reg        ctrl_enable, ctrl_reject_border, ctrl_despeckle;
    reg [7:0]  thr_diff, thr_abs, thr_mindim; reg [5:0] thr_maxham;
    reg [23:0] min_area, max_area;
    reg [15:0] line_cyc;
    reg [31:0] scratch;
    reg        i2c_go_h; reg i2c_rw_h; reg [6:0] i2c_dev_h; reg [15:0] i2c_reg_h; reg [7:0] i2c_wd_h;

    // ------------------------------------------------------------------ CSI-2 receiver
    wire pix_valid, line_first, line_last, csi_fs, csi_fe, csi_frame_ok;
    wire [7:0] pix0, pix1;
    wire [15:0] ecc_c, ecc_d, crc_e, fr_bad;
    csi2_rx rx(.clk(clk), .rst(rst), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .pix_valid(pix_valid),
        .pix0(pix0), .pix1(pix1), .line_first(line_first), .line_last(line_last), .fs(csi_fs), .fe(csi_fe), .pkt_end(csi_pkt_end),
        .frame_ok(csi_frame_ok), .ecc_corrected(ecc_c), .ecc_dropped(ecc_d), .crc_errors(crc_e), .frames_bad(fr_bad));

    // ------------------------------------------------------------------ frame gating / bank selection
    reg        cur_bank, gate, cancel;
    reg        tpu_busy_q; reg tpu_bank;
    wire       tpu_busy, tpu_done;
    reg [31:0] frames_total, drop_gate, drop_busy, frames_processed, frame_seq;
    wire [31:0] frames_dropped = drop_gate + drop_busy;
    always @(posedge clk) begin
        if (rst) begin
            cur_bank <= 1; gate <= 0; cancel <= 0; frames_total <= 0; drop_gate <= 0;
        end else begin
            if (csi_fs) begin
                frames_total <= frames_total + 1; cancel <= 0;
                if (ctrl_enable && !(tpu_busy && tpu_bank == ~cur_bank)) begin gate <= 1; cur_bank <= ~cur_bank; end
                else begin gate <= 0; drop_gate <= drop_gate + 1; end
            end
            if (csi_fe && !csi_frame_ok) cancel <= 1;
        end
    end
    wire g_valid = pix_valid & gate;
    wire g_fs = csi_fs & ctrl_enable & ~(tpu_busy && tpu_bank == ~cur_bank);
    wire g_fe = csi_fe & gate;

    // device clock: free-running 64-bit microsecond counter (1 MHz), latched at every accepted frame start per capture bank
    reg [15:0] us_acc; reg [63:0] time_us, ft0, ft1; reg [31:0] time_hi_lat, time_lo_lat;
    always @(posedge clk) begin
        if (rst) begin us_acc <= 0; time_us <= 0; ft0 <= 0; ft1 <= 0; time_hi_lat <= 0; time_lo_lat <= 0; end
        else begin
            if (us_acc + US_NUM >= US_DEN) begin us_acc <= us_acc + US_NUM - US_DEN; time_us <= time_us + 1; end else us_acc <= us_acc + US_NUM;
            if (g_fs) begin if (cur_bank) ft0 <= time_us; else ft1 <= time_us; end    // bank flips on this edge: new bank = ~cur_bank
            if (bus_re && bus_addr[7:2] == 6'h19) begin time_hi_lat <= time_us[63:32]; time_lo_lat <= time_us[31:0]; end
        end
    end

    // frame brightness sum (for the MCU's auto exposure): sum of all pixels of the last gated frame
    reg [31:0] sum_acc, frame_sum;
    always @(posedge clk) begin
        if (rst) begin sum_acc <= 0; frame_sum <= 0; end
        else begin
            if (g_fs) sum_acc <= 0;
            else if (g_valid) sum_acc <= sum_acc + pix0 + pix1;
            if (g_fe) frame_sum <= sum_acc;
        end
    end

    // ------------------------------------------------------------------ threshold / binarize
    wire b_valid, b0, b1, b_first, b_last, b_fs, b_fe, busy_err; wire [9:0] b_y;
    thresh_binarize #(.LINE_CYC(800)) th(.clk(clk), .rst(rst), .cfg_diff_min(thr_diff), .cfg_abs_black(thr_abs),
        .cfg_line_cyc(line_cyc), .vin_valid(g_valid), .vin_p0(pix0), .vin_p1(pix1), .vin_fs(g_fs), .vin_fe(g_fe),
        .o_valid(b_valid), .o_b0(b0), .o_b1(b1), .o_first(b_first), .o_last(b_last), .o_y(b_y),
        .o_frame_start(b_fs), .o_frame_end(b_fe), .o_busy_err(busy_err));

    // ------------------------------------------------------------------ memories (ping-pong)
    reg [31:0] fb0 [0:31999]; reg [31:0] fb1 [0:31999];
    reg [31:0] cand0 [0:1023]; reg [31:0] cand1 [0:1023];
    reg [31:0] res0 [0:511];  reg [31:0] res1 [0:511];
    integer zi;
`ifndef SYNTHESIS
    initial begin   // deterministic power-up contents for simulation
        for (zi = 0; zi < 512; zi = zi + 1) begin res0[zi] = 0; res1[zi] = 0; end
        for (zi = 0; zi < 1024; zi = zi + 1) begin cand0[zi] = 0; cand1[zi] = 0; end
        for (zi = 0; zi < 32000; zi = zi + 1) begin fb0[zi] = 0; fb1[zi] = 0; end
    end
`endif

    // 3x3 majority despeckle between binarize and everything downstream (bypassable)
    wire d_valid_i, d_b0_i, d_b1_i, d_first_i, d_last_i, d_fs_i, d_fe_i; wire [9:0] d_y_i;
    despeckle dsp(.clk(clk), .rst(rst), .bypass(1'b0), .i_valid(b_valid), .i_b0(b0), .i_b1(b1), .i_fs(b_fs),
        .o_valid(d_valid_i), .o_b0(d_b0_i), .o_b1(d_b1_i), .o_first(d_first_i), .o_last(d_last_i), .o_y(d_y_i), .o_fs(d_fs_i), .o_fe(d_fe_i));
    wire d_valid = ctrl_despeckle ? d_valid_i : b_valid;
    wire d_b0 = ctrl_despeckle ? d_b0_i : b0;
    wire d_b1 = ctrl_despeckle ? d_b1_i : b1;
    wire d_first = ctrl_despeckle ? d_first_i : b_first;
    wire d_last = ctrl_despeckle ? d_last_i : b_last;
    wire d_fs = ctrl_despeckle ? d_fs_i : b_fs;
    wire d_fe = ctrl_despeckle ? d_fe_i : b_fe;
    wire [9:0] d_y = ctrl_despeckle ? d_y_i : b_y;

    // binary frame packer: 2 pixels per beat, 16 beats per word, bit x%32 = pixel x
    reg [31:0] pack; reg [9:0] ocol;
    reg        wr_bank_q;
    wire [15:0] fb_waddr = d_y * 16'd40 + {12'd0, ocol[9:4]};
    wire [31:0] pack_n = {d_b1, d_b0, pack[31:2]};
    always @(posedge clk) begin
        if (d_fs) wr_bank_q <= cur_bank;
        if (d_valid) begin
            pack <= pack_n;
            if (ocol[3:0] == 4'd15) begin
                if (cur_bank) fb1[fb_waddr] <= pack_n; else fb0[fb_waddr] <= pack_n;
            end
            ocol <= d_last ? 10'd0 : ocol + 1;
        end
        if (rst) ocol <= 0;
    end

    // ------------------------------------------------------------------ connected components
    wire        c_we; wire [9:0] c_waddr; wire [31:0] c_wdata; wire ccl_done; wire [7:0] ccl_count; wire [3:0] ccl_flags;
    wire [15:0] ccl_maxrow;
    run_ccl ccl(.clk(clk), .rst(rst), .cfg_min_area(min_area), .cfg_max_area(max_area), .cfg_min_dim(thr_mindim),
        .cfg_reject_border(ctrl_reject_border), .v(d_valid), .b0(d_b0), .b1(d_b1), .first(d_first), .last(d_last),
        .fstart(d_fs), .fend(d_fe), .cand_we(c_we), .cand_waddr(c_waddr), .cand_wdata(c_wdata), .done(ccl_done),
        .cand_count(ccl_count), .flags(ccl_flags), .max_row_cycles(ccl_maxrow));
    always @(posedge clk) if (c_we) begin if (cur_bank) cand1[c_waddr] <= c_wdata; else cand0[c_waddr] <= c_wdata; end

    // ------------------------------------------------------------------ TPU
    reg        tpu_start; reg [7:0] tpu_count;
    wire [9:0] t_craddr; wire [15:0] t_fbaddr; wire t_we; wire [8:0] t_waddr; wire [31:0] t_wdata, t_cycles;
    reg [31:0] t_cand_q, t_fb_q;
    wire [31:0] bus_fb_q_dummy;
    reg [31:0] t_cand0_q, t_cand1_q; reg t_bank_q;
    always @(posedge clk) begin
        t_cand0_q <= cand0[t_craddr]; t_cand1_q <= cand1[t_craddr]; t_bank_q <= tpu_bank;
    end
    always @* t_cand_q = t_bank_q ? t_cand1_q : t_cand0_q;
    // shared frame read port: TPU has priority, SPI debug reads get it when the TPU is idle
    reg        spi_fb_req; reg [15:0] spi_fb_addr; reg spi_fb_bank;
    wire [15:0] fb_raddr = tpu_busy ? t_fbaddr : spi_fb_addr;
    wire        fb_rbank = tpu_busy ? tpu_bank : spi_fb_bank;
    reg [31:0]  fb_q;
    reg [31:0] fb0_q, fb1_q; reg fb_bank_q;
    always @(posedge clk) begin fb0_q <= fb0[fb_raddr]; fb1_q <= fb1[fb_raddr]; fb_bank_q <= fb_rbank; end
    always @* fb_q = fb_bank_q ? fb1_q : fb0_q;
    reg [31:0] fbq_bus; always @(posedge clk) fbq_bus <= fb_q;            // registered copy for the (slow) SPI read path
    tpu_core tpu(.clk(clk), .rst(rst), .start(tpu_start), .busy(tpu_busy), .done(tpu_done), .cfg_frame_id(frame_seq),
        .cfg_maxham(thr_maxham), .cand_count(tpu_count), .cfg_minside(8'd8), .cand_raddr(t_craddr), .cand_rdata(t_cand_q),
        .res_we(t_we), .res_waddr(t_waddr), .res_wdata(t_wdata), .fb_addr(t_fbaddr), .fb_data(fb_q), .cycle_count(t_cycles));
    always @(posedge clk) if (t_we) begin if (tpu_bank) res1[t_waddr] <= t_wdata; else res0[t_waddr] <= t_wdata; end

    // pipeline control: ccl done -> start TPU on the bank that frame was written to
    reg        res_bank, res_valid; reg [15:0] res_seq; reg [7:0] res_count; reg [31:0] last_cycles;
    reg [31:0] res_frame;
    always @(posedge clk) begin
        tpu_start <= 0;
        if (rst) begin
            tpu_bank <= 0; drop_busy <= 0; res_valid <= 0; res_seq <= 0; res_count <= 0; frames_processed <= 0; frame_seq <= 0;
            irq <= 0; last_cycles <= 0; res_bank <= 0; res_frame <= 0;
        end else begin
            if (ccl_done) begin
                if (cancel || tpu_busy) begin drop_busy <= drop_busy + 1; end
                else begin
                    tpu_bank <= cur_bank; tpu_count <= ccl_count; tpu_start <= 1; frame_seq <= frame_seq + 1;
                end
            end
            if (t_we && t_waddr == 9'd0) res_count <= t_wdata[7:0];
            if (tpu_done) begin
                res_bank <= tpu_bank; res_valid <= 1; res_seq <= res_seq + 1; last_cycles <= t_cycles;
                frames_processed <= frames_processed + 1; irq <= 1; res_frame <= frame_seq;
            end
            if (bus_re_pulse && bus_addr[23:0] == 24'h000018) irq <= 0;
        end
    end

    // ------------------------------------------------------------------ I2C + sensor init
    wire i2c_go_i, i2c_done, i2c_nack, i2c_busy, init_done; wire [15:0] i2c_reg_i; wire [7:0] i2c_data_i, i2c_rdata;
    wire [6:0] i2c_dev_i; wire [7:0] init_nacks;
    wire        m_go  = init_done ? i2c_go_h : i2c_go_i;
    wire        m_rw  = init_done ? i2c_rw_h : 1'b0;
    wire [6:0]  m_dev = init_done ? i2c_dev_h : i2c_dev_i;
    wire [15:0] m_reg = init_done ? i2c_reg_h : i2c_reg_i;
    wire [7:0]  m_wd  = init_done ? i2c_wd_h : i2c_data_i;
    i2c_master #(.QDIV(I2C_QDIV)) i2c(.clk(clk), .rst(rst), .go(m_go), .rw(m_rw), .dev(m_dev), .reg_addr(m_reg),
        .wdata(m_wd), .rdata(i2c_rdata), .busy(i2c_busy), .done(i2c_done), .nack(i2c_nack), .scl_oe(scl_oe),
        .sda_oe(sda_oe), .sda_i(sda_i));
    sensor_init #(.HEX(SENSOR_HEX), .POWERUP_CLKS(POWERUP_CLKS), .MS_CLKS(MS_CLKS)) sinit(.clk(clk), .rst(rst),
        .i2c_done(i2c_done), .i2c_nack(i2c_nack), .i2c_busy(i2c_busy), .i2c_go(i2c_go_i), .i2c_reg(i2c_reg_i),
        .i2c_data(i2c_data_i), .i2c_dev(i2c_dev_i), .init_done(init_done), .nack_count(init_nacks));

    // ------------------------------------------------------------------ SPI bus
    spi_slave spi(.clk(clk), .rst(rst), .sck(sck), .cs_n(cs_n), .mosi(mosi), .miso(miso), .miso_oe(miso_oe),
        .bus_addr(bus_addr), .bus_re(bus_re), .bus_rdata(bus_rdata), .bus_we(bus_we), .bus_wdata(bus_wdata));

    // read pipeline: latch address, memories read next cycle, mux the cycle after
    reg [23:0] ra_q; reg [1:0] rpipe;
    reg [31:0] res0_q, res1_q, cand0_q, cand1_q, reg_q;
    wire [31:0] status = {res_seq, res_count, 4'd0, init_done, tpu_busy, res_bank, res_valid};
    reg [31:0] regmux;
    always @* begin
        case (ra_q[7:2])
            6'h00: regmux = 32'h41544731;
            6'h01: regmux = 32'h00010000;
            6'h02: regmux = {29'd0, ctrl_despeckle, ctrl_reject_border, ctrl_enable};
            6'h03: regmux = {2'd0, thr_maxham, thr_mindim, thr_abs, thr_diff};
            6'h04: regmux = {8'd0, min_area};
            6'h05: regmux = {8'd0, max_area};
            6'h06: regmux = status;
            6'h07: regmux = res_frame;
            6'h08: regmux = {ecc_d, ecc_c};
            6'h09: regmux = {fr_bad, crc_e};
            6'h0A: regmux = {ccl_maxrow, 4'd0, ccl_flags, ccl_count};
            6'h0B: regmux = last_cycles;
            6'h0C: regmux = frames_dropped;
            6'h0D: regmux = frames_total;
            6'h0E: regmux = frames_processed;
            6'h0F: regmux = {16'd0, line_cyc};
            6'h10: regmux = {i2c_go_h, i2c_rw_h, 7'd0, i2c_dev_h, i2c_reg_h};
            6'h11: regmux = {22'd0, i2c_nack, i2c_busy, i2c_rdata};
            6'h14: regmux = {16'd0, init_nacks, 7'd0, init_done};
            6'h16: regmux = scratch;
            6'h17: regmux = {30'd0, busy_err, cancel};
            6'h18: regmux = frame_sum;
            6'h19: regmux = time_lo_lat;
            6'h1A: regmux = time_hi_lat;
            6'h1B: regmux = ft0[31:0];
            6'h1C: regmux = ft0[63:32];
            6'h1D: regmux = ft1[31:0];
            6'h1E: regmux = ft1[63:32];
            default: regmux = 32'h0;
        endcase
    end
    always @(posedge clk) begin
        spi_fb_req <= 0;
        if (bus_re) begin
            ra_q <= bus_addr; rpipe <= 2'd1;
        end else if (rpipe != 0) rpipe <= rpipe - 1;
        res0_q <= res0[ra_q[10:2]]; res1_q <= res1[ra_q[10:2]];
        if (ra_q[23:20] == 4'h1 || ra_q[23:20] == 4'h2) bus_rdata <= tpu_busy ? 32'hBAD0BAD0 : fbq_bus;
        else if (ra_q[23:12] == 12'h001) bus_rdata <= res0_q;
        else if (ra_q[23:12] == 12'h002) bus_rdata <= res1_q;
        else bus_rdata <= regmux;
    end
    // fb read address for SPI must follow the latched bus address a cycle later too
    always @(posedge clk) if (!tpu_busy && (ra_q[23:20] == 4'h1 || ra_q[23:20] == 4'h2)) begin
        spi_fb_bank <= ra_q[21]; spi_fb_addr <= ra_q[17:2];
    end

    // register writes
    always @(posedge clk) begin
        i2c_go_h <= 0;
        if (rst) begin
            ctrl_enable <= 1; ctrl_reject_border <= 1; ctrl_despeckle <= 1; thr_diff <= 24; thr_abs <= 64; thr_mindim <= 10; thr_maxham <= 2;
            min_area <= 100; max_area <= 400000; line_cyc <= LINE_CYC_DEFAULT; scratch <= 0;
            i2c_rw_h <= 0; i2c_dev_h <= 7'h60; i2c_reg_h <= 0; i2c_wd_h <= 0;
        end else if (bus_we && bus_addr[23:12] == 12'h000) begin
            case (bus_addr[7:2])
                6'h02: begin ctrl_enable <= bus_wdata[0]; ctrl_reject_border <= bus_wdata[1]; ctrl_despeckle <= bus_wdata[2]; end
                6'h03: begin thr_diff <= bus_wdata[7:0]; thr_abs <= bus_wdata[15:8]; thr_mindim <= bus_wdata[23:16]; thr_maxham <= bus_wdata[29:24]; end
                6'h04: min_area <= bus_wdata[23:0];
                6'h05: max_area <= bus_wdata[23:0];
                6'h0F: line_cyc <= bus_wdata[15:0];
                6'h10: begin i2c_reg_h <= bus_wdata[15:0]; i2c_dev_h <= bus_wdata[22:16] == 0 ? 7'h60 : bus_wdata[22:16];
                             i2c_rw_h <= bus_wdata[30]; i2c_go_h <= bus_wdata[31]; end
                6'h11: i2c_wd_h <= bus_wdata[7:0];
                6'h16: scratch <= bus_wdata;
                default: ;
            endcase
        end
    end

    assign leds = {tpu_busy, irq, init_done, gate};
endmodule
