// Streaming run-based connected-component labeller (4-connected, black = 1) with union-find, label recycling and
// per-component statistics: area plus the 8 directional extremes (+x,-x,+y,-y,+(x+y),-(x+y),+(x-y),+(y-x)).
// Input: binary video 2 px/beat (from thresh_binarize), rows ~LINE_CYC clocks apart.
//
// Dataflow
//   run detector   : runs of the row being received go into one of NB row banks (up to MAXR runs per row).
//   prev prefetch  : a small pipeline streams the previous row's runs (start, end, root label) into a 4-entry FIFO.
//   walker FSM     : merge-walks the current row against that FIFO (about 3 clocks per run on the common path), picks the
//                    label of each run (new label / existing root / union of several roots) and queues a statistics
//                    update for it.
//   stats unit     : pipelined read-modify-write of the 226-bit statistics word of a label (one op per clock, same-label
//                    ops are spaced by 4 clocks).  Unions and terminations wait until the unit is drained.
//   termination    : after every row the roots of previous-row runs that were not extended by the current row are
//                    checked; a component with no run in the current row is finished: it is filtered (area, size, border)
//                    and, if it passes, offered to the top-MAXC-by-area candidate table; its label returns to the free
//                    list.  Labels absorbed by a union are freed one row later (they may still be referenced by run labels).
//   emit           : at frame end the live components are finished the same way, then the surviving candidates are
//                    written as 16-word records (table order, which is not sorted).
// Capacity limits never invalidate a frame: they only drop the offending item and set a (diagnostic) flag.
//
// Record (16 words of 32 bit at cand_addr = {idx[5:0], word[3:0]}):
//   w0 = area                 w1..w8 = dir0..dir7 {aux[15:0], score[15:0]}   (score sign-extended)
//   w9 = label (at termination)  w10 = x0 | x1<<16      w11 = y0 | y1<<16   (bbox)
//   aux: dirs 0,1 -> y ; dirs 2..7 -> x   (the second coordinate follows from the score)
`timescale 1ns/1ps
module run_ccl #(
    parameter MAXR  = 256,          // runs per row (power of two)
    parameter RB    = 8,
    parameter BB    = 2,            // log2(number of row banks); at most NB-2 rows may wait for the labeller
    parameter NLAB  = 1024,         // label table (live labels only; finished components are recycled)
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
    output reg         done,         // pulse: candidate list complete (always fires, whatever the flags)
    output reg  [7:0]  cand_count,
    output reg  [3:0]  flags,        // degraded-frame diagnostics: [0] row dropped [1] run dropped [2] label table full [3] candidate dropped
    output reg  [15:0] max_row_cycles
);
    localparam NB   = 1 << BB;
    localparam LABW = LB;
    localparam STW  = 214;                      // {area[21:0], dir[7:0][23:0]}
    localparam IW   = 33;                       // info word {done, last_row[9:0], area[21:0]}: narrow mirror used by the termination check
    localparam PD   = 4;                        // prev-run FIFO depth
    localparam OQ   = 4;                        // stats op queue depth
    localparam MB   = 6;                        // log2(MAXC)

    // ------------------------------------------------------------------ run detector
    reg [10:0] runs_s_mem [0:NB*MAXR-1];
    reg [10:0] runs_e_mem [0:NB*MAXR-1];
    reg [LABW-1:0] runlab [0:NB*MAXR-1];
    reg [RB:0] cnt [0:NB-1];

    reg        in_run;
    reg [10:0] rstart;
    reg [9:0]  bc;
    reg [BB-1:0] wb;
    reg [RB:0] wcnt;
    reg        tail_cyc, tail_v;      // cycle after the last beat of a row: optional 2nd run + commit
    reg [10:0] tail_s, tail_e;
    reg [3:0]  committed, processed;  // wrap-around row counters, pend = committed - processed
    reg [9:0]  det_row;               // row index of the row being detected
    reg [9:0]  rowy [0:NB-1];         // y of the row held in each bank
    reg [3:0]  fend_dly;
    reg        fend_lat;
    reg        ovf_run, ovf_row, ovf_lab, ovf_cand;
    reg [15:0] rows_dropped;          // diagnostic (testbench only)
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
            committed <= 0; fend_dly <= 0; tail_cyc <= 0; fend_lat <= 0; det_row <= 0; rows_dropped <= 0;
        end else if (fstart) begin
            wb <= 0; wcnt <= 0; ovf_run <= 0; ovf_row <= 0; in_run <= 0; bc <= 0; tail_v <= 0;
            committed <= 0; fend_dly <= 0; fend_lat <= 0; det_row <= 0; rows_dropped <= 0;
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
                // backpressure: NB-2 rows may wait (one bank is the previous row, still needed, one is being filled)
                if (pend >= NB - 2) begin ovf_row <= 1; wcnt <= 0; rows_dropped <= rows_dropped + 1; end
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

    // ------------------------------------------------------------------ memories
    reg [LABW-1:0] parentA [0:NLAB-1];          // two identical copies: A for the prefetcher, B for the walker / termination
    reg [LABW-1:0] parentB [0:NLAB-1];
    reg [STW-1:0]  stats   [0:NLAB-1];
    reg [IW-1:0]   info    [0:NLAB-1];          // {done, last_row, area} mirror of stats
    reg [LABW-1:0] flmem   [0:NLAB-1];          // free-label FIFO
    reg [LABW-1:0] abmem   [0:2*NLAB-1];        // labels absorbed by unions, freed one row later
    reg [STW-1:0]  pool    [0:MAXC-1];          // finished candidates
    reg [21:0]     tarea   [0:MAXC-1];          // their areas
    reg [LABW-1:0] tlab    [0:MAXC-1];          // their labels (information only)
    reg [LABW-1:0] orph    [0:MAXR-1];          // roots to check for termination at the end of the row

    // ------------------------------------------------------------------ state
    localparam [5:0]
        S_IDLE = 0, S_R0 = 1, S_CMP = 2, S_FSET = 3, S_FW = 4, S_FU = 5,
        S_U0 = 6, S_UA1 = 7, S_UA2 = 8, S_UA3 = 9, S_UB1 = 10, S_UB2 = 11, S_UB3 = 12,
        S_FIN = 13, S_FLUSH = 14, S_DRAIN = 15,
        S_T = 16, S_TF0 = 17, S_TF1 = 18, S_TF2 = 19, S_TR1 = 20, S_TR2 = 21, S_TR3 = 22, S_TC0 = 23, S_TC1 = 24,
        S_TOP = 25, S_MS = 26, S_TN = 27,
        S_REL = 28, S_REL1 = 29, S_REL2 = 30, S_ROWEND = 31,
        S_EM0 = 32, S_EM1 = 33, S_EM2 = 34, S_EM3 = 35, S_WR = 36, S_DONE = 37, S_WAITNEXT = 38;
    reg [5:0]  S;

    reg [BB-1:0] rp_bank, pf_bank;
    wire [BB-1:0] pb_bank = rp_bank - 1'b1;
    reg        has_prev, adj, final_pass;
    reg [RB:0] nc, np, ci, pj, fi, cfi, norph, oi, rs_idx;
    reg [9:0]  cur_y;
    reg [LABW-1:0] L, fl, rroot, u_r;
    reg        pm, u_gt;
    reg [4:0]  hops;
    reg [LB:0] nlab;
    reg [15:0] row_cycles;
    reg [STW-1:0] acc, sr;
    reg        ok_a, ok_d, ok_b;
    reg [MB:0] t_cnt;
    reg [21:0] t_min_area;
    reg [MB-1:0] t_min_idx, scan_i;
    reg [MB:0] ei;
    reg [3:0]  cw;

    // ---- stats op queue
    reg        op_k [0:OQ-1]; reg [LABW-1:0] op_L [0:OQ-1]; reg [10:0] op_cs [0:OQ-1]; reg [10:0] op_ce [0:OQ-1]; reg [9:0] op_y [0:OQ-1];
    reg [1:0]  oq_rd, oq_wr; reg [2:0] oq_cnt;
    // stats unit pipeline: stage 1 = sa visible, stage 2 = st_q valid, stage 3 = st_r valid (compute), then the write
    reg        hv1, hv2, hv3; reg [LABW-1:0] hL1, hL2, hL3;
    reg        p2v, p3v;
    reg        p1k, p2k, p3k; reg [10:0] p1cs, p2cs, p3cs, p1ce, p2ce, p3ce; reg [9:0] p1y, p2y, p3y;
    wire stats_idle = (oq_cnt == 0) && !hv1 && !hv2 && !hv3;

    // ---- current-row run FIFO (head = the run being labelled)
    reg [BB+RB-1:0] ca;
    reg [10:0] cq_s, cq_e;
    reg        cv0, cv1, cf_run;
    always @(posedge clk) begin
        cq_s <= runs_s_mem[ca];
        cq_e <= runs_e_mem[ca];
    end
    reg [10:0] c_s [0:PD-1]; reg [10:0] c_e [0:PD-1];
    reg [1:0] c_rd, c_wr; reg [2:0] c_cnt;
    wire cvalid = (c_cnt != 0);
    wire [10:0] cs = c_s[c_rd], ce = c_e[c_rd];

    // ---- previous-row prefetch pipeline
    reg [BB+RB-1:0] pf_a;
    reg [10:0] rq_s, rq_e, s2_s, s2_e;
    reg [LABW-1:0] rlq, s2_l, parqA;
    reg        v0, v1, v2, pf_run;
    always @(posedge clk) begin
        rq_s <= runs_s_mem[pf_a];
        rq_e <= runs_e_mem[pf_a];
        rlq  <= runlab[pf_a];
        parqA <= parentA[rlq];
    end
    reg [10:0] f_s [0:PD-1]; reg [10:0] f_e [0:PD-1]; reg [LABW-1:0] f_r [0:PD-1]; reg f_nf [0:PD-1];
    reg [1:0] f_rd, f_wr; reg [2:0] f_cnt;
    wire head_v = (f_cnt != 0);
    wire [10:0] hs = f_s[f_rd], he = f_e[f_rd];
    wire [LABW-1:0] hr = f_r[f_rd];
    wire hnf = f_nf[f_rd];

    // ---- walker / termination read port (parent copy B + info), same address
    reg [LABW-1:0] pa;
    reg [LABW-1:0] par_q;
    reg [IW-1:0]   inf_q;
    always @(posedge clk) begin par_q <= parentB[pa]; inf_q <= info[pa]; end
    wire [10:0] mq = inf_q[32:22];
    wire [21:0] aq = inf_q[21:0];

    // ---- stats port
    reg [LABW-1:0] sa;
    reg [STW-1:0]  st_q, st_r;
    always @(posedge clk) begin st_q <= stats[sa]; st_r <= st_q; end
    reg          wr_pend; reg [LABW-1:0] wr_addr; reg [STW-1:0] wr_data; reg [9:0] wr_meta;

    // ---- free list / absorbed list
    reg [LB-1:0] fr_rd, fr_wr; reg [LB:0] fr_cnt;
    reg [LABW-1:0] fq; reg fq_ok;
    always @(posedge clk) fq <= flmem[fr_rd];
    reg [LB:0] ab_head, ab_mid, ab_tail;
    reg [LABW-1:0] ab_q;
    always @(posedge clk) ab_q <= abmem[ab_head];

    // ---- candidate pool read
    reg [MB-1:0] pool_a; reg [STW-1:0] pool_q; reg [LABW-1:0] tlab_q;
    always @(posedge clk) begin pool_q <= pool[pool_a]; tlab_q <= tlab[pool_a]; end

    // ---- pipelined termination check
    reg        g1v, g2v, lr_v; reg [LABW-1:0] g1_l, g2_l, lr; reg [RB:0] g1_i, g2_i;

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

    function [STW-1:0] st_init;
        input integer cs, ce, y;
        integer k;
        reg [STW-1:0] s;
        begin
            s = {STW{1'b0}};
            s[213:192] = ce - cs + 1;
            for (k = 0; k < 8; k = k + 1) s[k*24 +: 24] = cand(k, cs, ce, y);
            st_init = s;
        end
    endfunction

    function [STW-1:0] st_update;
        input [STW-1:0] s;
        input integer cs, ce, y;
        integer k;
        reg [23:0] c, o;
        reg [STW-1:0] r;
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

    function [STW-1:0] st_merge;
        input [STW-1:0] a, b;
        integer k;
        reg [STW-1:0] r;
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

    wire signed [12:0] bsx1 = sr[0*24+11 +: 13], bsxm = sr[1*24+11 +: 13], bsy1 = sr[2*24+11 +: 13], bsym = sr[3*24+11 +: 13];
    wire signed [13:0] bbw = bsx1 + bsxm + 14'sd1, bbh = bsy1 + bsym + 14'sd1;

    // ------------------------------------------------------------------ sequencer
    reg        pop, cpop, oq_push, oq_kind, pf_flush, par_we, fl_push, ab_push, free_pop, tm_we;
    reg [LABW-1:0] par_wa, par_wd, fl_d, ab_d, oq_lab, tm_a;
    reg [IW-1:0] tm_d;
    reg [RB:0] pj_n;
    reg [LABW-1:0] Lh; reg haz, issue;
    reg [2:0]  infl, cinfl; reg can_issue, c_issue; reg [LABW-1:0] pr_r; reg pr_nf;
    reg [LABW-1:0] ol;
    reg        fin_req, fin_ok, fin_kind, t_slow, t_term;
    reg [LABW-1:0] fin_L, fin_lab;
    wire last_cur = (ci + 1'b1 == nc);

    always @(posedge clk) begin
        cand_we <= 0; done <= 0;
        wr_pend <= 0;
        if (wr_pend) begin
            stats[wr_addr] <= wr_data;
            info[wr_addr] <= {1'b0, wr_meta, wr_data[213:192]};
        end
        pop = 0; cpop = 0; oq_push = 0; oq_kind = 0; oq_lab = 0; pf_flush = 0; par_we = 0; fl_push = 0; ab_push = 0;
        free_pop = 0; tm_we = 0; tm_a = 0; tm_d = 0; pj_n = pj; fin_req = 0; fin_L = 0; t_slow = 0; t_term = 0;
        par_wa = 0; par_wd = 0; fl_d = 0; ab_d = 0;
        if (rst || fstart) begin
            S <= S_IDLE; rp_bank <= 0; has_prev <= 0; processed <= 0; nlab <= 1; ovf_lab <= 0; ovf_cand <= 0;
            cand_count <= 0; max_row_cycles <= 0; row_cycles <= 0; flags <= 0; final_pass <= 0;
            f_cnt <= 0; f_rd <= 0; f_wr <= 0; v0 <= 0; v1 <= 0; v2 <= 0; pf_run <= 0; fi <= 0; pj <= 0;
            c_cnt <= 0; c_rd <= 0; c_wr <= 0; cv0 <= 0; cv1 <= 0; cf_run <= 0; cfi <= 0;
            oq_cnt <= 0; oq_rd <= 0; oq_wr <= 0; hv1 <= 0; hv2 <= 0; hv3 <= 0; p2v <= 0; p3v <= 0;
            fr_rd <= 0; fr_wr <= 0; fr_cnt <= 0; fq_ok <= 0; ab_head <= 0; ab_mid <= 0; ab_tail <= 0;
            t_cnt <= 0; t_min_area <= 22'h3FFFFF; t_min_idx <= 0; norph <= 0; g1v <= 0; g2v <= 0; lr_v <= 0;
        end else begin
            if (S != S_IDLE && S < S_EM0 && !final_pass) row_cycles <= row_cycles + 1;

            // ------------------------------------------------ stats unit
            Lh = op_L[oq_rd];
            haz = (hv1 && hL1 == Lh) || (hv2 && hL2 == Lh) || (hv3 && hL3 == Lh);
            issue = (oq_cnt != 0) && !haz;
            hv3 <= hv2; hL3 <= hL2; hv2 <= hv1; hL2 <= hL1; hv1 <= issue; hL1 <= Lh;
            if (issue) begin
                sa <= Lh;
                p1k <= op_k[oq_rd]; p1cs <= op_cs[oq_rd]; p1ce <= op_ce[oq_rd]; p1y <= op_y[oq_rd];
                oq_rd <= oq_rd + 1'b1;
            end
            p2v <= hv1; p2k <= p1k; p2cs <= p1cs; p2ce <= p1ce; p2y <= p1y;
            p3v <= p2v; p3k <= p2k; p3cs <= p2cs; p3ce <= p2ce; p3y <= p2y;
            if (p3v) begin
                wr_pend <= 1; wr_addr <= hL3; wr_meta <= p3y;
                wr_data <= p3k ? st_init(p3cs, p3ce, p3y) : st_update(st_r, p3cs, p3ce, p3y);
            end

            // ------------------------------------------------ sequencer FSM
            case (S)
                S_IDLE: begin
                    row_cycles <= 0;
                    if (pend != 0) begin
                        nc <= cnt[rp_bank]; cur_y <= rowy[rp_bank];
                        np <= has_prev ? cnt[pb_bank] : {(RB+1){1'b0}};
                        adj <= has_prev && (rowy[pb_bank] + 10'd1 == rowy[rp_bank]);
                        pf_bank <= pb_bank; final_pass <= 0; S <= S_R0;
                    end else if (fend_lat) begin
                        // frame end: the last processed row is "previous", there is no current row; everything alive terminates
                        nc <= 0; np <= has_prev ? cnt[pb_bank] : {(RB+1){1'b0}}; adj <= 0; pf_bank <= pb_bank;
                        final_pass <= 1; S <= S_R0;
                    end
                end
                S_R0: begin
                    ci <= 0; pj_n = 0; pm <= 0; L <= 0; norph <= 0; pf_flush = 1; pf_run <= 1; cf_run <= 1;
                    c_cnt <= 0; c_rd <= 0; c_wr <= 0; cv0 <= 0; cv1 <= 0; cfi <= 0;
                    S <= S_CMP;
                end
                S_CMP: begin
                    if (ci == nc) S <= S_FLUSH;
                    else if (cvalid) begin
                        if (head_v) begin
                            if (!adj || he < cs) begin                   // previous run ends before the current one: consume
                                if (!pm && hr != 0) begin orph[norph] <= hr; norph <= norph + 1'b1; end
                                pop = 1; pj_n = pj + 1'b1; pm <= 0;
                            end else if (hs > ce) begin fin_req = 1; fin_L = L; end   // previous run starts after the current one
                            else if (hnf) begin fl <= hr; hops <= 0; S <= S_FSET; end
                            else begin                                   // overlap
                                if (hr != 0 && L != 0 && hr != L) begin
                                    u_r <= hr; u_gt <= (he > ce); S <= S_U0;
                                end else begin
                                    if (hr != 0 && L == 0) L <= hr;
                                    if (he > ce) begin pm <= 1; fin_req = 1; fin_L = (L != 0) ? L : hr; end
                                    else begin pop = 1; pj_n = pj + 1'b1; pm <= 0; end
                                end
                            end
                        end else if (pj >= np) begin fin_req = 1; fin_L = L; end
                    end
                end
                // ---- slow root search for the FIFO head
                S_FSET: begin pa <= fl; S <= S_FW; end
                S_FW: S <= S_FU;
                S_FU: begin
                    if (par_q == fl) begin f_r[f_rd] <= fl; f_nf[f_rd] <= 0; S <= S_CMP; end
                    else if (hops == 5'd31) begin f_r[f_rd] <= 0; f_nf[f_rd] <= 0; S <= S_CMP; end
                    else begin fl <= par_q; hops <= hops + 1'b1; S <= S_FSET; end
                end
                // ---- union: root u_r is absorbed into L
                S_U0: if (stats_idle) begin sa <= L; S <= S_UA1; end
                S_UA1: S <= S_UA2;
                S_UA2: S <= S_UA3;
                S_UA3: begin acc <= st_r; sa <= u_r; S <= S_UB1; end
                S_UB1: S <= S_UB2;
                S_UB2: S <= S_UB3;
                S_UB3: begin
                    par_we = 1; par_wa = u_r; par_wd = L;
                    wr_pend <= 1; wr_addr <= L; wr_meta <= cur_y; wr_data <= st_merge(acc, st_r);
                    ab_push = 1; ab_d = u_r;
                    if (u_gt) pm <= 1; else begin pj_n = pj + 1'b1; pm <= 0; end
                    pf_flush = 1;                                        // prefetched roots may be stale now
                    S <= u_gt ? S_FIN : S_CMP;
                end
                S_FIN: begin fin_req = 1; fin_L = L; end                 // retry of a finish that had to wait
                // ---- all current runs done: pass the remaining previous runs to the orphan list
                S_FLUSH: begin
                    if (head_v) begin
                        if (!pm && hr != 0) begin orph[norph] <= hr; norph <= norph + 1'b1; end
                        pop = 1; pj_n = pj + 1'b1; pm <= 0;
                    end else if (pj >= np) S <= S_DRAIN;
                end
                S_DRAIN: if (stats_idle) begin oi <= 0; g1v <= 0; g2v <= 0; lr_v <= 0; S <= S_T; end
                // ---- termination check of the orphan roots: 1 root per clock when the root is known and the component is small
                S_T: begin
                    if (g2v && g2_l != 0) begin
                        if (par_q != g2_l) begin                         // stale label: find its root the slow way
                            t_slow = 1; fl <= par_q; hops <= 1; S <= S_TF0;
                        end else if (!(mq[10] || (!final_pass && mq[9:0] == cur_y) || (lr_v && lr == g2_l))) begin
                            if (aq < cfg_min_area[21:0] || aq > cfg_max_area[21:0]) begin
                                t_term = 1; fl_push = 1; fl_d = g2_l;    // finished and rejected by size: free it
                                tm_we = 1; tm_a = g2_l; tm_d = {1'b1, 10'd0, aq};
                            end else begin                               // needs the bounding box: read the full statistics
                                t_slow = 1; rroot <= g2_l; sa <= g2_l; pa <= g2_l; S <= S_TR1;
                            end
                        end
                    end
                    lr_v <= t_term; lr <= g2_l;
                    if (t_slow) begin g1v <= 0; g2v <= 0; rs_idx <= g2_i + 1'b1; end
                    else begin
                        g2v <= g1v; g2_l <= g1_l; g2_i <= g1_i;
                        if (oi < norph) begin
                            ol = orph[oi]; pa <= ol; g1v <= 1; g1_l <= ol; g1_i <= oi; oi <= oi + 1'b1;
                        end else g1v <= 0;
                        if (oi >= norph && !g1v && !g2v) S <= final_pass ? S_EM0 : S_REL;
                    end
                end
                S_TF0: begin pa <= fl; S <= S_TF1; end
                S_TF1: S <= S_TF2;
                S_TF2: begin
                    if (par_q == fl) begin rroot <= fl; sa <= fl; S <= S_TR1; end
                    else if (hops == 5'd31) S <= S_TN;
                    else begin fl <= par_q; hops <= hops + 1'b1; S <= S_TF0; end
                end
                S_TR1: S <= S_TR2;
                S_TR2: S <= S_TR3;
                S_TR3: begin sr <= st_r; S <= S_TC0; end
                S_TC0: begin
                    if (mq[10] || (!final_pass && mq[9:0] == cur_y)) S <= S_TN;     // done already / extended by this row
                    else begin
                        ok_a <= (sr[213:192] >= cfg_min_area[21:0]) && (sr[213:192] <= cfg_max_area[21:0]);
                        ok_d <= (bbw >= cfg_min_dim) && (bbh >= cfg_min_dim);
                        ok_b <= !(cfg_reject_border && (bsxm == 0 || bsym == 0 || bsx1 == 1279 || bsy1 == 799));
                        S <= S_TC1;
                    end
                end
                S_TC1: begin                                             // component finished: mark, free, maybe keep
                    tm_we = 1; tm_a = rroot; tm_d = {1'b1, 10'd0, sr[213:192]};
                    fl_push = 1; fl_d = rroot;
                    S <= (ok_a && ok_d && ok_b) ? S_TOP : S_TN;
                end
                S_TOP: begin
                    if (t_cnt < MAXC) begin
                        pool[t_cnt[MB-1:0]] <= sr; tlab[t_cnt[MB-1:0]] <= rroot;
                        tarea[t_cnt[MB-1:0]] <= sr[213:192];
                        if (t_cnt == 0 || sr[213:192] < t_min_area) begin t_min_area <= sr[213:192]; t_min_idx <= t_cnt[MB-1:0]; end
                        t_cnt <= t_cnt + 1'b1; S <= S_TN;
                    end else if (sr[213:192] > t_min_area) begin           // replace the smallest kept candidate
                        pool[t_min_idx] <= sr; tlab[t_min_idx] <= rroot;
                        tarea[t_min_idx] <= sr[213:192];
                        ovf_cand <= 1; scan_i <= 0; t_min_area <= 22'h3FFFFF; S <= S_MS;
                    end else begin ovf_cand <= 1; S <= S_TN; end
                end
                S_MS: begin                                              // find the new minimum (one entry per clock)
                    if (tarea[scan_i] < t_min_area) begin t_min_area <= tarea[scan_i]; t_min_idx <= scan_i; end
                    scan_i <= scan_i + 1'b1;
                    if (scan_i == MAXC - 1) S <= S_TN;
                end
                S_TN: begin oi <= rs_idx; g1v <= 0; g2v <= 0; lr_v <= 0; S <= S_T; end
                // ---- free the labels absorbed during the previous row
                S_REL: begin
                    if (ab_head == ab_mid) begin ab_mid <= ab_tail; S <= S_ROWEND; end
                    else S <= S_REL1;
                end
                S_REL1: S <= S_REL2;
                S_REL2: begin fl_push = 1; fl_d = ab_q; ab_head <= ab_head + 1'b1; S <= S_REL; end
                S_ROWEND: begin
                    rp_bank <= rp_bank + 1'b1; has_prev <= 1; processed <= processed + 1'b1;
                    if (row_cycles > max_row_cycles) max_row_cycles <= row_cycles;
                    S <= S_IDLE;
                end
                // ---------------------------------------------------------- emit the kept candidates
                S_EM0: begin ei <= 0; cand_count <= 0; S <= S_EM1; end
                S_EM1: begin
                    if (ei >= t_cnt) S <= S_DONE;
                    else begin pool_a <= ei[MB-1:0]; S <= S_EM2; end
                end
                S_EM2: S <= S_EM3;
                S_EM3: begin sr <= pool_q; rroot <= tlab_q; cw <= 0; S <= S_WR; end
                S_WR: begin
                    cand_we <= 1; cand_waddr <= {ei[5:0], cw};
                    case (cw)
                        4'd0: cand_wdata <= {10'd0, sr[213:192]};
                        4'd1, 4'd2, 4'd3, 4'd4, 4'd5, 4'd6, 4'd7, 4'd8: cand_wdata <= word_of(sr, cw - 4'd1);
                        4'd9:  cand_wdata <= {{(32-LB){1'b0}}, rroot};
                        4'd10: cand_wdata <= bbox_x(sr);
                        4'd11: cand_wdata <= bbox_y(sr);
                        default: cand_wdata <= 32'd0;
                    endcase
                    if (cw == 4'd15) begin
                        ei <= ei + 1'b1; cand_count <= {1'b0, ei} + 8'd1; S <= S_EM1;
                    end else cw <= cw + 1'b1;
                end
                S_DONE: begin
                    done <= 1; flags <= {ovf_cand, ovf_lab, ovf_run, ovf_row}; S <= S_WAITNEXT;
                end
                default: ;
            endcase

            // ------------------------------------------------ finish the current run (label it, queue its statistics update)
            if (fin_req) begin
                fin_ok = 0; fin_lab = 0; fin_kind = 0;
                if (fin_L != 0) begin
                    if (oq_cnt < OQ) begin fin_ok = 1; fin_lab = fin_L; end
                end else if (fr_cnt != 0) begin                          // recycled label
                    if (fq_ok && oq_cnt < OQ) begin fin_ok = 1; fin_lab = fq; fin_kind = 1; free_pop = 1; end
                end else if (nlab < NLAB) begin                          // never used label
                    if (oq_cnt < OQ) begin fin_ok = 1; fin_lab = nlab[LB-1:0]; fin_kind = 1; nlab <= nlab + 1'b1; end
                end else begin fin_ok = 1; ovf_lab <= 1; end             // table full: the run stays unlabelled (background)
                if (fin_ok) begin
                    if (fin_lab != 0) begin
                        oq_push = 1; oq_kind = fin_kind; oq_lab = fin_lab;
                        if (fin_kind) begin par_we = 1; par_wa = fin_lab; par_wd = fin_lab; end
                    end
                    runlab[{rp_bank, ci[RB-1:0]}] <= fin_lab;
                    cpop = 1; ci <= ci + 1'b1; L <= 0;
                    S <= last_cur ? S_FLUSH : S_CMP;
                end else S <= S_FIN;
            end

            // ------------------------------------------------ bookkeeping (queues, FIFOs, memories)
            pj <= pj_n;
            if (oq_push) begin
                op_k[oq_wr] <= oq_kind; op_L[oq_wr] <= oq_lab; op_cs[oq_wr] <= cs; op_ce[oq_wr] <= ce; op_y[oq_wr] <= cur_y;
                oq_wr <= oq_wr + 1'b1;
            end
            oq_cnt <= oq_cnt + oq_push - issue;
            if (par_we) begin parentA[par_wa] <= par_wd; parentB[par_wa] <= par_wd; end
            if (tm_we) info[tm_a] <= tm_d;
            if (fl_push) begin flmem[fr_wr] <= fl_d; fr_wr <= fr_wr + 1'b1; end
            if (free_pop) fr_rd <= fr_rd + 1'b1;
            fr_cnt <= fr_cnt + fl_push - free_pop;
            fq_ok <= !(free_pop || (fl_push && fr_cnt == 0));
            if (ab_push) begin abmem[ab_tail] <= ab_d; ab_tail <= ab_tail + 1'b1; end

            // current-row run fetch
            cinfl = cv0 + cv1;
            c_issue = cf_run && (cfi < nc) && ((c_cnt + cinfl) < PD);
            cv0 <= c_issue; cv1 <= cv0;
            if (c_issue) begin ca <= {rp_bank, cfi[RB-1:0]}; cfi <= cfi + 1'b1; end
            if (cv1) begin c_s[c_wr] <= cq_s; c_e[c_wr] <= cq_e; c_wr <= c_wr + 1'b1; end
            c_cnt <= c_cnt + cv1 - cpop;
            if (cpop) c_rd <= c_rd + 1'b1;
            if (S == S_R0) begin c_cnt <= 0; c_rd <= 0; c_wr <= 0; cv0 <= 0; cv1 <= 0; cfi <= 0; end

            // previous-row prefetch pipeline
            infl = v0 + v1 + v2;
            can_issue = pf_run && (fi < np) && ((f_cnt + infl) < PD);
            v0 <= can_issue; v1 <= v0; v2 <= v1;
            if (can_issue) begin pf_a <= {pf_bank, fi[RB-1:0]}; fi <= fi + 1'b1; end
            s2_s <= rq_s; s2_e <= rq_e; s2_l <= rlq;
            pr_nf = (s2_l != 0) && (parqA != s2_l);
            pr_r  = (s2_l == 0) ? {LABW{1'b0}} : (parqA == s2_l) ? s2_l : parqA;
            if (v2) begin
                f_s[f_wr] <= s2_s; f_e[f_wr] <= s2_e; f_r[f_wr] <= pr_r; f_nf[f_wr] <= pr_nf; f_wr <= f_wr + 1'b1;
            end
            f_cnt <= f_cnt + v2 - pop;
            if (pop) f_rd <= f_rd + 1'b1;
            if (pf_flush) begin
                v0 <= 0; v1 <= 0; v2 <= 0; f_cnt <= 0; f_rd <= 0; f_wr <= 0; fi <= pj_n;
            end
        end
    end

    function [31:0] bbox_x;
        input [STW-1:0] s;
        reg signed [12:0] a, b;
        begin a = s[0*24+11 +: 13]; b = s[1*24+11 +: 13]; bbox_x = {3'd0, a, 3'd0, -b}; end
    endfunction
    function [31:0] bbox_y;
        input [STW-1:0] s;
        reg signed [12:0] a, b;
        begin a = s[2*24+11 +: 13]; b = s[3*24+11 +: 13]; bbox_y = {3'd0, a, 3'd0, -b}; end
    endfunction

    function [31:0] word_of;
        input [STW-1:0] s;
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
