// Streams a binary frame (+mask=) through despeckle and dumps the output mask (+out=).  +bypass=1 tests bypass.
`timescale 1ns/1ps
module tb_despeckle;
    parameter LINE = 700;
    reg clk = 0, rst = 1; always #5 clk = ~clk;
    reg [7:0] mask [0:1280*800-1]; reg [7:0] outm [0:1280*800-1];
    reg v = 0, b0 = 0, b1 = 0, fs = 0, bypass = 0;
    wire ov, ob0, ob1, of, ol, ofs, ofe; wire [9:0] oy;
    despeckle dut(.clk(clk), .rst(rst), .bypass(bypass), .i_valid(v), .i_b0(b0), .i_b1(b1), .i_fs(fs),
        .o_valid(ov), .o_b0(ob0), .o_b1(ob1), .o_first(of), .o_last(ol), .o_y(oy), .o_fs(ofs), .o_fe(ofe));
    integer fd, n, y, c, beats = 0, rows = 0, bad = 0, fs_n = 0, fe_n = 0, firsts = 0;
    reg [9:0] ecol = 0; reg [9:0] ey = 0;
    always @(posedge clk) if (ov) begin
        beats = beats + 1;
        if (bypass) begin outm[(beats-1)*2] <= ob0; outm[(beats-1)*2+1] <= ob1; end
        else begin
            outm[oy*1280 + ecol*2] <= ob0; outm[oy*1280 + ecol*2 + 1] <= ob1;
            if (of && ecol != 0) bad = bad + 1;
            if (of) firsts = firsts + 1;
            if (ol) begin if (ecol != 639) bad = bad + 1; ecol <= 0; rows = rows + 1; end else ecol <= ecol + 1;
        end
    end
    always @(posedge clk) begin if (ofs) fs_n = fs_n + 1; if (ofe) fe_n = fe_n + 1; end
    reg [1023:0] f;
    initial begin
        if (!$value$plusargs("mask=%s", f)) $finish; fd = $fopen(f, "rb"); n = $fread(mask, fd); $fclose(fd);
        if ($value$plusargs("bypass=%d", n)) bypass = n;
        repeat (10) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        fs <= 1; @(posedge clk); fs <= 0; repeat (5) @(posedge clk);
        for (y = 0; y < 800; y = y + 1) begin
            for (c = 0; c < 640; c = c + 1) begin v <= 1; b0 <= mask[y*1280+2*c] != 0; b1 <= mask[y*1280+2*c+1] != 0; @(posedge clk); end
            v <= 0; repeat (LINE - 640) @(posedge clk);
        end
        repeat (2000) @(posedge clk);
        $display("RESULT rows=%0d beats=%0d bad=%0d fs=%0d fe=%0d firsts=%0d", rows, beats, bad, fs_n, fe_n, firsts);
        if (!$value$plusargs("out=%s", f)) $finish;
        fd = $fopen(f, "wb"); for (n = 0; n < 1280*800; n = n + 1) $fwrite(fd, "%c", outm[n] ? 8'd1 : 8'd0); $fclose(fd);
        $finish;
    end
endmodule
