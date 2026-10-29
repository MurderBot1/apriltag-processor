// The FIFOs are 128 deep so the core may run slower than the sensor byte clock (100 MHz): a 640-beat line burst is absorbed
// and drained in 640/f_core (7.5 us at 85.7 MHz) which still fits the 8.0 us line period.
// MIPI D-PHY 2-lane HS receiver for the ECP5 (no hard D-PHY): LVDS inputs, edge clock taken from the sensor's clock lane,
// IDDRX2F 4:1 gearing, per-lane bit-slip alignment on the SoT sync byte, 2-lane deskew + clock-domain crossing into the
// core clock.  Output matches what csi2_rx expects: hs_valid / lane0 / lane1, first beat = packet header.
//
// USE_PRIM = 1 : ECP5 primitives (ECLKSYNCB, CLKDIVF, IDDRX2F)      USE_PRIM = 0 : behavioural DDR model (simulation)
// The lane aligner tries both nibble orders (Q0 first / Q3 first) in parallel and locks whichever finds the sync byte,
// so the design does not depend on the exact bit order convention of the gearbox primitive.
`timescale 1ns/1ps
module dphy_rx #(
    parameter USE_PRIM = 0,
    parameter BEH_REVERSE = 0,        // simulation only: deliver the gearbox nibble in the opposite bit order
    parameter START_LEVEL = 10,
    parameter TIMEOUT = 1000          // core clocks of continuous hs_valid without a packet end -> force re-sync
) (
    input  wire        clk_p,         // clock lane (positive pin, LVDS), 400 MHz DDR
    input  wire [1:0]  d_p,           // data lanes (positive pins)
    input  wire        core_clk,
    input  wire        core_rst,
    input  wire        pkt_end,       // pulse from csi2_rx: current packet fully consumed (or dropped)
    output reg         hs_valid = 0,
    output reg  [7:0]  lane0 = 0,
    output reg  [7:0]  lane1 = 0,
    output wire [3:0]  status         // {lane1 locked, lane0 locked, resyncs counter lsb, clock seen}
);
    // ------------------------------------------------------------------ clocks
    wire eclk, sclk;
    // ALIGNWD of CLKDIVF/IDDRX2F is left unconnected (word alignment is done in the lane aligner): nextpnr-ecp5 0.7
    // mis-packs ALIGNWD nets that have any other user, including constants.
    generate if (USE_PRIM) begin : g_prim
        wire eclk_i;
        ECLKSYNCB eclksync(.ECLKI(clk_p), .STOP(1'b0), .ECLKO(eclk_i));
        assign eclk = eclk_i;
        CLKDIVF #(.DIV("2.0")) clkdiv(.CLKI(eclk_i), .RST(1'b0), .CDIVX(sclk));
    end else begin : g_beh
        reg div = 0;
        assign eclk = clk_p;
        always @(posedge clk_p) div <= ~div;
        assign sclk = ~div;      // rising edges fall between q updates (no race in simulation)
    end endgenerate

    // ------------------------------------------------------------------ gearboxes
    wire [3:0] q0, q1;               // {Q3,Q2,Q1,Q0}
    generate if (USE_PRIM) begin : g_gear
        IDDRX2F g0(.D(d_p[0]), .SCLK(sclk), .ECLK(eclk), .RST(1'b0), .Q3(q0[3]), .Q2(q0[2]), .Q1(q0[1]), .Q0(q0[0]));
        IDDRX2F g1(.D(d_p[1]), .SCLK(sclk), .ECLK(eclk), .RST(1'b0), .Q3(q1[3]), .Q2(q1[2]), .Q1(q1[1]), .Q0(q1[0]));
    end else begin : g_gear_beh
        // behavioural model of IDDRX2F: sample on both edges of the DDR clock, 4 samples (earliest first) per divided clock
        reg       ph = 0;
        reg       a_r0, a_f0, a_r1, a_f1, b_r0, b_f0, b_r1, b_f1;
        reg [3:0] qq0 = 0, qq1 = 0;
        always @(posedge clk_p) begin
            ph <= ~ph;
            if (!ph) begin a_r0 <= d_p[0]; a_r1 <= d_p[1]; end          // even cycle rising sample
            else     begin b_r0 <= d_p[0]; b_r1 <= d_p[1]; end          // odd cycle rising sample
            if (!ph) begin                                               // previous pair is complete and stable
                qq0 <= {b_f0, b_r0, a_f0, a_r0};
                qq1 <= {b_f1, b_r1, a_f1, a_r1};
            end
        end
        always @(negedge clk_p) begin
            if (ph) begin a_f0 <= d_p[0]; a_f1 <= d_p[1]; end            // ph already toggled: this fall belongs to the even cycle
            else    begin b_f0 <= d_p[0]; b_f1 <= d_p[1]; end
        end
        assign q0 = BEH_REVERSE ? {qq0[0], qq0[1], qq0[2], qq0[3]} : qq0;
        assign q1 = BEH_REVERSE ? {qq1[0], qq1[1], qq1[2], qq1[3]} : qq1;
    end endgenerate

    // ------------------------------------------------------------------ unlock request (core -> sclk)
    reg [3:0] unl_cnt = 0;
    reg       unl_core = 0;
    reg       to_fire = 0;
    reg [15:0] to_cnt = 0;
    always @(posedge core_clk) begin
        if (core_rst) begin unl_cnt <= 0; unl_core <= 0; to_cnt <= 0; to_fire <= 0; end
        else begin
            to_fire <= 0;
            if (hs_valid) begin to_cnt <= to_cnt + 1; if (to_cnt == TIMEOUT) to_fire <= 1; end else to_cnt <= 0;
            if (pkt_end || to_fire) unl_cnt <= 4'd10;
            else if (unl_cnt != 0) unl_cnt <= unl_cnt - 1;
            unl_core <= (unl_cnt != 0);
        end
    end
    reg [1:0] unl_s = 0; always @(posedge sclk) begin unl_s <= {unl_s[0], unl_core}; end
    wire unlock = unl_s[1];

    // ------------------------------------------------------------------ lanes (two nibble orders each)
    wire [3:0] qn [0:1]; assign qn[0] = q0; assign qn[1] = q1;
    genvar L;
    wire [1:0] bv; wire [7:0] bd [0:1]; wire [1:0] lock_any;
    generate for (L = 0; L < 2; L = L + 1) begin : g_lane
        wire va, vb, ka, kb; wire [7:0] da, db;
        wire [3:0] qrev = {qn[L][0], qn[L][1], qn[L][2], qn[L][3]};
        // the engine that is not selected is forced into "unlocked" by the other's lock via its own unlock input
        wire unl_a = unlock | (kb & ~ka);
        wire unl_b = unlock | (ka & ~kb);
        dphy_lane la(.sclk(sclk), .rst(1'b0), .q(qn[L]), .unlock(unl_a), .byte_valid(va), .byte_data(da), .locked(ka));
        dphy_lane lb(.sclk(sclk), .rst(1'b0), .q(qrev),  .unlock(unl_b), .byte_valid(vb), .byte_data(db), .locked(kb));
        assign bv[L] = va | vb;
        assign bd[L] = va ? da : db;
        assign lock_any[L] = ka | kb;
    end endgenerate

    // ------------------------------------------------------------------ FIFOs (sclk -> core)
    wire [1:0] empty; wire [7:0] fill0, fill1; wire [7:0] rd0, rd1;
    reg  ren0 = 0, ren1 = 0;
    wire flush_rd;
    async_fifo #(.W(8), .AW(7)) f0(.wclk(sclk), .wrst(1'b0), .wen(bv[0]), .wdata(bd[0]), .wfull(),
        .rclk(core_clk), .rrst(core_rst), .ren(ren0), .rflush(flush_rd), .rdata(rd0), .rempty(empty[0]), .rfill(fill0));
    async_fifo #(.W(8), .AW(7)) f1(.wclk(sclk), .wrst(1'b0), .wen(bv[1]), .wdata(bd[1]), .wfull(),
        .rclk(core_clk), .rrst(core_rst), .ren(ren1), .rflush(flush_rd), .rdata(rd1), .rempty(empty[1]), .rfill(fill1));

    // ------------------------------------------------------------------ read side
    localparam R_IDLE = 0, R_RUN = 1, R_WAIT = 2, R_FLUSH = 3, R_DROPW = 4;
    reg [2:0] rs = 0; reg [5:0] wcnt = 0; reg got; reg pend0 = 0, pend1 = 0;
    reg [3:0] resyncs = 0;
    always @(posedge core_clk) begin
        hs_valid <= 0; ren0 <= 0; ren1 <= 0; pend0 <= ren0 & ~empty[0]; pend1 <= ren1 & ~empty[1];
        if (core_rst) begin rs <= R_IDLE; wcnt <= 0; resyncs <= 0; end
        else case (rs)
            R_IDLE: if (fill0 >= START_LEVEL && fill1 >= START_LEVEL) begin rs <= R_RUN; ren0 <= 1; ren1 <= 1; end
            R_RUN: if (pkt_end) begin rs <= R_DROPW; wcnt <= 0; end   // packet layer is done: emit nothing more, then discard the trailing garbage
            else begin
                // reads were issued last cycle; data appears one cycle after ren (registered rdata)
                if (pend0 & pend1) begin hs_valid <= 1; lane0 <= rd0; lane1 <= rd1; end
                if (!empty[0] && !empty[1]) begin ren0 <= 1; ren1 <= 1; end
                else begin rs <= R_WAIT; wcnt <= 0; end
            end
            R_WAIT: begin
                if (pend0 & pend1) begin hs_valid <= 1; lane0 <= rd0; lane1 <= rd1; end
                wcnt <= wcnt + 1;
                if (wcnt == 6'd12) begin rs <= R_FLUSH; end
            end
            R_DROPW: begin                                      // after a packet end: no further beats, wait for the lanes to unlock
                wcnt <= wcnt + 1;
                if (wcnt == 6'd12) rs <= R_FLUSH;
            end
            R_FLUSH: begin                                      // one-cycle pointer reset of both FIFOs
                rs <= R_IDLE; resyncs <= resyncs + 1;
            end
        endcase
    end
    assign flush_rd = (rs == R_FLUSH);
    assign status = {lock_any[1], lock_any[0], resyncs[0], 1'b1};
endmodule
