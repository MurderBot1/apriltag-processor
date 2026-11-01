// Cost-down experiment: FPGA "front end only" = D-PHY RX + CSI-2 + tile threshold + despeckle (no frame banks, CCL or TPU).
// Used only to check what a small ECP5 (25F/45F, slower speed grades) needs for capture + binarize (resources, D-PHY/core fmax).
// Outputs are the despeckled 2-bit-per-clock mask stream; fixed thresholds (diff 24, abs 64), 686-clock line like the real design.
`timescale 1ns/1ps
module fe_top (
    input  wire clk_24m, input wire mipi_clk_p, input wire [1:0] mipi_d_p, output wire sensor_xvclk,
    output wire o_valid, output wire o_b0, output wire o_b1, output wire o_first, output wire o_last, output wire [3:0] o_dbg);
    wire clk100, clk24, clk200, locked;
    sys_pll pll(.clkin(clk_24m), .clkout0(clk100), .clkout1(clk24), .clkout2(clk200), .locked(locked));
    assign sensor_xvclk = clk24;
    reg [4:0] rc = 0; reg rst = 1;
    always @(posedge clk100) begin if (!locked) begin rc <= 0; rst <= 1; end else if (rc != 31) rc <= rc + 1; else rst <= 0; end
    wire hs_valid, pkt_end; wire [7:0] lane0, lane1; wire [3:0] st;
    dphy_rx #(.USE_PRIM(1)) dphy(.clk_p(mipi_clk_p), .d_p(mipi_d_p), .core_clk(clk100), .core_rst(rst), .pkt_end(pkt_end), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .status(st));
    wire pv, lf, ll, fs, fe, fok; wire [7:0] p0, p1; wire [15:0] a, b, c, d;
    csi2_rx rx(.clk(clk100), .rst(rst), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .pix_valid(pv), .pix0(p0), .pix1(p1), .line_first(lf), .line_last(ll),
        .fs(fs), .fe(fe), .pkt_end(pkt_end), .frame_ok(fok), .ecc_corrected(a), .ecc_dropped(b), .crc_errors(c), .frames_bad(d));
    wire bv, b0, b1, bf, bl, bfs, bfe, be; wire [9:0] by;
    thresh_binarize #(.LINE_CYC(800)) th(.clk(clk100), .rst(rst), .cfg_diff_min(8'd24), .cfg_abs_black(8'd64), .cfg_ratio(2'd0), .cfg_line_cyc(16'd686), .vin_valid(pv), .vin_p0(p0), .vin_p1(p1),
        .vin_fs(fs), .vin_fe(fe), .o_valid(bv), .o_b0(b0), .o_b1(b1), .o_first(bf), .o_last(bl), .o_y(by), .o_frame_start(bfs), .o_frame_end(bfe), .o_busy_err(be));
    wire dv, d0, d1, df, dl, dfs, dfe; wire [9:0] dy;
    despeckle dsp(.clk(clk100), .rst(rst), .bypass(1'b0), .i_valid(bv), .i_b0(b0), .i_b1(b1), .i_fs(bfs), .o_valid(dv), .o_b0(d0), .o_b1(d1), .o_first(df), .o_last(dl), .o_y(dy), .o_fs(dfs), .o_fe(dfe));
    assign o_valid = dv; assign o_b0 = d0; assign o_b1 = d1; assign o_first = df; assign o_last = dl;
    assign o_dbg = {be ^ fok ^ ^dy, st[2:0] ^ {^a, ^b, ^c ^ ^d}};
endmodule
