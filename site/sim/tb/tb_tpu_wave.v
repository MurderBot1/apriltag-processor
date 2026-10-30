// Waveform scenario: the TPU runs its baked program on one tag candidate.  Stimulus as tb/tb_tpu.v
// (+cand=, +fb=, +n=); windows dumped: start-up, first TAGMATCH, and the result write-back.
`timescale 1ns/1ps
module tb;
    parameter PROG = "rtl/tpu_prog.hex";
    reg clk = 0, rst = 1, start = 0;
    always #5 clk = ~clk;
    wire busy, done, res_we; wire [8:0] res_waddr; wire [31:0] res_wdata, cycle_count;
    wire [9:0] cand_raddr; wire [15:0] fb_addr;
    reg [31:0] cand [0:1023];
    reg [31:0] fb [0:31999];
    reg [31:0] res [0:511];
    reg [31:0] cand_rdata = 0, fb_data = 0;
    reg [7:0] ncand = 1; reg [31:0] frame_id = 1;
    always @(posedge clk) begin cand_rdata <= cand[cand_raddr]; fb_data <= fb[fb_addr]; end
    always @(posedge clk) if (res_we) res[res_waddr] <= res_wdata;
    tpu_core #(.PROG_HEX(PROG)) dut(.clk(clk), .rst(rst), .start(start), .busy(busy), .done(done), .cfg_frame_id(frame_id),
        .cfg_maxham(6'd2), .cand_count(ncand), .cfg_minside(8'd8), .cand_raddr(cand_raddr), .cand_rdata(cand_rdata),
        .res_we(res_we), .res_waddr(res_waddr), .res_wdata(res_wdata), .fb_addr(fb_addr), .fb_data(fb_data),
        .cycle_count(cycle_count));
    // ---- signals shown in the viewer
    wire [15:0] pc = dut.pc;
    wire [4:0]  fsm_state = dut.st;
    wire [31:0] instr = dut.ir;
    wire [5:0]  opcode = dut.op;
    wire signed [31:0] operand_A = dut.opA, operand_B = dut.opB;
    wire [31:0] r1 = dut.rf[1], r2 = dut.rf[2], r3 = dut.rf[3], r4 = dut.rf[4], r5 = dut.rf[5], r6 = dut.rf[6];
    wire [31:0] r20 = dut.rf[20], r21 = dut.rf[21], r22 = dut.rf[22], r23 = dut.rf[23];
    wire [9:0] cand_read_addr = cand_raddr; wire [31:0] cand_read_data = cand_rdata;
    wire [15:0] frame_word_addr = fb_addr; wire [31:0] frame_word = fb_data;
    wire result_we = res_we; wire [8:0] result_addr = res_waddr; wire [31:0] result_data = res_wdata;
    wire tpu_busy = busy, tpu_done = done, tpu_start = start;
    wire [31:0] clocks = cycle_count;
    reg [1023:0] f; integer fd, n, i, cyc = 0, tm_cyc = -100000, last_we = -100000;
    reg tm_seen = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc == 0) $dumpon;
        if (cyc == 900) $dumpoff;
        if (!tm_seen && dut.st == 5'd7) begin tm_seen = 1; tm_cyc = cyc; $dumpon; end
        if (tm_seen && cyc == tm_cyc + 600) $dumpoff;
        if (res_we) begin last_we = cyc; $dumpon; end
        if (cyc == last_we + 60 && last_we > 0) $dumpoff;
    end
    initial begin
        if (!$value$plusargs("vcd=%s", f)) $finish;
        $dumpfile(f); $dumpvars(1, tb); $dumpoff;
        for (i = 0; i < 512; i = i + 1) res[i] = 0;
        if (!$value$plusargs("cand=%s", f)) $finish; $readmemh(f, cand);
        if (!$value$plusargs("fb=%s", f)) $finish; $readmemh(f, fb);
        if ($value$plusargs("n=%d", n)) ncand = n;
        if ($value$plusargs("frame=%d", n)) frame_id = n;
        repeat (10) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        start <= 1; @(posedge clk); start <= 0;
        wait (done); repeat (80) @(posedge clk);
        fd = $fopen("tpu_res.txt", "w");
        for (i = 0; i < 512; i = i + 1) $fdisplay(fd, "%08x", res[i]);
        $fclose(fd);
        $display("RESULT cycles=%0d", cycle_count);
        $finish;
    end
    initial begin #2000000000; $display("TIMEOUT"); $finish; end
endmodule
