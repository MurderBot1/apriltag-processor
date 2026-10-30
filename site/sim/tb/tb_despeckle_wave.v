// Waveform scenario: 3x3 majority filter (despeckle) on a small cropped mask (+mask= hex file, 1 byte/pixel).
`timescale 1ns/1ps
module tb;
    parameter COLS = 16;
    parameter ROWS = 12;
    parameter LINE = 40;
    reg clk = 0, rst = 1; always #5 clk = ~clk;
    reg [7:0] mask [0:4095];
    reg v = 0, b0 = 0, b1 = 0, fs = 0;
    wire ov, ob0, ob1, of, ol, ofs, ofe; wire [9:0] oy;
    despeckle #(.COLS(COLS), .ROWS(ROWS)) dut(.clk(clk), .rst(rst), .bypass(1'b0), .i_valid(v), .i_b0(b0), .i_b1(b1), .i_fs(fs),
        .o_valid(ov), .o_b0(ob0), .o_b1(ob1), .o_first(of), .o_last(ol), .o_y(oy), .o_fs(ofs), .o_fe(ofe));
    // ---- signals shown in the viewer
    wire in_valid = v, in_black0 = b0, in_black1 = b1, in_frame_start = fs;
    wire [9:0] in_row = dut.cur_row;
    wire [9:0] in_beat = dut.c;
    wire [1:0] win_prev_row = dut.pa1, win_this_row = dut.pb1, win_next_row = dut.pc1;
    wire [3:0] sum_px0 = dut.s0, sum_px1 = dut.s1;
    wire out_valid = ov, out_black0 = ob0, out_black1 = ob1, out_first = of, out_last = ol; wire [9:0] out_row = oy;
    wire out_frame_end = ofe;
    integer fd, n, y, c; reg [1023:0] f;
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb);
        if (!$value$plusargs("mask=%s", f)) $finish; $readmemh(f, mask);
        repeat (4) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        fs <= 1; @(posedge clk); fs <= 0; repeat (3) @(posedge clk);
        for (y = 0; y < ROWS; y = y + 1) begin
            for (c = 0; c < COLS; c = c + 1) begin v <= 1; b0 <= mask[y*COLS*2+2*c] != 0; b1 <= mask[y*COLS*2+2*c+1] != 0; @(posedge clk); end
            v <= 0; repeat (LINE - COLS) @(posedge clk);
        end
        repeat (LINE * 2) @(posedge clk);
        $finish;
    end
    integer ofd, ocol = 0;
    initial begin ofd = $fopen("despeckle_out.txt", "w"); end
    always @(posedge clk) if (ov) begin $fdisplay(ofd, "%0d %0d %0d %0d", oy, ocol, ob0, ob1); ocol <= ol ? 0 : ocol + 1; $fflush(ofd); end
endmodule
