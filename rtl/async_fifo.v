// Small dual-clock FIFO (gray-coded pointers).  Write side: wclk/wen/wdata, read side: rclk/ren/rdata (registered).
// `rfill` is the read-side view of the fill level (conservative: write pointer is synchronised, so it can lag).
`timescale 1ns/1ps
module async_fifo #(
    parameter W = 8,
    parameter AW = 4
) (
    input  wire         wclk,
    input  wire         wrst,
    input  wire         wen,
    input  wire [W-1:0] wdata,
    output wire         wfull,
    input  wire         rclk,
    input  wire         rrst,
    input  wire         ren,
    input  wire         rflush,           // discard everything written so far (read pointer jumps to the synchronised write pointer)
    output reg  [W-1:0] rdata,
    output wire         rempty,
    output wire [AW:0]  rfill
);
    reg [W-1:0] mem [0:(1<<AW)-1];
    reg [AW:0] wbin = 0, wgray = 0, rbin = 0, rgray = 0;
    reg [AW:0] wg_r1 = 0, wg_r2 = 0, rg_w1 = 0, rg_w2 = 0;

    wire [AW:0] wbin_n  = wbin + ((wen && !wfull) ? 1 : 0);
    wire [AW:0] wgray_n = (wbin_n >> 1) ^ wbin_n;
    always @(posedge wclk) begin
        if (wrst) begin wbin <= 0; wgray <= 0; end
        else begin
            if (wen && !wfull) mem[wbin[AW-1:0]] <= wdata;
            wbin <= wbin_n; wgray <= wgray_n;
        end
        rg_w1 <= rgray; rg_w2 <= rg_w1;
    end
    // gray -> binary of the synchronised read pointer (write side) for the full flag
    function [AW:0] g2b; input [AW:0] g; integer i; begin g2b[AW] = g[AW]; for (i = AW-1; i >= 0; i = i - 1) g2b[i] = g2b[i+1] ^ g[i]; end endfunction
    reg  [AW:0] rbin_w = 0;                         // synchronised read pointer in binary (registered conversion)
    always @(posedge wclk) rbin_w <= g2b(rg_w2);
    wire [AW:0] wdiff = wbin - rbin_w;               // modulo-2^(AW+1) fill level
    reg  wfull_r = 0;
    always @(posedge wclk) wfull_r <= (wdiff[AW] || wdiff[AW-1:0] >= (1 << AW) - 2);   // asserted 2 entries early (registered)
    assign wfull = wfull_r;

    reg  [AW:0] wbin_r = 0;
    always @(posedge rclk) wbin_r <= g2b(wg_r2);
    wire [AW:0] rbin_n = rbin + ((ren && !rempty) ? 1 : 0);
    assign rempty = (wbin_r == rbin);
    wire [AW:0] rdiff = wbin_r - rbin;
    assign rfill  = rdiff;
    always @(posedge rclk) begin
        if (rrst) begin rbin <= 0; rgray <= 0; end
        else if (rflush) begin rbin <= wbin_r; rgray <= (wbin_r >> 1) ^ wbin_r; end
        else begin
            if (ren && !rempty) rdata <= mem[rbin[AW-1:0]];
            rbin <= rbin_n; rgray <= (rbin_n >> 1) ^ rbin_n;
        end
        wg_r1 <= wgray; wg_r2 <= wg_r1;
    end
endmodule
