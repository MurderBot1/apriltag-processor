// Streaming run-based connected-component labeller (4-connected, black = 1) with union-find and
// per-component statistics: area plus the 8 directional extremes (+x,-x,+y,-y,+(x+y),-(x+y),+(x-y),+(y-x)).
// Input: binary video 2 px/beat (from thresh_binarize), rows ~LINE_CYC clocks apart.
// Per row: runs are captured into a bank; during the following rows a sequencer labels them against the
// previous row's runs, merging components eagerly (stats of the absorbed root are folded into the survivor).
// At frame end the label table is scanned and tag-candidate records are written to a candidate RAM port.
//
// Record (16 words of 32 bit at cand_addr = {idx[5:0], word[3:0]}):
//   w0 = area                 w1..w8 = dir0..dir7 {aux[15:0], score[15:0]}   (score sign-extended)
//   w9 = label                w10    = x0 | x1<<16      w11 = y0 | y1<<16   (bbox)
//   aux: dirs 0,1 -> y ; dirs 2..7 -> x   (the second coordinate follows from the score)
`timescale 1ns/1ps
module run_ccl #(
    parameter MAXR  = 64,           // runs per row (power of two)
    parameter RB    = 6,
    parameter NLAB  = 1024,
    parameter LB    = 10,
    parameter MAXC  = 64
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [23:0] cfg_min_area,
    input  wire [23:0] cfg_max_area,
    input  wire [7:0]  cfg_min_dim,
    input  wire        cfg_reject_border,

    input  wire        v,
    input  wire        b0,
    input  wire        b1,
    input  wire        first,
    input  wire        last,
    input  wire        fstart,       // pulse with first beat of the frame
    input  wire        fend,         // pulse after last beat of the frame

    output reg         cand_we,
    output reg  [9:0]  cand_waddr,
    output reg  [31:0] cand_wdata,
    output reg         done,         // pulse: candidate list complete
    output reg  [7:0]  cand_count,
    output reg  [3:0]  flags,        // [0] row overrun [1] run overflow [2] label overflow [3] cand overflow
    output reg  [15:0] max_row_cycles
);
    localparam LABW = LB;
    // ------------------------------------------------------------------ run detector
    reg [10:0] runs_s_mem [0:4*MAXR-1];
    reg [10:0] runs_e_mem [0:4*MAXR-1];
    reg [LABW-1:0] runlab [0:4*MAXR-1];
    reg [RB:0] cnt [0:3];

    reg        in_run;
    reg [10:0] rstart;
    reg [9:0]  bc;
    reg [1:0]  wb;
    reg [RB:0] wcnt;
    reg        tail_cyc, tail_v;      // cycle after the last beat of a row: optional 2nd run + commit
    reg [10:0] tail_s, tail_e;
    reg [3:0]  committed, processed;  // wrap-around row counters, pend = committed - processed
    reg [9:0]  det_row;               // row index of the row being detected
    reg [9:0]  rowy [0:3];            // y of the row held in each bank
    reg [3:0]  fend_dly;
    reg        fend_lat;
    reg        ovf_run, ovf_row, ovf_lab, ovf_cand;
    wire [3:0] pend = committed - processed;
    wire [10:0] x0 = {bc, 1'b0};
    reg  [RB:0] wcnt_t;

    task wr_run; input [10:0] s; input [10:0] e;
        begin
            if (wcnt < MAXR) begin
                runs_s_mem[{wb, wcnt[RB-1:0]}] <= s;
                runs_e_mem[{wb, wcnt[RB-1:0]}] <= e;
                wcnt <= wcnt + 1;
            end else ovf_run <= 1;
        end
    endtask

    always @(posedge clk) begin
        tail_cyc <= 0;
        fend_dly <= {fend_dly[2:0], fend};
        if (fend_dly[3]) fend_lat <= 1;
        if (rst) begin
            in_run <= 0; bc <= 0; wb <= 0; wcnt <= 0; tail_v <= 0; ovf_run <= 0; ovf_row <= 0;
            committed <= 0; fend_dly <= 0; tail_cyc <= 0; fend_lat <= 0; det_row <= 0;
        end else if (fstart) begin
            wb <= 0; wcnt <= 0; ovf_run <= 0; ovf_row <= 0; in_run <= 0; bc <= 0; tail_v <= 0;
            committed <= 0; fend_dly <= 0; fend_lat <= 0; det_row <= 0;
        end else begin
            if (tail_cyc) begin
                // commit the row: optional second run of the last beat, then count
                wcnt_t = wcnt;
                if (tail_v) begin
                    if (wcnt < MAXR) begin
                        runs_s_mem[{wb, wcnt[RB-1:0]}] <= tail_s;
                        runs_e_mem[{wb, wcnt[RB-1:0]}] <= tail_e;
                        wcnt_t = wcnt + 1;
                    end else ovf_run <= 1;
                end
                // backpressure: with 4 banks at most 2 rows may wait (the 4th bank is the previous row, still needed)
                if (pend >= 2) begin ovf_row <= 1; wcnt <= 0; end
                else begin cnt[wb] <= wcnt_t; rowy[wb] <= det_row; wb <= wb + 1; wcnt <= 0; committed <= committed + 1; end
                det_row <= det_row + 1;
            end
            if (v) begin
                bc <= last ? 10'd0 : bc + 1;
                tail_v <= 0;
                case ({in_run, b0, b1})
                    3'b000: ;
                    3'b001: begin in_run <= 1; rstart <= x0 + 11'd1; end
                    3'b010: wr_run(x0, x0);
                    3'b011: begin in_run <= 1; rstart <= x0; end
                    3'b100: begin wr_run(rstart, x0 - 11'd1); in_run <= 0; end
                    3'b101: begin wr_run(rstart, x0 - 11'd1); in_run <= 1; rstart <= x0 + 11'd1; end
                    3'b110: begin wr_run(rstart, x0); in_run <= 0; end
                    3'b111: ;
                endcase
                if (last) begin
                    tail_cyc <= 1; in_run <= 0;
                    // a run still open after this beat is closed at x=1279 by the tail write
                    case ({in_run, b0, b1})
                        3'b001, 3'b101: begin tail_v <= 1; tail_s <= x0 + 11'd1; tail_e <= x0 + 11'd1; end
                        3'b011:         begin tail_v <= 1; tail_s <= x0;         tail_e <= x0 + 11'd1; end
                        3'b111:         begin tail_v <= 1; tail_s <= rstart;     tail_e <= x0 + 11'd1; end
                        default: tail_v <= 0;
                    endcase
                end
            end
        end
    end

    // ------------------------------------------------------------------ label machinery
    reg [LABW-1:0] parent [0:NLAB-1];
    reg [213:0]    stats  [0:NLAB-1];
    reg [LABW:0]   nlab;

    reg [10:0] rs_q, re_q;
    reg [LABW-1:0] rl_q, par_q;
    reg [213:0]    st_q, st_r;
    reg [RB+1:0]   ra;           // {bank, idx}
    reg [LABW-1:0] pa;
    reg [LABW-1:0] sa;

    always @(posedge clk) begin
        rs_q <= runs_s_mem[ra[RB+1:0]];
        re_q <= runs_e_mem[ra[RB+1:0]];
        rl_q <= runlab[ra[RB+1:0]];
        par_q <= parent[pa];
        st_q  <= stats[sa];
        st_r  <= st_q;                       // second register: keeps the compare logic away from the BRAM output delay
    end

    // helper functions on the packed stats vector -------------------------
    function [23:0] cand;
        input integer k;
        input integer cs, ce, y;
        integer sc, ax;
        begin
            case (k)
                0: begin sc = ce;        ax = y;  end
                1: begin sc = -cs;       ax = y;  end
                2: begin sc = y;         ax = cs; end
                3: begin sc = -y;        ax = cs; end
                4: begin sc = ce + y;    ax = ce; end
                5: begin sc = -(cs + y); ax = cs; end
                6: begin sc = ce - y;    ax = ce; end
                default: begin sc = y - cs; ax = cs; end
            endcase
            cand = {sc[12:0], ax[10:0]};
        end
    endfunction

    function [213:0] st_init;
        input integer cs, ce, y;
        integer k;
        reg [213:0] s;
        begin
            s = 214'd0;
            s[213:192] = ce - cs + 1;
            for (k = 0; k < 8; k = k + 1) s[k*24 +: 24] = cand(k, cs, ce, y);
            st_init = s;
        end
    endfunction

    function [213:0] st_update;
        input [213:0] s;
        input integer cs, ce, y;
        integer k;
        reg [23:0] c, o;
        reg [213:0] r;
        begin
            r = s;
            r[213:192] = s[213:192] + (ce - cs + 1);
            for (k = 0; k < 8; k = k + 1) begin
                c = cand(k, cs, ce, y); o = s[k*24 +: 24];
                if ($signed(c[23:11]) > $signed(o[23:11])) r[k*24 +: 24] = c;
            end
            st_update = r;
        end
    endfunction

    function [213:0] st_merge;
        input [213:0] a, b;
        integer k;
        reg [213:0] r;
        reg [23:0] x, y;
        begin
            r = a;
            r[213:192] = a[213:192] + b[213:192];
            for (k = 0; k < 8; k = k + 1) begin
                x = a[k*24 +: 24]; y = b[k*24 +: 24];
                if ($signed(y[23:11]) > $signed(x[23:11])) r[k*24 +: 24] = y;
            end
            st_merge = r;
        end
    endfunction

    // ------------------------------------------------------------------ sequencer
    localparam [5:0]
        S_IDLE = 0, S_CUR_SET = 1, S_CUR_WAIT = 2, S_CUR_USE = 3,
        S_P_CHECK = 4, S_P_WAIT = 5, S_P_USE = 6, S_P_EVAL = 7,
        S_F_SET = 8, S_F_WAIT = 9, S_F_USE = 10,
        S_GOTROOT = 11, S_P_ADV = 12,
        S_U_A_WAIT = 13, S_U_A_USE = 14, S_U_B_SET = 15, S_U_B_WAIT = 16, S_U_B_USE = 17,
        S_FIN = 18, S_FIN_WAIT = 19, S_FIN_USE = 20,
        S_WRLAB = 21, S_ROWEND = 22,
        S_SC_SET = 23, S_SC_WAIT = 24, S_SC_USE = 25, S_SC_WR = 26, S_DONE = 27, S_WAITNEXT = 28, S_SC_CHK = 29, S_SC_DEC = 30, S_FIN_W2 = 31, S_UA_W2 = 32, S_UB_W2 = 33, S_SC_W2 = 34;
    reg [5:0]  S;
    reg [5:0]  f_ret;
    reg [1:0]  rp_bank;
    reg [9:0]  prow;
    reg [9:0]  cur_y;
    reg        has_prev;
    reg [3:0]  hops;
    reg [RB:0] ci, pj, nc, np;
    reg [10:0] cs, ce, ps, pe;
    reg [LABW-1:0] pl, cur_label, fl, rroot;
    reg [213:0] acc;
    reg [15:0] row_cycles;
    reg [LABW:0] scan_l;
    reg [5:0]  cidx;
    reg [3:0]  cw;
    reg [213:0] sr;
    reg          wr_pend; reg [LABW-1:0] wr_addr; reg [213:0] wr_data;   // deferred stats write (breaks compare->BRAM path)
    reg sc_root, ok_a, ok_d, ok_b;
    wire signed [12:0] bsx1 = sr[0*24+11 +: 13], bsxm = sr[1*24+11 +: 13], bsy1 = sr[2*24+11 +: 13], bsym = sr[3*24+11 +: 13];
    wire signed [13:0] bbw = bsx1 + bsxm + 14'sd1, bbh = bsy1 + bsym + 14'sd1;
    wire [1:0] pb_bank = rp_bank - 2'd1;


    always @(posedge clk) begin
        cand_we <= 0; done <= 0;
        wr_pend <= 0;                                   // deferred stats write issued by the previous cycle
        if (wr_pend) stats[wr_addr] <= wr_data;
        if (rst || fstart) begin
            S <= S_IDLE; rp_bank <= 0; prow <= 0; has_prev <= 0; hops <= 0; processed <= 0; nlab <= 1; ovf_lab <= 0; ovf_cand <= 0;
            cand_count <= 0; cidx <= 0; max_row_cycles <= 0; row_cycles <= 0; scan_l <= 1;
            flags <= 0;
        end else begin
            if (S != S_IDLE && S < S_SC_SET) row_cycles <= row_cycles + 1;
            case (S)
                S_IDLE: begin
                    row_cycles <= 0;
                    if (pend != 0) begin
                        nc <= cnt[rp_bank]; cur_y <= rowy[rp_bank];
                        np <= (has_prev && (rowy[pb_bank] + 10'd1 == rowy[rp_bank])) ? cnt[pb_bank] : {(RB+1){1'b0}};
                        ci <= 0; pj <= 0; S <= S_CUR_SET;
                    end else if (fend_lat && pend == 0) S <= S_SC_SET;
                end
                S_CUR_SET: begin
                    if (ci == nc) S <= S_ROWEND;
                    else begin ra <= {rp_bank, ci[RB-1:0]}; S <= S_CUR_WAIT; end
                end
                S_CUR_WAIT: S <= S_CUR_USE;
                S_CUR_USE: begin cs <= rs_q; ce <= re_q; cur_label <= 0; S <= S_P_CHECK; end
                S_P_CHECK: begin
                    if (pj >= np) S <= S_FIN;
                    else begin ra <= {pb_bank, pj[RB-1:0]}; S <= S_P_WAIT; end
                end
                S_P_WAIT: S <= S_P_USE;
                S_P_USE: begin ps <= rs_q; pe <= re_q; pl <= rl_q; S <= S_P_EVAL; end
                S_P_EVAL: begin
                    if (pe < cs) begin pj <= pj + 1; S <= S_P_CHECK; end
                    else if (ps > ce) S <= S_FIN;
                    else if (pl == 0 || {1'b0, pl} >= nlab) S <= S_P_ADV;
                    else begin fl <= pl; f_ret <= S_GOTROOT; hops <= 0; S <= S_F_SET; end
                end
                S_F_SET: begin pa <= fl; S <= S_F_WAIT; end
                S_F_WAIT: S <= S_F_USE;
                S_F_USE: begin
                    if (par_q == fl) begin rroot <= fl; S <= f_ret; end
                    else if (hops == 4'd15) begin rroot <= 0; S <= f_ret; end      // corrupt chain: give up on this overlap
                    else begin fl <= par_q; hops <= hops + 1; S <= S_F_SET; end
                end
                S_GOTROOT: begin
                    if (rroot == 0) S <= S_P_ADV;
                    else if (cur_label == 0) begin cur_label <= rroot; S <= S_P_ADV; end
                    else if (rroot != cur_label) begin sa <= cur_label; S <= S_U_A_WAIT; end
                    else S <= S_P_ADV;
                end
                S_U_A_WAIT: S <= S_UA_W2;
                S_UA_W2: S <= S_U_A_USE;
                S_U_A_USE: begin acc <= st_r; sa <= rroot; S <= S_U_B_WAIT; end
                S_U_B_WAIT: S <= S_UB_W2;
                S_UB_W2: S <= S_U_B_USE;
                S_U_B_USE: begin
                    parent[rroot] <= cur_label;
                    wr_pend <= 1; wr_addr <= cur_label; wr_data <= st_merge(acc, st_r);
                    S <= S_P_ADV;
                end
                S_P_ADV: begin
                    if (pe > ce) S <= S_FIN;
                    else begin pj <= pj + 1; S <= S_P_CHECK; end
                end
                S_FIN: begin
                    if (cur_label == 0) begin
                        if (nlab >= NLAB) begin ovf_lab <= 1; S <= S_WRLAB; end
                        else begin
                            cur_label <= nlab[LABW-1:0]; parent[nlab[LABW-1:0]] <= nlab[LABW-1:0];
                            wr_pend <= 1; wr_addr <= nlab[LABW-1:0]; wr_data <= st_init(cs, ce, cur_y);
                            nlab <= nlab + 1; S <= S_WRLAB;
                        end
                    end else begin sa <= cur_label; S <= S_FIN_WAIT; end
                end
                S_FIN_WAIT: S <= S_FIN_W2;
                S_FIN_W2: S <= S_FIN_USE;
                S_FIN_USE: begin
                    wr_pend <= 1; wr_addr <= cur_label; wr_data <= st_update(st_r, cs, ce, cur_y);
                    S <= S_WRLAB;
                end
                S_WRLAB: begin
                    runlab[{rp_bank, ci[RB-1:0]}] <= cur_label;
                    ci <= ci + 1; S <= S_CUR_SET;
                end
                S_ROWEND: begin
                    rp_bank <= rp_bank + 1; prow <= prow + 1; has_prev <= 1; processed <= processed + 1;
                    if (row_cycles > max_row_cycles) max_row_cycles <= row_cycles;
                    S <= S_IDLE;
                end
                // ---------------------------------------------------------- end-of-frame scan
                S_SC_SET: begin
                    if (scan_l >= nlab) S <= S_DONE;
                    else begin pa <= scan_l[LABW-1:0]; sa <= scan_l[LABW-1:0]; S <= S_SC_WAIT; end
                end
                S_SC_WAIT: S <= S_SC_W2;
                S_SC_W2: S <= S_SC_USE;
                S_SC_USE: begin                                       // stats + parent arrive: register them
                    sr <= st_r; sc_root <= (par_q == scan_l[LABW-1:0]); S <= S_SC_CHK;
                end
                S_SC_CHK: begin                                       // split the wide filter over two cycles
                    ok_a <= (sr[213:192] >= cfg_min_area[21:0]) && (sr[213:192] <= cfg_max_area[21:0]);
                    ok_d <= (bbw >= cfg_min_dim) && (bbh >= cfg_min_dim);
                    ok_b <= !(cfg_reject_border && (bsxm == 0 || bsym == 0 || bsx1 == 1279 || bsy1 == 799));
                    S <= S_SC_DEC;
                end
                S_SC_DEC: begin
                    if (sc_root && ok_a && ok_d && ok_b) begin
                        if (cand_count >= MAXC) begin ovf_cand <= 1; S <= S_SC_SET; scan_l <= scan_l + 1; end
                        else begin cw <= 0; S <= S_SC_WR; end
                    end else begin scan_l <= scan_l + 1; S <= S_SC_SET; end
                end
                S_SC_WR: begin
                    cand_we <= 1; cand_waddr <= {cidx, cw};
                    case (cw)
                        4'd0: cand_wdata <= {10'd0, sr[213:192]};
                        4'd1, 4'd2, 4'd3, 4'd4, 4'd5, 4'd6, 4'd7, 4'd8: cand_wdata <= word_of(sr, cw - 4'd1);
                        4'd9:  cand_wdata <= {20'd0, scan_l[LABW-1:0]};
                        4'd10: cand_wdata <= bbox_x(sr);
                        4'd11: cand_wdata <= bbox_y(sr);
                        default: cand_wdata <= 32'd0;
                    endcase
                    if (cw == 4'd15) begin
                        cidx <= cidx + 1; cand_count <= cand_count + 1; scan_l <= scan_l + 1; S <= S_SC_SET;
                    end else cw <= cw + 1;
                end
                S_WAITNEXT: ;
                S_DONE: begin
                    done <= 1; flags <= {ovf_cand, ovf_lab, ovf_run, ovf_row}; S <= S_WAITNEXT; scan_l <= 1;
                    // idle forever until next frame (fend_seen cleared by fstart)
                end
                default: S <= S_IDLE;
            endcase
        end
    end

    function cand_ok;
        input [213:0] s;
        integer bw, bh;
        reg signed [12:0] sx1, sxm, sy1, sym;
        begin
            sx1 = s[0*24+11 +: 13]; sxm = s[1*24+11 +: 13]; sy1 = s[2*24+11 +: 13]; sym = s[3*24+11 +: 13];
            bw = sx1 + sxm + 1; bh = sy1 + sym + 1;
            cand_ok = (s[213:192] >= cfg_min_area[21:0]) && (s[213:192] <= cfg_max_area[21:0])
                   && (bw >= cfg_min_dim) && (bh >= cfg_min_dim)
                   && !(cfg_reject_border && (sxm == 0 || sym == 0 || sx1 == 1279 || sy1 == 799));
        end
    endfunction

    function [31:0] bbox_x;
        input [213:0] s;
        reg signed [12:0] a, b;
        begin a = s[0*24+11 +: 13]; b = s[1*24+11 +: 13]; bbox_x = {3'd0, a, 3'd0, -b}; end
    endfunction
    function [31:0] bbox_y;
        input [213:0] s;
        reg signed [12:0] a, b;
        begin a = s[2*24+11 +: 13]; b = s[3*24+11 +: 13]; bbox_y = {3'd0, a, 3'd0, -b}; end
    endfunction

    function [31:0] word_of;
        input [213:0] s;
        input [3:0] k;
        reg [23:0] e;
        reg signed [12:0] sc;
        begin
            e = s[k*24 +: 24];
            sc = e[23:11];
            word_of = {5'd0, e[10:0], {3{sc[12]}}, sc};
        end
    endfunction
endmodule
