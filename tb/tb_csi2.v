// Plays a CSI-2 beat file (+in=hex, one 5-digit word per beat {hs_valid, lane1[7:0], lane0[7:0]} -> 17 bits)
// into csi2_rx and logs events to +out=file: "P first last p0 p1", "FS", "FE ok", and final statistics.
`timescale 1ns/1ps
module tb_csi2;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg [19:0] beats [0:2000000];
    reg hs = 0; reg [7:0] l0 = 0, l1 = 0;
    wire pv, lf, ll, fs, fe, fok; wire [7:0] p0, p1;
    wire [15:0] ecc_c, ecc_d, crc_e, fbad;
    csi2_rx #(.LINES(800)) dut(.clk(clk), .rst(rst), .hs_valid(hs), .lane0(l0), .lane1(l1), .pix_valid(pv), .pix0(p0),
        .pix1(p1), .line_first(lf), .line_last(ll), .fs(fs), .fe(fe), .frame_ok(fok), .ecc_corrected(ecc_c),
        .ecc_dropped(ecc_d), .crc_errors(crc_e), .frames_bad(fbad));
    integer fd, n, i, total;
    reg [1023:0] f;
    always @(posedge clk) begin
        if (pv) $fdisplay(fd, "P %0d %0d %0d %0d", lf, ll, p0, p1);
        if (fs) $fdisplay(fd, "FS");
        if (fe) $fdisplay(fd, "FE %0d", fok);
    end
    initial begin
        if (!$value$plusargs("in=%s", f)) $finish;
        $readmemh(f, beats);
        if (!$value$plusargs("n=%d", total)) $finish;
        if (!$value$plusargs("out=%s", f)) $finish;
        fd = $fopen(f, "w");
        repeat (10) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        for (i = 0; i < total; i = i + 1) begin
            hs <= beats[i][16]; l1 <= beats[i][15:8]; l0 <= beats[i][7:0]; @(posedge clk);
        end
        hs <= 0; repeat (20) @(posedge clk);
        $fdisplay(fd, "STAT ecc_corrected=%0d ecc_dropped=%0d crc_errors=%0d frames_bad=%0d", ecc_c, ecc_d, crc_e, fbad);
        $fclose(fd);
        $finish;
    end
endmodule
