// Waveform scenario: connected-components labelling on a small binary frame (+mask= hex file, 1 byte/pixel).
// Based on tb/tb_ccl.v; small frame so the whole run can be dumped.
`timescale 1ns/1ps
module tb;
    parameter COLS = 32;
    parameter ROWS = 40;
    parameter LINE = 150;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg [7:0] mask [0:8191];
    reg v = 0, b0 = 0, b1 = 0, first = 0, last = 0, fstart = 0, fend = 0;
    wire cand_we; wire [9:0] cand_waddr; wire [31:0] cand_wdata; wire done; wire [7:0] cand_count; wire [3:0] flags;
    wire [15:0] max_row_cycles;
    reg [23:0] min_area = 40, max_area = 400000; reg [7:0] min_dim = 6; reg rej = 0;
    run_ccl dut(.clk(clk), .rst(rst), .cfg_min_area(min_area), .cfg_max_area(max_area), .cfg_min_dim(min_dim),
        .cfg_reject_border(rej), .v(v), .b0(b0), .b1(b1), .first(first), .last(last), .fstart(fstart), .fend(fend),
        .cand_we(cand_we), .cand_waddr(cand_waddr), .cand_wdata(cand_wdata), .done(done), .cand_count(cand_count),
        .flags(flags), .max_row_cycles(max_row_cycles));
    // ---- signals shown in the viewer
    wire in_valid = v, in_black0 = b0, in_black1 = b1, in_row_first = first, in_row_last = last, frame_start = fstart, frame_end = fend;
    wire [5:0] seq_state = dut.S;
    wire [9:0] labelling_row = dut.cur_y;
    wire [10:0] cur_run_start = dut.cs, cur_run_end = dut.ce, prev_run_start = dut.hs, prev_run_end = dut.he;
    wire [8:0] runs_in_row = dut.nc, runs_in_prev_row = dut.np, cur_run_index = dut.ci;
    wire [10:0] labels_allocated = dut.nlab;
    wire [9:0] cur_label_w = dut.L, prev_label = dut.fl, root_label = dut.rroot;
    wire stats_idle_w = dut.stats_idle;
    wire cand_write = cand_we; wire [9:0] cand_addr = cand_waddr; wire [31:0] cand_data = cand_wdata;
    wire frame_done = done; wire [7:0] cand_total = cand_count; wire [3:0] ccl_flags = flags;
    wire [15:0] worst_row_clocks = max_row_cycles;
    reg [31:0] cram [0:1023];
    always @(posedge clk) if (cand_we) cram[cand_waddr] <= cand_wdata;
    integer fd, n, y, c, i; reg [1023:0] f;
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb);
        if (!$value$plusargs("mask=%s", f)) $finish; $readmemh(f, mask);
        for (i = 0; i < 1024; i = i + 1) cram[i] = 0;
        repeat (4) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        fstart <= 1; @(posedge clk); fstart <= 0; repeat (10) @(posedge clk);
        for (y = 0; y < ROWS; y = y + 1) begin
            for (c = 0; c < COLS; c = c + 1) begin
                v <= 1; b0 <= mask[y*COLS*2 + 2*c] != 0; b1 <= mask[y*COLS*2 + 2*c + 1] != 0;
                first <= (c == 0); last <= (c == COLS-1);
                if (y == ROWS-1 && c == COLS-1) fend <= 1; else fend <= 0;
                @(posedge clk);
            end
            v <= 0; last <= 0; first <= 0; fend <= 0;
            repeat (LINE - COLS) @(posedge clk);
        end
        repeat (600) @(posedge clk);
        fd = $fopen("ccl_out.txt", "w");
        $fdisplay(fd, "%0d", cand_count);
        for (i = 0; i < cand_count * 16; i = i + 1) $fdisplay(fd, "%08x", cram[i]);
        $fclose(fd);
        $finish;
    end
endmodule
