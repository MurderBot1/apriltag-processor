// Runs the TPU RTL on candidate records (+cand=hex 1024 words) and a packed binary frame (+fb=hex 32000 words),
// dumps the 512-word result RAM (+out=file) and cycle count.  Compared bit-exactly with tools/tpu_isa.py.
`timescale 1ns/1ps
module tb_tpu;
    reg clk = 0, rst = 1, start = 0;
    always #5 clk = ~clk;
    wire busy, done, res_we; wire [8:0] res_waddr; wire [31:0] res_wdata, cycle_count;
    wire [9:0] cand_raddr; wire [15:0] fb_addr;
    reg [31:0] cand [0:1023];
    reg [31:0] fb [0:31999];
    reg [31:0] res [0:511];
    reg [31:0] cand_rdata = 0, fb_data = 0;
    reg [7:0] ncand = 0; reg [31:0] frame_id = 1;
    always @(posedge clk) begin cand_rdata <= cand[cand_raddr]; fb_data <= fb[fb_addr]; end
    always @(posedge clk) if (res_we) res[res_waddr] <= res_wdata;
    tpu_core dut(.clk(clk), .rst(rst), .start(start), .busy(busy), .done(done), .cfg_frame_id(frame_id),
        .cfg_maxham(6'd2), .cand_count(ncand), .cfg_minside(8'd8), .cand_raddr(cand_raddr), .cand_rdata(cand_rdata),
        .res_we(res_we), .res_waddr(res_waddr), .res_wdata(res_wdata), .fb_addr(fb_addr), .fb_data(fb_data),
        .cycle_count(cycle_count));
    reg [1023:0] f; integer fd, n, i;
    initial begin
        for (i = 0; i < 512; i = i + 1) res[i] = 0;
        if (!$value$plusargs("cand=%s", f)) $finish; $readmemh(f, cand);
        if (!$value$plusargs("fb=%s", f)) $finish; $readmemh(f, fb);
        if ($value$plusargs("n=%d", n)) ncand = n;
        if ($value$plusargs("frame=%d", n)) frame_id = n;
        repeat (10) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        start <= 1; @(posedge clk); start <= 0;
        wait (done); repeat (5) @(posedge clk);
        if (!$value$plusargs("out=%s", f)) $finish;
        fd = $fopen(f, "w");
        for (i = 0; i < 512; i = i + 1) $fdisplay(fd, "%08x", res[i]);
        $fclose(fd);
        $display("RESULT cycles=%0d", cycle_count);
        $finish;
    end
    initial begin #2000000000; $display("TIMEOUT"); $finish; end
endmodule
