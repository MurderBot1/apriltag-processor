// AprilTag camera core (architecture A3): CSI-2 in -> threshold -> despeckle -> {connected components, mask streamer} -> 8-bit bus to the MCU,
// plus register file, SPI slave bridge and OV9281 I2C bring-up.  The FPGA holds no frame store and no tag processor any more: the despeckled
// binary frame and the labeller's candidate list are streamed to the RP2350 (rtl/mask_stream.v), whose firmware runs the tag unit
// (firmware/core/attpu.c, bit-exact port of the old TPU).  A frame is only lost when the MCU has no free buffer (counted there).
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
    // MCU frame bus (rtl/mask_stream.v)
    output wire [7:0]  mcu_d,
    output wire        mcu_clk,
    output wire        mcu_fs,
    // misc
    output wire        csi_pkt_end,    // to the D-PHY receiver: packet consumed, re-arm sync hunt
    output reg         irq,            // level: a frame packet was sent to the MCU (cleared on status read)
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

    // ------------------------------------------------------------------ frame gating
    reg        gate, cancel;
    reg [31:0] frames_total, drop_gate;
    wire       stream_busy;
    always @(posedge clk) begin
        if (rst) begin
            gate <= 0; cancel <= 0; frames_total <= 0; drop_gate <= 0;
        end else begin
            if (csi_fs) begin
                frames_total <= frames_total + 1; cancel <= 0;
                if (ctrl_enable) gate <= 1;
                else begin gate <= 0; drop_gate <= drop_gate + 1; end
            end
            if (csi_fe && !csi_frame_ok) cancel <= 1;
        end
    end
    wire g_valid = pix_valid & gate;
    wire g_fs = csi_fs & ctrl_enable;
    wire g_fe = csi_fe & gate;

    // device clock: free-running 64-bit microsecond counter (1 MHz), latched at every accepted frame start (goes into the packet header)
    reg [15:0] us_acc; reg [63:0] time_us, ts_cur; reg [31:0] time_hi_lat, time_lo_lat;
    always @(posedge clk) begin
        if (rst) begin us_acc <= 0; time_us <= 0; ts_cur <= 0; time_hi_lat <= 0; time_lo_lat <= 0; end
        else begin
            if (us_acc + US_NUM >= US_DEN) begin us_acc <= us_acc + US_NUM - US_DEN; time_us <= time_us + 1; end else us_acc <= us_acc + US_NUM;
            if (g_fs) ts_cur <= time_us;
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

    // ------------------------------------------------------------------ connected components
    wire        c_we; wire [9:0] c_waddr; wire [31:0] c_wdata; wire ccl_done; wire [7:0] ccl_count; wire [3:0] ccl_flags;
    wire [15:0] ccl_maxrow;
    run_ccl ccl(.clk(clk), .rst(rst), .cfg_min_area(min_area), .cfg_max_area(max_area), .cfg_min_dim(thr_mindim),
        .cfg_reject_border(ctrl_reject_border), .v(d_valid), .b0(d_b0), .b1(d_b1), .first(d_first), .last(d_last),
        .fstart(d_fs), .fend(d_fe), .cand_we(c_we), .cand_waddr(c_waddr), .cand_wdata(c_wdata), .done(ccl_done),
        .cand_count(ccl_count), .flags(ccl_flags), .max_row_cycles(ccl_maxrow));

    // ------------------------------------------------------------------ mask + candidate stream to the MCU
    wire [31:0] ms_sent; wire [15:0] ms_aborts, ms_ovf; wire [7:0] ms_count; wire ms_pkt_end;
    mask_stream ms(.clk(clk), .rst(rst), .enable(ctrl_enable), .d_valid(d_valid), .d_b0(d_b0), .d_b1(d_b1), .d_last(d_last),
        .d_fs(d_fs), .d_fe(d_fe), .csi_fe(g_fe), .c_we(c_we), .c_waddr(c_waddr), .c_wdata(c_wdata), .ccl_done(ccl_done), .ccl_count(ccl_count),
        .ccl_flags(ccl_flags), .ccl_maxrow(ccl_maxrow), .ts(ts_cur), .frame_sum(frame_sum), .frame_bad(cancel), .busy_err(busy_err),
        .bus_d(mcu_d), .bus_clk(mcu_clk), .bus_fs(mcu_fs), .frames_sent(ms_sent), .aborts(ms_aborts), .fifo_ovf(ms_ovf),
        .last_count(ms_count), .busy(stream_busy), .pkt_end(ms_pkt_end));
    always @(posedge clk) begin
        if (rst) irq <= 0;
        else begin
            if (ms_pkt_end) irq <= 1;
            if (bus_re && bus_addr[23:0] == 24'h000018) irq <= 0;
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

    // read pipeline: latch address, mux the cycle after
    reg [23:0] ra_q;
    wire [31:0] status = {ms_sent[15:0], ms_count, 4'd0, init_done, stream_busy, 1'b0, |ms_sent};
    reg [31:0] regmux;
    always @* begin
        case (ra_q[7:2])
            6'h00: regmux = 32'h41544731;
            6'h01: regmux = 32'h00020000;                    // version 2.0: A3 (no TPU / frame store in the FPGA)
            6'h02: regmux = {29'd0, ctrl_despeckle, ctrl_reject_border, ctrl_enable};
            6'h03: regmux = {2'd0, thr_maxham, thr_mindim, thr_abs, thr_diff};
            6'h04: regmux = {8'd0, min_area};
            6'h05: regmux = {8'd0, max_area};
            6'h06: regmux = status;
            6'h07: regmux = ms_sent;
            6'h08: regmux = {ecc_d, ecc_c};
            6'h09: regmux = {fr_bad, crc_e};
            6'h0A: regmux = {ccl_maxrow, 4'd0, ccl_flags, ccl_count};
            6'h0B: regmux = {ms_ovf, ms_aborts};              // streamer: FIFO overflows, aborted packets
            6'h0C: regmux = drop_gate;
            6'h0D: regmux = frames_total;
            6'h0E: regmux = ms_sent;
            6'h0F: regmux = {16'd0, line_cyc};
            6'h10: regmux = {i2c_go_h, i2c_rw_h, 7'd0, i2c_dev_h, i2c_reg_h};
            6'h11: regmux = {22'd0, i2c_nack, i2c_busy, i2c_rdata};
            6'h14: regmux = {16'd0, init_nacks, 7'd0, init_done};
            6'h16: regmux = scratch;
            6'h17: regmux = {30'd0, busy_err, cancel};
            6'h18: regmux = frame_sum;
            6'h19: regmux = time_lo_lat;
            6'h1A: regmux = time_hi_lat;
            default: regmux = 32'h0;
        endcase
    end
    always @(posedge clk) begin
        if (bus_re) ra_q <= bus_addr;
        bus_rdata <= regmux;
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

    assign leds = {stream_busy, irq, init_done, gate};
endmodule
