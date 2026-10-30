// Waveform scenario: CSI-2 packet layer.  Plays a beat file (+in=, +n=) into csi2_rx and dumps chosen signals (+vcd=).
// Adapted from tb/tb_csi2.v (unchanged DUT); the beat format is {hs_valid, lane1[7:0], lane0[7:0]}.
`timescale 1ns/1ps
module tb;
    parameter LINES = 3;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg [19:0] beats [0:4095];
    reg hs = 0; reg [7:0] l0 = 0, l1 = 0;
    wire pv, lf, ll, fs, fe, fok; wire [7:0] p0, p1;
    wire [15:0] ecc_c, ecc_d, crc_e, fbad;
    csi2_rx #(.LINES(LINES)) dut(.clk(clk), .rst(rst), .hs_valid(hs), .lane0(l0), .lane1(l1), .pix_valid(pv), .pix0(p0),
        .pix1(p1), .line_first(lf), .line_last(ll), .fs(fs), .fe(fe), .frame_ok(fok), .ecc_corrected(ecc_c),
        .ecc_dropped(ecc_d), .crc_errors(crc_e), .frames_bad(fbad));
    // ---- signals shown in the viewer (friendly names)
    wire [2:0]  state     = dut.st;
    wire [15:0] beats_left = dut.beats_left;
    wire [15:0] crc_run   = dut.crc;
    wire [5:0]  ecc_syndrome = dut.syn;
    wire        hdr_ok    = dut.hdr_ok0;
    wire        hdr_1bit  = dut.hdr_1bit;
    wire [15:0] line_count = dut.lines;
    wire        frame_err = dut.frame_err;
    wire [7:0]  hdr_di = dut.h_di, hdr_wc0 = dut.h_wc0, hdr_wc1 = dut.h_wc1, hdr_ecc = dut.h_ecc;
    wire hs_valid = hs; wire [7:0] lane0 = l0, lane1 = l1;
    wire pix_valid = pv; wire [7:0] pix0 = p0, pix1 = p1; wire line_first = lf, line_last = ll, frame_ok = fok;
    wire [15:0] ecc_corrected = ecc_c, ecc_dropped = ecc_d, crc_errors = crc_e, frames_bad = fbad;
    integer i, total; reg [1023:0] f;
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb);
        if (!$value$plusargs("in=%s", f)) $finish;
        $readmemh(f, beats);
        if (!$value$plusargs("n=%d", total)) $finish;
        repeat (4) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        for (i = 0; i < total; i = i + 1) begin
            hs <= beats[i][16]; l1 <= beats[i][15:8]; l0 <= beats[i][7:0]; @(posedge clk);
        end
        hs <= 0; repeat (12) @(posedge clk);
        $finish;
    end
endmodule
