// Feeds one or two binary frames (+mask=, +mask2= : 1 byte/pixel) into run_ccl at 120fps line timing and
// dumps the candidate RAM after each frame (+out=, +out2=: count line, then hex words) plus status.
`timescale 1ns/1ps
module tb_ccl;
    parameter LINE = 905;
    integer line_n = LINE;                      // +line=<clocks per sensor line> overrides (686 = real 85.714 MHz timing)
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg [7:0] mask [0:1280*800-1];
    reg v = 0, b0 = 0, b1 = 0, first = 0, last = 0, fstart = 0, fend = 0;
    wire cand_we; wire [9:0] cand_waddr; wire [31:0] cand_wdata; wire done; wire [7:0] cand_count; wire [3:0] flags;
    wire [15:0] max_row_cycles;
    reg [23:0] min_area = 100, max_area = 400000; reg [7:0] min_dim = 10; reg rej = 1;
`ifndef P_NLAB
`define P_NLAB 1024
`define P_LB 10
`endif
    run_ccl #(.NLAB(`P_NLAB), .LB(`P_LB)) dut(.clk(clk), .rst(rst), .cfg_min_area(min_area), .cfg_max_area(max_area), .cfg_min_dim(min_dim),
        .cfg_reject_border(rej), .v(v), .b0(b0), .b1(b1), .first(first), .last(last), .fstart(fstart), .fend(fend),
        .cand_we(cand_we), .cand_waddr(cand_waddr), .cand_wdata(cand_wdata), .done(done), .cand_count(cand_count),
        .flags(flags), .max_row_cycles(max_row_cycles));
    reg [31:0] cram [0:1023];
    always @(posedge clk) if (cand_we) cram[cand_waddr] <= cand_wdata;
    integer cyc = 0, fend_cycle = 0, done_cycle = 0, done_cnt = 0;
    always @(posedge clk) begin cyc <= cyc + 1; if (done) begin done_cnt <= done_cnt + 1; done_cycle <= cyc; end end
    reg [1023:0] maskf, outf;
    integer fd, n, y, c, i;

    task send_frame;
        begin
            fstart <= 1; @(posedge clk); fstart <= 0; repeat (10) @(posedge clk);
            for (y = 0; y < 800; y = y + 1) begin
                for (c = 0; c < 640; c = c + 1) begin
                    v <= 1; b0 <= mask[y*1280 + 2*c] != 0; b1 <= mask[y*1280 + 2*c + 1] != 0;
                    first <= (c == 0); last <= (c == 639);
                    if (y == 799 && c == 639) begin fend <= 1; fend_cycle = cyc; end else fend <= 0;
                    @(posedge clk);
                end
                v <= 0; last <= 0; first <= 0; fend <= 0;
                repeat (line_n - 640) @(posedge clk);
            end
            repeat (40000) @(posedge clk);
        end
    endtask
    task dump; input [1023:0] f;
        begin
            fd = $fopen(f, "w");
            $fdisplay(fd, "%0d", cand_count);
            for (i = 0; i < cand_count * 16; i = i + 1) $fdisplay(fd, "%08x", cram[i]);
            $fclose(fd);
            $display("RESULT done=%0d count=%0d flags=%b max_row_cycles=%0d done_latency=%0d rows_dropped=%0d labels_used=%0d", done_cnt, cand_count, flags, max_row_cycles, done_cycle - fend_cycle, dut.rows_dropped, dut.nlab);
        end
    endtask
    initial begin
        if (!$value$plusargs("mask=%s", maskf)) begin $display("need +mask"); $finish; end
        if (!$value$plusargs("out=%s", outf)) begin $display("need +out"); $finish; end
        if ($value$plusargs("line=%d", n)) line_n = n;
        if ($value$plusargs("minarea=%d", n)) min_area = n;
        if ($value$plusargs("mindim=%d", n)) min_dim = n;
        if ($value$plusargs("maxarea=%d", n)) max_area = n;
        if ($value$plusargs("rej=%d", n)) rej = n;
        for (i = 0; i < 1024; i = i + 1) cram[i] = 0;
        repeat (20) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        fd = $fopen(maskf, "rb"); n = $fread(mask, fd); $fclose(fd);
        send_frame; dump(outf);
        if ($value$plusargs("mask2=%s", maskf)) begin
            if (!$value$plusargs("out2=%s", outf)) outf = "sim/out2.txt";
            fd = $fopen(maskf, "rb"); n = $fread(mask, fd); $fclose(fd);
            send_frame; dump(outf);
        end
        $finish;
    end
endmodule
