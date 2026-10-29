// 3x3 binary majority filter on the 2-pixel/beat stream:  out = (set pixels in the 3x3 window incl. centre) >= 4,
// zero padding outside the frame.  Bit-exact with tools/golden.py:despeckle().
// Row r is produced while row r+1 streams in (rows A=r-1, B=r in two 2-bit-wide buffers, C = incoming).  Every row
// gets one extra "tail" cycle (zero column) for its right edge, and a virtual all-zero row after the last real row
// produces the final output row.  Input rows must be separated by at least 2 idle clocks.
`timescale 1ns/1ps
module despeckle #(
    parameter COLS = 640,
    parameter ROWS = 800
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        bypass,          // pass the stream through unchanged (zero latency); change only between frames
    input  wire        i_valid,
    input  wire        i_b0,
    input  wire        i_b1,
    input  wire        i_fs,            // frame start
    output reg         o_valid,
    output reg         o_b0,
    output reg         o_b1,
    output reg         o_first,
    output reg         o_last,
    output reg  [9:0]  o_y,
    output reg         o_fs,
    output reg         o_fe
);
    reg [1:0] bufA [0:COLS-1];           // row r-1
    reg [1:0] bufB [0:COLS-1];           // row r
    reg [9:0] col, in_row;               // incoming beat / row
    reg       running;
    reg       tail_pend;                 // run one tail step next cycle
    reg       flushing;                  // streaming the virtual zero row
    reg [9:0] fcol;
    reg [1:0] pa2, pa1, pb2, pb1, pc2, pc1;   // beats c-2, c-1 of rows A, B, C
    reg       have_prev;                 // a beat c-1 exists in the current row
    reg [9:0] cur_row;                   // index of the row being incoming (virtual row = ROWS)

    wire real_beat = i_valid & running & ~flushing & ~tail_pend;
    wire flush_beat = flushing;
    wire step = real_beat | flush_beat | tail_pend;

    wire [9:0] c = flushing ? fcol : col;
    reg  [1:0] ra, rb, nc;               // column data for beat c: row A, row B, row C(new)
    always @* begin
        ra = 2'b00; rb = 2'b00; nc = 2'b00;
        if (!tail_pend) begin
            ra = bufA[c]; rb = bufB[c]; nc = flushing ? 2'b00 : {i_b1, i_b0};
        end
    end
    // beat c data feeding the window: (A,B,C) = (rb, new-from-buffer ...) -> rows are r-1, r, r+1:
    //   row r-1 column = bufB-old?  We keep: bufA holds r-1, bufB holds r, incoming is r+1.
    wire [1:0] a_n = ra;                 // row r-1 beat c
    wire [1:0] b_n = rb;                 // row r   beat c
    wire [1:0] c_n = nc;                 // row r+1 beat c
    // left edge: beat -1 is zero (pX2 forced to 0 at c==1 by the load rule below); first output row also masks row -1
    wire mask_a = (cur_row == 10'd1) | (cur_row == 10'd0);   // row -1 does not exist when producing output row 0
    wire [1:0] pa1_m = mask_a ? 2'b00 : pa1;
    wire [1:0] a_nm = mask_a ? 2'b00 : a_n;
    wire [1:0] pa2_mm = mask_a ? 2'b00 : pa2;
    // sums for the pair at beat c-1 (pixel x=2(c-1) and 2(c-1)+1)
    wire [3:0] s0 = (pa2_mm[1] + pa1_m[0] + pa1_m[1]) + (pb2[1] + pb1[0] + pb1[1]) + (pc2[1] + pc1[0] + pc1[1]);
    wire [3:0] s1 = (pa1_m[0] + pa1_m[1] + a_nm[0])   + (pb1[0] + pb1[1] + b_n[0])  + (pc1[0] + pc1[1] + c_n[0]);
    wire out_enable = have_prev & (cur_row >= 10'd1);

    always @(posedge clk) begin
        o_valid <= 0; o_first <= 0; o_last <= 0; o_fs <= 0; o_fe <= 0;
        if (rst) begin
            col <= 0; in_row <= 0; running <= 0; tail_pend <= 0; flushing <= 0; fcol <= 0; have_prev <= 0; cur_row <= 0;
            o_y <= 0;
        end else if (bypass) begin
            o_valid <= i_valid; o_b0 <= i_b0; o_b1 <= i_b1; o_first <= 0; o_last <= 0; o_y <= 0; o_fs <= 0; o_fe <= 0;
        end else begin
            if (i_fs) begin
                running <= 1; col <= 0; in_row <= 0; cur_row <= 0; tail_pend <= 0; flushing <= 0; fcol <= 0; have_prev <= 0;
            end
            if (step) begin
                // frame start goes out one clock before the first output beat (step c==0 of incoming row 1)
                if (c == 10'd0 && !tail_pend && !flushing && cur_row == 10'd1) o_fs <= 1;
                // output for beat c-1
                if (out_enable) begin
                    o_valid <= 1; o_b0 <= (s0 >= 4); o_b1 <= (s1 >= 4);
                    o_first <= (c == 10'd1) && !tail_pend;
                    o_last  <= tail_pend;
                    o_y     <= cur_row - 10'd1;
                    o_fe    <= tail_pend && (cur_row == ROWS);
                end
                if (tail_pend) begin
                    tail_pend <= 0; have_prev <= 0;
                    if (cur_row == ROWS) begin flushing <= 0; running <= 0; end
                    else if (cur_row == ROWS - 1) begin flushing <= 1; fcol <= 0; cur_row <= ROWS; have_prev <= 0; end
                    else cur_row <= cur_row + 1;
                end else begin
                    // window shift with the new column; beat 0 starts a fresh window (zero left neighbour)
                    if (c == 0) begin
                        pa2 <= 2'b00; pb2 <= 2'b00; pc2 <= 2'b00;
                    end else begin
                        pa2 <= pa1; pb2 <= pb1; pc2 <= pc1;
                    end
                    pa1 <= a_n; pb1 <= b_n; pc1 <= c_n;
                    have_prev <= 1'b1;
                    if (!flushing) begin bufA[c] <= rb; bufB[c] <= nc; end
                    if (c == COLS - 1) begin
                        tail_pend <= 1;
                        if (!flushing) col <= 0;
                    end else if (flushing) fcol <= fcol + 1; else col <= col + 1;
                end
            end
        end
    end
endmodule
