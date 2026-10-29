// One MIPI D-PHY HS data lane after the ECP5 IDDRX2F 4:1 gearbox (clocked by sclk = lane_rate/4 = 200 MHz).
// q = {Q3,Q2,Q1,Q0} per sclk, Q0 is the earliest bit.  D-PHY sends LSB first, so a byte is 8 consecutive bits with the
// first bit in bit 0.  Bytes are assembled on a free-running 2-sclk grid; the lane hunts for the SoT sync byte 0xB8
// preceded by three 0x00 bytes (HS-ZERO, >= 24 bits so noise cannot fake it) at any of the 8 bit alignments, then emits aligned payload bytes (one per grid
// edge, i.e. per 2 sclk) until `unlock` (from the CSI-2 packet layer).
//
// Window arithmetic: at a grid edge N = {q, n1} is the newest complete grid byte and v = {b0..b4} the five before.
// A sync byte found in v at slip k occupies v[24+k +: 8] (zeros in v[k +: 24]); the first payload byte therefore
// starts at bit 32+k of ext = {N, v} and every later payload byte at the same offset of the then-current ext.
`timescale 1ns/1ps
module dphy_lane (
    input  wire       sclk,
    input  wire       rst,
    input  wire [3:0] q,
    input  wire       unlock,         // sclk domain, already synchronised
    output reg        byte_valid = 0, // one pulse every second sclk while locked
    output reg  [7:0] byte_data = 0,
    output reg        locked = 0
);
    reg [3:0] n1 = 0;
    reg       ph = 0;
    reg [2:0] slip = 0;
    reg [7:0] b0 = 8'hFF, b1 = 8'hFF, b2 = 8'hFF, b3 = 8'hFF, b4 = 8'hFF;
    wire [39:0] v   = {b0, b1, b2, b3, b4};
    wire [7:0]  nb  = {q, n1};
    wire [47:0] ext = {nb, v};
    // The window v only changes at grid edges (every 2nd sclk), so the 8 sync comparisons are registered in the
    // intermediate cycle (hit_q) and only the small priority encode sits in the grid-edge path.
    reg  [7:0] hv;
    reg  [7:0] hit_q = 0;
    integer k;
    always @* for (k = 0; k < 8; k = k + 1)
        hv[k] = (v[24 + k +: 8] == 8'hB8) && (v[k +: 24] == 24'h000000);
    always @(posedge sclk) hit_q <= hv;
    reg        sync_hit;
    reg [2:0]  sync_slip;
    always @* begin
        sync_hit = |hit_q; sync_slip = 0;
        for (k = 7; k >= 0; k = k - 1) if (hit_q[k]) sync_slip = k[2:0];
    end

    // one-hot byte select (at most one slip can match: a sync byte preceded by zeros cannot match at two shifts):
    // an AND-OR of the 8 candidate bytes is two LUT levels shallower than encode + variable shift.
    reg [7:0] slip_oh = 8'd1;
    function [7:0] sel_oh; input [47:0] e; input [7:0] oh;
        integer q;
        begin
            sel_oh = 8'd0;
            for (q = 0; q < 8; q = q + 1) sel_oh = sel_oh | (e[32 + q +: 8] & {8{oh[q]}});
        end
    endfunction
    always @(posedge sclk) begin
        byte_valid <= 0;
        if (rst) begin
            ph <= 0; locked <= 0; slip <= 0; b0 <= 8'hFF; b1 <= 8'hFF; b2 <= 8'hFF; b3 <= 8'hFF; b4 <= 8'hFF; n1 <= 0; byte_data <= 0;
        end else begin
            n1 <= q;
            ph <= ~ph;
            if (ph) begin
                b0 <= nb; b1 <= b0; b2 <= b1; b3 <= b2; b4 <= b3;
                if (unlock) begin
                    locked <= 0; b0 <= 8'hFF; b1 <= 8'hFF; b2 <= 8'hFF; b3 <= 8'hFF; b4 <= 8'hFF;
                end else if (!locked) begin
                    if (sync_hit) begin
                        locked <= 1; slip_oh <= hit_q; byte_valid <= 1;
                        byte_data <= sel_oh(ext, hit_q);
                    end
                end else begin
                    byte_valid <= 1;
                    byte_data <= sel_oh(ext, slip_oh);
                end
            end
        end
    end
endmodule
