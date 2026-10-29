// D-PHY receiver + CSI-2 packet layer testbench.  Drives two HS lane bit streams (+l0=, +l1= hex files, 32 UI/word,
// earliest bit = bit 0) with a DDR clock whose edges sit in the middle of each UI (as D-PHY does), into dphy_rx ->
// csi2_rx.  +nui=<UI count> +out=<log>.  Optional +cperiod=<ps> trims the core clock to emulate ppm offsets.
`timescale 1ns/1ps
`ifndef GEARREV
`define GEARREV 0
`endif
module tb_dphy;
    parameter LINES = 20;
    reg clk_p = 0; reg [1:0] d_p = 0;
    reg core_clk = 0, core_rst = 1;
    real core_half = 5.0;
    always #(core_half) core_clk = ~core_clk;
    wire hs_valid; wire [7:0] lane0, lane1; wire [3:0] status; wire pkt_end;
    wire pv, lf, ll, fs, fe, fok; wire [7:0] p0, p1; wire [15:0] ec, ed, ce, fb;
    dphy_rx #(.USE_PRIM(0), .BEH_REVERSE(`GEARREV)) rx(.clk_p(clk_p), .d_p(d_p), .core_clk(core_clk), .core_rst(core_rst), .pkt_end(pkt_end),
        .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1), .status(status));
    csi2_rx #(.LINES(LINES)) csi(.clk(core_clk), .rst(core_rst), .hs_valid(hs_valid), .lane0(lane0), .lane1(lane1),
        .pix_valid(pv), .pix0(p0), .pix1(p1), .line_first(lf), .line_last(ll), .fs(fs), .fe(fe), .pkt_end(pkt_end),
        .frame_ok(fok), .ecc_corrected(ec), .ecc_dropped(ed), .crc_errors(ce), .frames_bad(fb));
    reg [31:0] w0 [0:1000000]; reg [31:0] w1 [0:1000000];
    integer fd, i, nui, k;
    reg [1023:0] f; real cp;
    always @(posedge core_clk) begin
        if (pv) $fdisplay(fd, "P %0d %0d %0d %0d", lf, ll, p0, p1);
        if (fs) $fdisplay(fd, "FS");
        if (fe) $fdisplay(fd, "FE %0d", fok);
    end
    initial begin
        if (!$value$plusargs("l0=%s", f)) $finish; $readmemh(f, w0);
        if (!$value$plusargs("l1=%s", f)) $finish; $readmemh(f, w1);
        if (!$value$plusargs("nui=%d", nui)) $finish;
        if (!$value$plusargs("out=%s", f)) $finish;
        if ($value$plusargs("cperiod=%f", cp)) core_half = cp / 2.0;
        fd = $fopen(f, "w");
        #100 core_rst = 0;
        #50;
        for (i = 0; i < nui; i = i + 1) begin
            d_p[0] = w0[i/32][i%32]; d_p[1] = w1[i/32][i%32];
            #0.625 clk_p = ~clk_p;                 // clock edge in the middle of the UI
            #0.625;
        end
        #2000;
        $fdisplay(fd, "STAT ecc_corrected=%0d ecc_dropped=%0d crc_errors=%0d frames_bad=%0d status=%b", ec, ed, ce, fb, status);
        $fclose(fd);
        $finish;
    end
endmodule
