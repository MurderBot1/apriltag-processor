// TPU: Tag Processing Unit - a small custom processor whose instruction ROM is the baked edge-refinement /
// decode program (tools/tpu_prog.py -> rtl/tpu_prog.hex) with a baked tag36h11 code ROM.
// Bit-exact with the Python ISS in tools/tpu_isa.py.  Two clock cycles per simple instruction.
`timescale 1ns/1ps
module tpu_core #(
    parameter PROG_HEX = "rtl/tpu_prog.hex",
    parameter TAG_HEX  = "rtl/tag36h11.hex"
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,            // pulse: run the program once
    output reg         busy,
    output reg         done,             // pulse
    // configuration
    input  wire [31:0] cfg_frame_id,
    input  wire [5:0]  cfg_maxham,
    input  wire [7:0]  cand_count,
    input  wire [7:0]  cfg_minside,
    // candidate RAM (1-cycle read latency)
    output wire [9:0]  cand_raddr,
    input  wire [31:0] cand_rdata,
    // result RAM write port
    output reg         res_we,
    output reg  [8:0]  res_waddr,
    output reg  [31:0] res_wdata,
    // binary frame read port: 40 words per row, bit x%32 of word y*40+x/32 ; 1-cycle read latency
    output wire [15:0] fb_addr,
    input  wire [31:0] fb_data,
    output reg  [31:0] cycle_count
);
    reg [31:0] rom [0:2047];
    reg [35:0] trom [0:586];
    reg [31:0] smem [0:1023];
    reg [31:0] rf [0:31];
    initial begin
        $readmemh(PROG_HEX, rom);
        $readmemh(TAG_HEX, trom);
    end

    localparam [5:0]
        NOP=0, ADD=1, SUB=2, AND=3, OR=4, XOR=5, SLL=6, SRL=7, SRA=8, MIN=9, MAX=10, ABS=11, MUL=12, MULS=13,
        DIVQ=14, ADDI=15, LDI=16, LUI=17, ORI=18, SLLI=19, SRAI=20, SRLI=21, ANDI=22, LD=23, ST=24, CRD=25,
        TWR=26, PIX=27, BEQ=28, BNE=29, BLT=30, BGE=31, JMP=32, JAL=33, JR=34, TAGMATCH=35, CNT=36, CFG=37, HALT=38;

    localparam [4:0] S_IDLE=0, S_FETCH=1, S_EXEC=2, S_MUL=3, S_DIV=4, S_MEMW=5, S_PIXW=6, S_TAG=7, S_HALT=8, S_TAGF=9, S_RD=10, S_PIXA=11, S_TAGP=12, S_FD=13, S_DIVW=14, S_PIXB=15, S_MEMW2=16;
    reg [4:0]  st;
    reg [15:0] pc;
    reg [31:0] ir;
    reg [31:0] rom_q;
    reg [31:0] smem_q;
    reg [31:0] smem_r, cand_r, fb_r;       // registered memory outputs (BRAM clock-to-out kept off the datapath)

    wire [5:0]  op   = ir[31:26];
    wire [4:0]  rd   = ir[25:21];
    wire [4:0]  ra   = ir[20:16];
    wire [4:0]  rb   = ir[15:11];
    wire [10:0] imm11 = ir[10:0];
    wire [15:0] imm16 = ir[15:0];
    wire signed [31:0] simm16 = {{16{ir[15]}}, ir[15:0]};
    reg  signed [31:0] opA, opB, opD;            // operands latched in S_RD (register-file mux off the critical path)
    wire signed [31:0] A  = opA;
    wire signed [31:0] B  = opB;
    wire signed [31:0] D  = opD;

    wire [31:0] ea = A + simm16;
    assign cand_raddr = ea[9:0];

    // pixel addressing
    wire pix_in = (A >= 0) && (A < 1280) && (B >= 0) && (B < 800);
    wire [15:0] pix_word = ({6'd0, B[9:0]} << 5) + ({6'd0, B[9:0]} << 3) + {10'd0, A[10:5]};      // y*40 + x/32
    reg  [15:0] fb_addr_r;
    assign fb_addr = fb_addr_r;
    reg [4:0] pix_bit_sel;
    reg       pix_in_r;

    reg        wb_en;
    reg [31:0] wb_val;
    reg [15:0] npc;

    reg signed [63:0] mprod;
    reg [4:0]  msh;
    reg [4:0]  wd;
    reg [47:0] dnum;  reg [32:0] drem; reg [31:0] dden; reg [47:0] dq; reg [5:0] dcnt; reg dneg;
    reg [32:0] r2d; reg [47:0] q2d;

    reg [35:0] mr0, mr1, mr2, mr3;
    reg [9:0]  mi;
    reg [5:0]  best_h; reg [9:0] best_i; reg [1:0] best_k;

    function [35:0] rot6; input [35:0] c;
        integer r, k;
        begin
            for (r = 0; r < 6; r = r + 1)
                for (k = 0; k < 6; k = k + 1)
                    rot6[35 - (6*r + k)] = c[35 - (6*(5-k) + r)];
        end
    endfunction
    function [5:0] pop36; input [35:0] v;
        integer j;
        begin pop36 = 0; for (j = 0; j < 36; j = j + 1) pop36 = pop36 + v[j]; end
    endfunction

    wire [35:0] trom_q = trom[mi];
    reg  [35:0] trom_r, trom_r2; reg [9:0] mi_a, mi_b, mi_c, tcnt;   // trom_r is absorbed into the block RAM output register; trom_r2 is a real FF
    wire [5:0] h0 = pop36(trom_r2 ^ mr0), h1 = pop36(trom_r2 ^ mr1), h2 = pop36(trom_r2 ^ mr2), h3 = pop36(trom_r2 ^ mr3);
    reg [5:0] h0r, h1r, h2r, h3r;
    reg [5:0] hmin; reg [1:0] kmin;
    always @* begin
        hmin = h0r; kmin = 2'd0;
        if (h1r < hmin) begin hmin = h1r; kmin = 2'd1; end
        if (h2r < hmin) begin hmin = h2r; kmin = 2'd2; end
        if (h3r < hmin) begin hmin = h3r; kmin = 2'd3; end
    end

    reg wbr_en = 0; reg [4:0] wbr_rd; reg [1:0] wbr_cls, wcls;
    reg [31:0] r_arith, r_logic, r_shift, r_misc;
    // per-class ALU results (registered in S_EXEC, selected one cycle later): one shared adder, no 25-way mux in front of the register file
    wire        isSub = (op == SUB), isAdd = (op == ADD);
    wire [31:0] addb  = isAdd ? B : (isSub ? ~B : simm16);
    wire [31:0] arith_v = A + addb + (isSub ? 32'd1 : 32'd0);
    wire [31:0] logic_v = (op == AND) ? (A & B) : (op == OR) ? (A | B) : (op == XOR) ? (A ^ B) : (op == ORI) ? (A | {16'd0, imm16}) : (A & {16'd0, imm16});
    wire [4:0]  shamt   = (op == SLL || op == SRL || op == SRA) ? B[4:0] : imm16[4:0];
    wire [31:0] shift_v = (op == SLL || op == SLLI) ? (A << shamt) : (op == SRL || op == SRLI) ? (A >> shamt) : (A >>> shamt);
    reg  [31:0] misc_v;
    always @* begin
        case (op)
            MIN: misc_v = (A < B) ? A : B;
            MAX: misc_v = (A > B) ? A : B;
            ABS: misc_v = (A < 0) ? -A : A;
            LDI: misc_v = simm16;
            LUI: misc_v = {imm16, 16'd0};
            JAL: misc_v = {16'd0, pc + 16'd1};
            CNT: misc_v = {24'd0, cand_count};
            default: case (imm16[1:0]) 2'd0: misc_v = cfg_frame_id; 2'd1: misc_v = {26'd0, cfg_maxham}; 2'd2: misc_v = {24'd0, cand_count}; default: misc_v = {24'd0, cfg_minside}; endcase
        endcase
    end
    integer i;
    always @(posedge clk) begin
        res_we <= 0; done <= 0;
        wbr_en <= 0;
        if (wbr_en) rf[wbr_rd] <= (wbr_cls == 2'd0) ? r_arith : (wbr_cls == 2'd1) ? r_logic : (wbr_cls == 2'd2) ? r_shift : r_misc;
        smem_q <= smem[ea[9:0]];
        smem_r <= smem_q; cand_r <= cand_rdata; fb_r <= fb_data;
        if (rst) begin
            st <= S_IDLE; busy <= 0; pc <= 0; cycle_count <= 0;
            for (i = 0; i < 32; i = i + 1) rf[i] <= 0;
        end else begin
            if (busy) cycle_count <= cycle_count + 1;
            case (st)
                S_IDLE: if (start) begin st <= S_FETCH; pc <= 0; busy <= 1; cycle_count <= 0; end
                S_FETCH: begin rom_q <= rom[pc[10:0]]; st <= S_FD; end      // block RAM read
                S_FD:    begin ir <= rom_q; st <= S_RD; end                    // BRAM output delay kept out of the decode path
                S_RD: begin
                    opA <= (ra == 0) ? 32'sd0 : rf[ra]; opB <= (rb == 0) ? 32'sd0 : rf[rb]; opD <= (rd == 0) ? 32'sd0 : rf[rd];
                    st <= S_EXEC;
                end
                S_EXEC: begin
                    wb_en = 0; wb_val = 0; wcls = 2'd0; npc = pc + 1; st <= S_FETCH;
                    case (op)
                        NOP: ;
                        ADD: begin wb_en = 1; wcls = 2'd0; end
                        SUB: begin wb_en = 1; wcls = 2'd0; end
                        AND: begin wb_en = 1; wcls = 2'd1; end
                        OR:  begin wb_en = 1; wcls = 2'd1; end
                        XOR: begin wb_en = 1; wcls = 2'd1; end
                        SLL: begin wb_en = 1; wcls = 2'd2; end
                        SRL: begin wb_en = 1; wcls = 2'd2; end
                        SRA: begin wb_en = 1; wcls = 2'd2; end
                        MIN: begin wb_en = 1; wcls = 2'd3; end
                        MAX: begin wb_en = 1; wcls = 2'd3; end
                        ABS: begin wb_en = 1; wcls = 2'd3; end
                        MUL, MULS: begin mprod <= A * B; msh <= (op == MUL) ? 5'd0 : imm11[4:0]; wd <= rd; st <= S_MUL; end
                        DIVQ: begin
                            wd <= rd;
                            if (B == 0) begin
                                if (rd != 0) rf[rd] <= (A >= 0) ? 32'h7FFFFFFF : 32'h80000001;
                            end else begin
                                dnum <= {((A < 0) ? -A : A), 16'd0}; dden <= (B < 0) ? -B : B;
                                drem <= 0; dq <= 0; dcnt <= 48; dneg <= (A < 0) != (B < 0); st <= S_DIV;
                            end
                        end
                        ADDI: begin wb_en = 1; wcls = 2'd0; end
                        LDI:  begin wb_en = 1; wcls = 2'd3; end
                        LUI:  begin wb_en = 1; wcls = 2'd3; end
                        ORI:  begin wb_en = 1; wcls = 2'd1; end
                        SLLI: begin wb_en = 1; wcls = 2'd2; end
                        SRAI: begin wb_en = 1; wcls = 2'd2; end
                        SRLI: begin wb_en = 1; wcls = 2'd2; end
                        ANDI: begin wb_en = 1; wcls = 2'd1; end
                        LD:   begin wd <= rd; st <= S_MEMW; end
                        ST:   begin smem[ea[9:0]] <= D; end
                        CRD:  begin wd <= rd; st <= S_MEMW; end
                        TWR:  begin res_we <= 1; res_waddr <= ea[8:0]; res_wdata <= D; end
                        PIX:  begin wd <= rd; pix_bit_sel <= A[4:0]; fb_addr_r <= pix_word; pix_in_r <= pix_in; st <= S_PIXA; end
                        BEQ:  if (A == B) npc = {5'd0, imm11};
                        BNE:  if (A != B) npc = {5'd0, imm11};
                        BLT:  if (A <  B) npc = {5'd0, imm11};
                        BGE:  if (A >= B) npc = {5'd0, imm11};
                        JMP:  npc = imm16;
                        JAL:  begin wb_en = 1; wcls = 2'd3; npc = imm16; end
                        JR:   npc = A[15:0];
                        TAGMATCH: begin
                            wd <= rd;
                            mr0 <= {B[3:0], A}; mr1 <= rot6({B[3:0], A}); mr2 <= rot6(rot6({B[3:0], A}));
                            mr3 <= rot6(rot6(rot6({B[3:0], A}))); mi <= 0; tcnt <= 0; best_h <= 6'd63; best_i <= 0; best_k <= 0;
                            st <= S_TAG;
                        end
                        CNT:  begin wb_en = 1; wcls = 2'd3; end
                        CFG:  begin wb_en = 1; wcls = 2'd3; end
                        HALT: begin st <= S_HALT; busy <= 0; done <= 1; npc = pc; end
                        default: ;
                    endcase
                    wbr_en <= (wb_en && rd != 0); wbr_rd <= rd; wbr_cls <= wcls;      // written during the next S_FETCH
                    r_arith <= arith_v; r_logic <= logic_v; r_shift <= shift_v; r_misc <= misc_v;
                    pc <= npc;
                end
                S_MUL: begin
                    if (wd != 0) rf[wd] <= (mprod >>> msh);
                    st <= S_FETCH;
                end
                S_DIV: begin
                    r2d = {drem[31:0], dnum[47]};
                    q2d = {dq[46:0], 1'b0};
                    if (r2d >= {1'b0, dden}) begin r2d = r2d - {1'b0, dden}; q2d[0] = 1'b1; end
                    drem <= r2d; dq <= q2d; dnum <= {dnum[46:0], 1'b0}; dcnt <= dcnt - 1;
                    if (dcnt == 1) st <= S_DIVW;                  // result registered in dq, written next cycle
                end
                S_DIVW: begin
                    if (wd != 0) rf[wd] <= dneg ? -dq[31:0] : dq[31:0];
                    st <= S_FETCH;
                end
                S_MEMW: st <= S_MEMW2;                       // BRAM output registered, then selected
                S_MEMW2: begin
                    if (wd != 0) rf[wd] <= (op == LD) ? smem_r : cand_r;
                    st <= S_FETCH;
                end
                S_PIXA: begin                                // block RAM samples fb_addr this cycle
                    if (pix_in_r) st <= S_PIXW;
                    else begin if (wd != 0) rf[wd] <= 32'd0; st <= S_FETCH; end
                end
                S_PIXW: st <= S_PIXB;                        // BRAM output -> fb_r register
                S_PIXB: begin
                    if (wd != 0) rf[wd] <= {31'd0, fb_r[pix_bit_sel]};
                    st <= S_FETCH;
                end
                S_TAG: begin
                    // pipeline: ROM word (t) -> trom_r (t+1) -> trom_r2 (t+2) -> popcounts h*r (t+3) -> best update; tcnt = issue/drain counter
                    trom_r <= trom_q; trom_r2 <= trom_r;
                    h0r <= h0; h1r <= h1; h2r <= h2; h3r <= h3;
                    mi_a <= mi; mi_b <= mi_a; mi_c <= mi_b;
                    if (tcnt >= 10'd3 && hmin < best_h) begin best_h <= hmin; best_i <= mi_c; best_k <= kmin; end
                    if (tcnt == 10'd589) st <= S_TAGF;
                    else begin tcnt <= tcnt + 1; if (mi != 586) mi <= mi + 1; end
                end
                S_TAGF: begin
                    if (wd != 0) rf[wd] <= (best_h <= cfg_maxham) ? {14'd0, best_h, best_k, best_i} : 32'hFFFFFFFF;
                    st <= S_FETCH;
                end
                S_HALT: if (start) begin st <= S_FETCH; pc <= 0; busy <= 1; cycle_count <= 0; end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
