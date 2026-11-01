// Adaptive threshold + binarizer, 2 pixels / clock, bit-exact with tools/golden.py:binarize().
//   2x2 binning -> 8x8-pixel tiles (min,max) -> 3x3 tile neighbourhood -> thr=(min+max)/2
//   tile is "contrasty" if diff>=diff_min and k*diff>=max (k = 2,3,4 or no test, cfg_ratio = 0..3, reset 0) ; contrasty: black = p<=thr, else black = p<abs_black
//   (k=2 means min <= max/2: a frame whose contrast is compressed so that min > max/2, e.g. black 69 / white 167, has no contrasty tile at all; k=4 admits it)
// Pixels are delayed by D=17 rows in a 32-row ring so the tile row below is known when a row is emitted.
// Output rows are launched when input row (y+17) starts, or by an internal timer during the post-frame flush.
`timescale 1ns/1ps
module thresh_binarize #(
    parameter COLS = 640,          // beats per row (2 px each)
    parameter ROWS = 800,
    parameter LINE_CYC = 900       // default flush pacing (overridden by cfg_line_cyc)
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  cfg_diff_min,
    input  wire [7:0]  cfg_abs_black,
    input  wire [1:0]  cfg_ratio,      // contrast-ratio test: 0 = 2*diff>=max, 1 = 3*diff>=max, 2 = 4*diff>=max, 3 = off (diff_min only)
    input  wire [15:0] cfg_line_cyc,   // clocks per sensor line (flush pacing)
    // video in (from csi2_rx)
    input  wire        vin_valid,
    input  wire [7:0]  vin_p0,
    input  wire [7:0]  vin_p1,
    input  wire        vin_fs,
    input  wire        vin_fe,
    // binary video out, same 2 px/beat format, rows paced like the input
    output reg         o_valid,
    output reg         o_b0,
    output reg         o_b1,
    output reg         o_first,
    output reg         o_last,
    output reg  [9:0]  o_y,
    output reg         o_frame_start,    // pulses with first beat of row 0
    output reg         o_frame_end,      // pulses after last beat of last row
    output reg         o_busy_err        // sticky: output launched while previous row still active
);
    localparam D = 17;
    localparam TILES = COLS / 4;       // 160
    localparam TROWS = ROWS / 8;       // 100

    // ------------------------------------------------------------ memories
    reg [15:0] ring   [0:32*COLS-1];   // {p1,p0}, linear address row*COLS+col (no wasted depth)
    reg [9:0]  hsprev [0:COLS-1];
    reg [15:0] acc    [0:TILES-1];     // {min,max} running over binned rows of a tile row
    reg [15:0] tmm0 [0:TILES-1];
    reg [15:0] tmm1 [0:TILES-1];
    reg [15:0] tmm2 [0:TILES-1];
    reg [15:0] tmm3 [0:TILES-1];
    reg [8:0]  thr  [0:511];     // {hi, thr}

    // ------------------------------------------------------------ input stage s0
    reg [9:0] in_row, in_col;
    reg       in_frame;
    wire [9:0] in_col_n = in_col;
    reg       s1_v;
    reg [9:0] s1_row, s1_col;
    reg [9:0] s1_hs;
    reg [9:0] hp_q;
    reg [15:0] ring_wdata;

    wire [9:0] hs0 = {2'b0, vin_p0} + {2'b0, vin_p1};

    always @(posedge clk) begin
        hp_q <= hsprev[in_col];
        if (vin_valid && in_frame) begin
            ring[in_row[4:0] * COLS + in_col] <= {vin_p1, vin_p0};
            if (!in_row[0]) hsprev[in_col] <= hs0;
        end
    end

    // line_last: derived from column counter reaching COLS-1
    wire last_col = (in_col == COLS - 1);
    wire first_col = (in_col == 0);

    always @(posedge clk) begin
        if (rst) begin
            in_row <= 0; in_col <= 0; in_frame <= 0; s1_v <= 0;
        end else begin
            s1_v <= 0;
            if (vin_fs) begin in_row <= 0; in_col <= 0; in_frame <= 1; end
            if (vin_fe) in_frame <= 0;
            if (vin_valid && in_frame) begin
                s1_v <= 1; s1_row <= in_row; s1_col <= in_col; s1_hs <= hs0;
                if (last_col) begin in_col <= 0; in_row <= in_row + 1; end
                else in_col <= in_col + 1;
            end
        end
    end

    // ------------------------------------------------------------ binned tile statistics
    // s1: 2x2 binning (add) -> register ; s2: running min/max, tile accumulate (the compares are off the BRAM-output path)
    wire        s1_odd  = s1_row[0];
    wire [9:0]  vsum    = s1_hs + hp_q + 10'd2;
    wire [7:0]  bval    = vsum[9:2];
    reg         s2_v; reg [9:0] s2_row, s2_col; reg [7:0] s2_b;
    always @(posedge clk) begin s2_v <= s1_v; s2_row <= s1_row; s2_col <= s1_col; s2_b <= bval; end
    wire        s2_odd  = s2_row[0];
    wire [7:0]  tx      = s2_col[9:2];
    wire [6:0]  ty_in   = s2_row[9:3];
    wire [1:0]  brow    = s2_row[2:1];          // binned row inside the tile row
    reg  [7:0]  seg_min, seg_max;
    reg  [15:0] acc_q;
    reg  [7:0]  tiles_done;

    wire [7:0] segmin_n = (s2_col[1:0] == 2'd0) ? s2_b : ((s2_b < seg_min) ? s2_b : seg_min);
    wire [7:0] segmax_n = (s2_col[1:0] == 2'd0) ? s2_b : ((s2_b > seg_max) ? s2_b : seg_max);
    wire [7:0] acc_min  = acc_q[15:8], acc_max = acc_q[7:0];
    wire [7:0] fin_min  = (brow == 2'd0) ? segmin_n : ((acc_min < segmin_n) ? acc_min : segmin_n);
    wire [7:0] fin_max  = (brow == 2'd0) ? segmax_n : ((acc_max > segmax_n) ? acc_max : segmax_n);

    // running tile value is fetched early (s1, first beat of a 4-beat tile segment) and held in acc_q
    always @(posedge clk) if (s1_v && s1_odd && s1_col[1:0] == 2'd0) acc_q <= acc[s1_col[9:2]];

    reg [15:0] fin_r; reg fin_v, fin_last; reg [7:0] fin_tx; reg [1:0] fin_ty; reg fin_final; reg [6:0] fin_tyfull;
    always @(posedge clk) begin
        fin_v <= 0;
        if (s2_v && s2_odd) begin
            seg_min <= segmin_n; seg_max <= segmax_n;
            if (s2_col[1:0] == 2'd3) begin
                fin_v <= 1; fin_r <= {fin_min, fin_max}; fin_tx <= tx; fin_final <= (brow == 2'd3); fin_ty <= ty_in[1:0];
                fin_last <= (s2_col == COLS - 1); fin_tyfull <= ty_in;
            end
        end
    end
    // tile-row memories are written one cycle later from registered data
    always @(posedge clk) begin
        if (fin_v) begin
            acc[fin_tx] <= fin_r;
            if (fin_final) begin
                case (fin_ty)
                    2'd0: tmm0[fin_tx] <= fin_r;
                    2'd1: tmm1[fin_tx] <= fin_r;
                    2'd2: tmm2[fin_tx] <= fin_r;
                    default: tmm3[fin_tx] <= fin_r;
                endcase
            end
        end
    end

    always @(posedge clk) begin
        if (rst || vin_fs) tiles_done <= 0;
        else if (fin_v && fin_final && fin_last) tiles_done <= fin_tyfull + 1;
    end

    // ------------------------------------------------------------ threshold computation FSM
    // tile row `cur_row` needs tile rows cur_row-1..cur_row+1.  Timeline relative to tc:
    //   tc=c      : read address c issued
    //   tc=c+1    : r* valid; column summary registered (cm_*)
    //   tc=c+2    : cm_* shifted into the 3-column window
    //   tc=c+3    : window = {c-2,c-1,c}; min/max registered (n_*) for centre tx=c-1
    //   tc=c+4    : thr word computed and written, i.e. when tc == tx+5
    reg [6:0]  thr_row;            // next tile row to compute
    reg        fe_seen;
    reg        tf;
    reg [8:0]  tc;
    reg [15:0] r0, r1, r2, r3;
    reg [7:0]  cmin0, cmin1, cmin2, cmax0, cmax1, cmax2;
    reg [2:0]  cval;
    reg [6:0]  cur_row;

    function [15:0] pick; input [1:0] s; input [15:0] a, b, c, d;
        begin case (s) 2'd0: pick = a; 2'd1: pick = b; 2'd2: pick = c; default: pick = d; endcase end
    endfunction

    wire [6:0]  row_m1 = cur_row - 7'd1, row_p1 = cur_row + 7'd1;
    wire        v_m1 = (cur_row != 0), v_p1 = (cur_row != TROWS - 1);
    wire [15:0] tm_c = pick(row_m1[1:0], r0, r1, r2, r3);
    wire [15:0] t0_c = pick(cur_row[1:0], r0, r1, r2, r3);
    wire [15:0] tp_c = pick(row_p1[1:0], r0, r1, r2, r3);
    reg  [15:0] tm, t0, tp;                       // registered picks (pipeline stage before the min/max)
    always @(posedge clk) begin tm <= tm_c; t0 <= t0_c; tp <= tp_c; end
    reg  [7:0]  colmin, colmax;
    always @* begin
        colmin = t0[15:8]; colmax = t0[7:0];
        if (v_m1) begin if (tm[15:8] < colmin) colmin = tm[15:8]; if (tm[7:0] > colmax) colmax = tm[7:0]; end
        if (v_p1) begin if (tp[15:8] < colmin) colmin = tp[15:8]; if (tp[7:0] > colmax) colmax = tp[7:0]; end
    end

    reg [7:0] nmin, nmax;
    reg [7:0] cm_min, cm_max;       // column summary register (pipeline stage)
    reg [7:0] n_min, n_max;         // window min/max register (pipeline stage)
    always @* begin
        nmin = 8'hFF; nmax = 8'h00;
        if (cval[0]) begin if (cmin0 < nmin) nmin = cmin0; if (cmax0 > nmax) nmax = cmax0; end
        if (cval[1]) begin if (cmin1 < nmin) nmin = cmin1; if (cmax1 > nmax) nmax = cmax1; end
        if (cval[2]) begin if (cmin2 < nmin) nmin = cmin2; if (cmax2 > nmax) nmax = cmax2; end
    end
    wire [8:0] ndiff = {1'b0, n_max} - {1'b0, n_min};
    wire [10:0] ndiff_k = (cfg_ratio == 2'd0) ? {1'b0, ndiff, 1'b0} : (cfg_ratio == 2'd1) ? ({1'b0, ndiff, 1'b0} + {2'b0, ndiff}) : {ndiff, 2'b00};
    wire       hi    = (ndiff >= {1'b0, cfg_diff_min}) && ((cfg_ratio == 2'd3) || (ndiff_k >= {3'b0, n_max}));
    wire [8:0] nsum  = {1'b0, n_min} + {1'b0, n_max};
    wire [7:0] thr_v = nsum[8:1];

    wire [8:0] rd_addr = (tc < TILES) ? tc : 9'd0;
    // thr is double-buffered by tile-row parity: tile row r+2 may only overwrite the buffer once tile row r has been read out
    // completely.  In the normal flow the 17-row output delay guarantees this; in the post-frame flush the last tile row would
    // otherwise start while the last row of tile row r-2 is still being emitted.
    reg [6:0]  out_tdone;              // tile rows whose last pixel row has been fully read
    wire       rd_ok = (thr_row < 7'd2) || (out_tdone + 7'd1 >= thr_row);
    wire can_start = ((thr_row + 7'd1 < tiles_done) || (fe_seen && thr_row < tiles_done)) && rd_ok;

    always @(posedge clk) begin
        r0 <= tmm0[rd_addr[7:0]]; r1 <= tmm1[rd_addr[7:0]]; r2 <= tmm2[rd_addr[7:0]]; r3 <= tmm3[rd_addr[7:0]];
        cm_min <= colmin; cm_max <= colmax;
        n_min <= nmin; n_max <= nmax;
        if (tf && tc >= 9'd6 && tc <= TILES + 5) thr[{cur_row[0], tc[7:0] - 8'd6}] <= {hi, thr_v};
    end

    always @(posedge clk) begin
        if (rst || vin_fs) begin
            tf <= 0; thr_row <= 0; fe_seen <= 0; tc <= 0; cval <= 0;
        end else begin
            if (vin_fe) fe_seen <= 1;
            if (!tf) begin
                if (can_start) begin tf <= 1; tc <= 0; cur_row <= thr_row; cval <= 0; end
            end else begin
                tc <= tc + 1;
                if (tc >= 9'd3 && tc <= TILES + 3) begin
                    cmin0 <= cmin1; cmax0 <= cmax1; cmin1 <= cmin2; cmax1 <= cmax2;
                    cmin2 <= cm_min; cmax2 <= cm_max;
                    cval <= {(tc <= TILES + 2), cval[2], cval[1]};
                end
                if (tc == TILES + 5) begin tf <= 0; thr_row <= thr_row + 7'd1; end
            end
        end
    end

    // ------------------------------------------------------------ output row sequencer
    wire trig_in = vin_valid && in_frame && first_col && (in_row >= D);
    reg        fl_active;
    reg [4:0]  fl_cnt;
    reg [15:0] fl_timer;
    wire       trig_fl = fl_active && (fl_timer == 0);

    reg        oact;
    reg [9:0]  oy, ob;
    reg [14:0] raddr;                  // running ring read address (row*COLS + beat), no multiplier in front of the RAM
    reg        p1_v, p1_first, p1_last; reg [9:0] p1_y;
    reg [15:0] ring_q; reg [8:0] thr_q;
    reg        p2_v, p2_first, p2_last; reg [9:0] p2_y; reg [15:0] ring_q2; reg [8:0] thr_q2;

    always @(posedge clk) begin
        if (rst) begin
            fl_active <= 0; fl_cnt <= 0; fl_timer <= 0;
        end else begin
            if (vin_fs) fl_active <= 0;
            if (vin_fe && in_frame) begin fl_active <= 1; fl_cnt <= 0; fl_timer <= 4; end
            else if (fl_active) begin
                if (fl_timer == 0) begin
                    fl_timer <= cfg_line_cyc - 16'd1;
                    if (fl_cnt == D - 1) fl_active <= 0; else fl_cnt <= fl_cnt + 1;
                end else fl_timer <= fl_timer - 1;
            end
        end
    end

    wire        launch  = trig_in || trig_fl;
    wire [9:0]  launch_y = trig_in ? (in_row - D) : (ROWS - D + {5'd0, fl_cnt});

    always @(posedge clk) begin
        if (rst || vin_fs) out_tdone <= 0;
        else if (oact && !launch && ob == COLS - 1 && oy[2:0] == 3'd7) out_tdone <= out_tdone + 7'd1;
    end


    always @(posedge clk) begin
        ring_q <= ring[raddr];
        thr_q  <= thr[{oy[3], ob[9:2]}];
    end

    always @(posedge clk) begin
        if (rst) begin
            oact <= 0; oy <= 0; ob <= 0; p1_v <= 0; o_valid <= 0; o_first <= 0; o_last <= 0;
            o_frame_start <= 0; o_frame_end <= 0; o_busy_err <= 0; o_b0 <= 0; o_b1 <= 0; o_y <= 0;
        end else begin
            p1_v <= 0; p2_v <= 0; o_valid <= 0; o_frame_start <= 0; o_frame_end <= 0; o_first <= 0; o_last <= 0;
            if (launch) begin
                if (launch_y == 0) o_frame_start <= 1;      // asserted ~3 clocks before the first beat of row 0
                if (oact) o_busy_err <= 1;
                oact <= 1; oy <= launch_y; ob <= 0; raddr <= launch_y[4:0] * COLS;
            end else if (oact) begin
                if (ob == COLS - 1) oact <= 0; else begin ob <= ob + 1; raddr <= raddr + 1; end
            end
            if (oact && !launch) begin
                p1_v <= 1; p1_first <= (ob == 0); p1_last <= (ob == COLS - 1); p1_y <= oy;
            end
            // stage 2: register the block-RAM outputs; stage 3: compare
            p2_v <= p1_v; p2_first <= p1_first; p2_last <= p1_last; p2_y <= p1_y; ring_q2 <= ring_q; thr_q2 <= thr_q;
            if (p2_v) begin
                o_valid <= 1; o_first <= p2_first; o_last <= p2_last; o_y <= p2_y;
                o_b0 <= thr_q2[8] ? (ring_q2[7:0]  <= thr_q2[7:0]) : (ring_q2[7:0]  < cfg_abs_black);
                o_b1 <= thr_q2[8] ? (ring_q2[15:8] <= thr_q2[7:0]) : (ring_q2[15:8] < cfg_abs_black);
                o_frame_end   <= p2_last && (p2_y == ROWS - 1);
            end
        end
    end
endmodule
