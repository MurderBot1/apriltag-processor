"""The program baked into the TPU's instruction ROM.  For every candidate component handed over by the
CCL unit it: picks a coarse quad from the 8 directional extremes, refines each side by fitting a line to
sub-sampled edge positions found in the binary frame, intersects the lines for sub-pixel corners, builds the
tag homography, samples the 6x6 data cells, matches them against the baked tag36h11 ROM (4 rotations) and
writes a result record.   Q16 = 16 fractional bits unless stated otherwise.

Scratch map: PTS 0..15  CC 16..23  RC 24..31  LN 32..47  CINFO 48..55  HOM 56..63
Result RAM : word 0 = tag count, record i at 16+16*i :
   w0 = 0x80000000 | ham<<12 | rot<<10 | id    w1..w8 = corners TL,TR,BR,BL (x,y) Q16
   w9 = candidate label   w10 = component area   w11 = frame id   w12 = quad area (px^2)
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from tpu_isa import Asm

PTS, CC, RC, LN, CINFO, HOM = 0, 16, 24, 32, 48, 56
MIN_QUAD_AREA = 80


def build():
    a = Asm()
    L = a.label
    # ======================================================================= main
    # r20 count, r21 ci, r22 tags written, r23 record base word, r24 tmp
    a.LDI('r22', 0)
    a.CNT('r20')
    a.LDI('r21', 0)
    L('main_loop')
    a.BGE('r21', 'r20', 'finish')
    a.SLLI('r23', 'r21', 4)
    a.JAL('r31', 'load_cand')
    a.JAL('r31', 'coarse')
    a.BEQ('r1', 'r0', 'next_cand')
    # refinement pass 1: K from candidate size
    a.LDI('r1', CC)
    a.LD('r2', 'r0', CINFO + 2)
    a.LD('r3', 'r0', CINFO + 3)
    a.MAX('r2', 'r2', 'r3')
    a.SRAI('r2', 'r2', 4)
    a.LDI('r3', 3); a.MAX('r2', 'r2', 'r3')
    a.LDI('r3', 8); a.MIN('r2', 'r2', 'r3')
    a.JAL('r31', 'refine')
    a.BEQ('r1', 'r0', 'next_cand')
    # pass 2: K = 3 around the refined corners
    a.LDI('r1', RC); a.LDI('r2', 3)
    a.JAL('r31', 'refine')
    a.BEQ('r1', 'r0', 'next_cand')
    a.JAL('r31', 'decode')               # r1 = match word or -1
    a.LDI('r3', -1)
    a.BEQ('r1', 'r3', 'next_cand')
    a.JAL('r31', 'emit')
    a.ADDI('r22', 'r22', 1)
    a.LDI('r3', 31)
    a.BGE('r22', 'r3', 'finish')
    L('next_cand')
    a.ADDI('r21', 'r21', 1)
    a.JMP('main_loop')
    L('finish')
    a.TWR('r22', 'r0', 0)
    a.HALT()

    # ======================================================================= load_cand
    # in: r23 = record base (word index).  out: PTS, CINFO.  clobbers r1..r12
    L('load_cand')
    a.CRD('r1', 'r23', 0)  ; a.ST('r1', 'r0', CINFO + 0)            # area
    a.CRD('r1', 'r23', 9)  ; a.ST('r1', 'r0', CINFO + 1)            # label
    a.CRD('r1', 'r23', 10); a.CRD('r2', 'r23', 11)
    a.LUI('r3', 0); a.ORI('r3', 'r3', 0xFFFF)   # r3 = 0xFFFF
    a.AND('r4', 'r1', 'r3'); a.SRLI('r5', 'r1', 16)                  # x0, x1
    a.SUB('r5', 'r5', 'r4'); a.ADDI('r5', 'r5', 1); a.ST('r5', 'r0', CINFO + 2)
    a.AND('r4', 'r2', 'r3'); a.SRLI('r5', 'r2', 16)                  # y0, y1
    a.SUB('r5', 'r5', 'r4'); a.ADDI('r5', 'r5', 1); a.ST('r5', 'r0', CINFO + 3)
    # per direction: r6 = score (sign-extended 16 bit), r7 = aux (11 bit)
    for k in range(8):
        a.CRD('r1', 'r23', 1 + k)
        a.SLLI('r6', 'r1', 16); a.SRAI('r6', 'r6', 16)
        a.SRLI('r7', 'r1', 16); a.ANDI('r7', 'r7', 0x7FF)
        if k == 0:   x, y = 'r6', 'r7'
        elif k == 1: a.SUB('r8', 'r0', 'r6'); x, y = 'r8', 'r7'
        elif k == 2: x, y = 'r7', 'r6'
        elif k == 3: a.SUB('r8', 'r0', 'r6'); x, y = 'r7', 'r8'
        elif k == 4: a.SUB('r8', 'r6', 'r7'); x, y = 'r7', 'r8'
        elif k == 5: a.SUB('r8', 'r0', 'r6'); a.SUB('r8', 'r8', 'r7'); x, y = 'r7', 'r8'
        elif k == 6: a.SUB('r8', 'r7', 'r6'); x, y = 'r7', 'r8'
        else:        a.ADD('r8', 'r6', 'r7'); x, y = 'r7', 'r8'
        a.ST(x, 'r0', PTS + 2 * k); a.ST(y, 'r0', PTS + 2 * k + 1)
    a.JR('r31')

    # ======================================================================= coarse
    # clockwise order E,SE,S,SW,W,NW,N,NE = dirs 0,4,2,7,1,5,3,6 ; set A = E,S,W,N ; set B = SE,SW,NW,NE
    # out: CC (Q16) , r1 = ok
    L('coarse')
    setA, setB = (0, 2, 1, 3), (4, 7, 5, 6)

    def shoelace(res, ks):
        a.LDI(res, 0)
        for i in range(4):
            k0, k1 = ks[i], ks[(i + 1) & 3]
            a.LD('r3', 'r0', PTS + 2 * k0); a.LD('r4', 'r0', PTS + 2 * k0 + 1)
            a.LD('r5', 'r0', PTS + 2 * k1); a.LD('r6', 'r0', PTS + 2 * k1 + 1)
            a.MUL('r7', 'r3', 'r6'); a.MUL('r8', 'r5', 'r4'); a.SUB('r7', 'r7', 'r8')
            a.ADD(res, res, 'r7')
    shoelace('r10', setA)
    shoelace('r11', setB)
    a.BGE('r10', 'r11', 'coarse_useA')
    a.LDI('r12', 1)                       # use B
    a.ADD('r10', 'r11', 'r0')
    a.JMP('coarse_sel')
    L('coarse_useA')
    a.LDI('r12', 0)
    L('coarse_sel')
    # r10 = 2*area (signed, positive for a proper clockwise quad)
    a.SRAI('r13', 'r10', 1)               # quad area
    a.LDI('r1', 0)
    a.LDI('r3', MIN_QUAD_AREA)
    a.BLT('r13', 'r3', 'coarse_ret')
    a.LD('r4', 'r0', CINFO + 0)           # component area
    a.SLLI('r5', 'r4', 2)
    a.BLT('r5', 'r13', 'coarse_ret')      # comp area < 25 % of quad area
    # comp area must be <= 1.1 * quad area  ->  10*comp <= 11*quad
    a.LDI('r6', 10); a.MUL('r7', 'r4', 'r6'); a.LDI('r6', 11); a.MUL('r8', 'r13', 'r6')
    a.BLT('r8', 'r7', 'coarse_ret')
    a.ST('r13', 'r0', CINFO + 4)
    a.BNE('r12', 'r0', 'coarse_copyB')
    ks = setA
    for i, k in enumerate(ks):
        a.LD('r3', 'r0', PTS + 2 * k); a.SLLI('r3', 'r3', 16); a.ST('r3', 'r0', CC + 2 * i)
        a.LD('r3', 'r0', PTS + 2 * k + 1); a.SLLI('r3', 'r3', 16); a.ST('r3', 'r0', CC + 2 * i + 1)
    a.JMP('coarse_ok')
    L('coarse_copyB')
    ks = setB
    for i, k in enumerate(ks):
        a.LD('r3', 'r0', PTS + 2 * k); a.SLLI('r3', 'r3', 16); a.ST('r3', 'r0', CC + 2 * i)
        a.LD('r3', 'r0', PTS + 2 * k + 1); a.SLLI('r3', 'r3', 16); a.ST('r3', 'r0', CC + 2 * i + 1)
    L('coarse_ok')
    a.LDI('r1', 1)
    L('coarse_ret')
    a.JR('r31')

    # ======================================================================= refine
    # in: r1 = source corners base (Q16 x,y pairs, clockwise), r2 = K.  out: RC = intersections, r1 = ok
    # live: r29 src, r28 K, r27 side, r15 aS, r16 aE(unused), r17 cS, r18 dAlong, r19 m, r20.. (main's r20..r23 are
    # saved on the stack-less scratch because refine clobbers them)
    L('refine')
    a.ST('r20', 'r0', 90); a.ST('r21', 'r0', 91); a.ST('r22', 'r0', 92); a.ST('r23', 'r0', 93)
    a.ADD('r29', 'r1', 'r0'); a.ADD('r28', 'r2', 'r0'); a.LDI('r27', 0)
    L('rf_side')
    a.LDI('r26', 4)
    a.BGE('r27', 'r26', 'rf_intersect')
    a.SLLI('r5', 'r27', 1); a.ADD('r5', 'r5', 'r29')
    a.LD('r6', 'r5', 0); a.LD('r7', 'r5', 1)                      # xa, ya
    a.ADDI('r8', 'r27', 1); a.ANDI('r8', 'r8', 3); a.SLLI('r8', 'r8', 1); a.ADD('r8', 'r8', 'r29')
    a.LD('r9', 'r8', 0); a.LD('r10', 'r8', 1)                      # xb, yb
    a.SUB('r11', 'r9', 'r6'); a.SUB('r12', 'r10', 'r7')            # dx, dy
    a.ABS('r13', 'r11'); a.ABS('r14', 'r12')
    a.BGE('r13', 'r14', 'rf_h')
    # vertical-ish edge: along = y, cross = x
    a.ADD('r15', 'r7', 'r0'); a.ADD('r16', 'r10', 'r0'); a.ADD('r17', 'r6', 'r0')
    a.ADD('r18', 'r12', 'r0'); a.ADD('r19', 'r11', 'r0')
    a.LDI('r24', 1)                                               # vflag
    a.LDI('r25', -1); a.BGE('r0', 'r12', 'rf_common')             # so = +1 if dy>0 else -1
    a.LDI('r25', 1); a.JMP('rf_common')
    L('rf_h')
    a.ADD('r15', 'r6', 'r0'); a.ADD('r16', 'r9', 'r0'); a.ADD('r17', 'r7', 'r0')
    a.ADD('r18', 'r11', 'r0'); a.ADD('r19', 'r12', 'r0')
    a.LDI('r24', 0)
    a.LDI('r25', 1); a.BLT('r11', 'r0', 'rf_common')              # so = +1 if dx<0 else -1
    a.LDI('r25', -1)
    L('rf_common')
    # r15 aS, r16 aE, r17 cS, r18 dAlong, r19 dCross, r24 vflag, r25 so
    a.BEQ('r18', 'r0', 'rf_fail')
    a.DIVQ('r19', 'r19', 'r18')                                   # r19 = m (Q16)
    a.ABS('r1', 'r19'); a.LUI('r2', 2); a.BGE('r1', 'r2', 'rf_fail')     # |m| >= 2.0 -> degenerate
    a.ADD('r1', 'r15', 'r16'); a.SRAI('r1', 'r1', 1); a.LUI('r2', 0); a.ORI('r2', 'r2', 0x8000)
    a.ADD('r1', 'r1', 'r2'); a.SRAI('r16', 'r1', 16)              # r16 := tm (integer mid along coordinate)
    # accumulators: r1 n, r2 St, r3 Stt, r4 Sd, r5 Std ; j in r6
    a.LDI('r1', 0); a.LDI('r2', 0); a.LDI('r3', 0); a.LDI('r4', 0); a.LDI('r5', 0); a.LDI('r6', 0)
    L('rf_j')
    a.LDI('r7', 16); a.BGE('r6', 'r7', 'rf_fit')
    # u = 6554 + (2j+1)*1638
    a.SLLI('r7', 'r6', 1); a.ADDI('r7', 'r7', 1); a.LDI('r8', 1638); a.MUL('r7', 'r7', 'r8'); a.ADDI('r7', 'r7', 6554)
    a.MULS('r7', 'r7', 'r18', 16); a.ADD('r7', 'r7', 'r15')        # tq (Q16)
    a.LUI('r8', 0); a.ORI('r8', 'r8', 0x8000); a.ADD('r7', 'r7', 'r8'); a.SRAI('r7', 'r7', 16)   # r7 = t
    a.SLLI('r8', 'r7', 16); a.SUB('r8', 'r8', 'r15'); a.MULS('r8', 'r8', 'r19', 16); a.ADD('r8', 'r8', 'r17')   # r8 = yc Q16
    a.LUI('r9', 0); a.ORI('r9', 'r9', 0x8000); a.ADD('r9', 'r9', 'r8'); a.SRAI('r9', 'r9', 16)   # round(yc)
    a.MUL('r10', 'r25', 'r28'); a.ADD('r9', 'r9', 'r10')           # c0 = round(yc) + so*K
    a.LDI('r10', 0)                                                # i
    a.SLLI('r11', 'r28', 1); a.ADDI('r11', 'r11', 1)               # 2K+1
    L('rf_scan')
    a.BNE('r24', 'r0', 'rf_pixv')
    a.PIX('r12', 'r7', 'r9'); a.JMP('rf_pixd')
    L('rf_pixv')
    a.PIX('r12', 'r9', 'r7')
    L('rf_pixd')
    a.BNE('r12', 'r0', 'rf_found')
    a.ADDI('r10', 'r10', 1); a.SUB('r9', 'r9', 'r25')
    a.BLT('r10', 'r11', 'rf_scan')
    a.JMP('rf_jnext')
    L('rf_found')
    a.BEQ('r10', 'r0', 'rf_jnext')                                 # black at the outermost pixel: invalid
    a.SLLI('r12', 'r9', 4); a.SLLI('r13', 'r25', 3); a.ADD('r12', 'r12', 'r13')    # edge Q4
    a.SRAI('r13', 'r8', 12); a.SUB('r12', 'r12', 'r13')            # d = edge - chord (Q4)
    a.SUB('r13', 'r7', 'r16')                                      # tc
    a.ADDI('r1', 'r1', 1); a.ADD('r2', 'r2', 'r13'); a.MUL('r14', 'r13', 'r13'); a.ADD('r3', 'r3', 'r14')
    a.ADD('r4', 'r4', 'r12'); a.MUL('r14', 'r13', 'r12'); a.ADD('r5', 'r5', 'r14')
    L('rf_jnext')
    a.ADDI('r6', 'r6', 1); a.JMP('rf_j')
    L('rf_fit')
    a.LDI('r7', 6); a.BLT('r1', 'r7', 'rf_fail')
    a.MUL('r7', 'r1', 'r3'); a.MUL('r8', 'r2', 'r2'); a.SUB('r7', 'r7', 'r8')       # den
    a.BGE('r0', 'r7', 'rf_fail')
    a.MUL('r8', 'r1', 'r5'); a.MUL('r9', 'r2', 'r4'); a.SUB('r8', 'r8', 'r9')       # num
    a.DIVQ('r8', 'r8', 'r7'); a.SRAI('r8', 'r8', 4)                                  # r8 = a (Q16 slope)
    a.MULS('r9', 'r8', 'r2', 12)                                                     # 16*a*St (Q4)
    a.SUB('r9', 'r4', 'r9'); a.DIVQ('r9', 'r9', 'r1'); a.SRAI('r9', 'r9', 4)         # r9 = b (Q16)
    a.ADD('r10', 'r19', 'r8')                                                        # M = m + a
    a.MULS('r11', 'r19', 'r15', 16); a.SUB('r11', 'r17', 'r11')                      # cS - m*aS
    a.MUL('r12', 'r8', 'r16'); a.SUB('r11', 'r11', 'r12'); a.ADD('r11', 'r11', 'r9') # Cc
    a.SLLI('r12', 'r27', 2); a.ADDI('r12', 'r12', LN)                                # line slot address
    a.LUI('r13', 1)                                                                  # 1.0 in Q16
    a.SUB('r14', 'r0', 'r10')                                                        # -M
    a.BNE('r24', 'r0', 'rf_storev')
    a.ST('r14', 'r12', 0); a.ST('r13', 'r12', 1); a.ST('r11', 'r12', 2); a.JMP('rf_stored')   # -M x + y = Cc
    L('rf_storev')
    a.ST('r13', 'r12', 0); a.ST('r14', 'r12', 1); a.ST('r11', 'r12', 2)                     # x - M y = Cc
    L('rf_stored')
    a.ADDI('r27', 'r27', 1); a.JMP('rf_side')

    L('rf_intersect')
    a.LDI('r27', 0)
    L('rf_ix')
    a.LDI('r26', 4); a.BGE('r27', 'r26', 'rf_ok')
    a.ADDI('r5', 'r27', 3); a.ANDI('r5', 'r5', 3); a.SLLI('r5', 'r5', 2); a.ADDI('r5', 'r5', LN)   # line (i-1)
    a.SLLI('r6', 'r27', 2); a.ADDI('r6', 'r6', LN)                                                  # line i
    a.LD('r7', 'r5', 0); a.LD('r8', 'r5', 1); a.LD('r9', 'r5', 2)                                   # A1 B1 C1
    a.LD('r10', 'r6', 0); a.LD('r11', 'r6', 1); a.LD('r12', 'r6', 2)                                # A2 B2 C2
    a.MULS('r13', 'r7', 'r11', 16); a.MULS('r14', 'r10', 'r8', 16); a.SUB('r13', 'r13', 'r14')       # det
    a.ABS('r14', 'r13'); a.LDI('r15', 3277); a.BLT('r14', 'r15', 'rf_fail')
    a.MULS('r14', 'r9', 'r11', 16); a.MULS('r15', 'r12', 'r8', 16); a.SUB('r14', 'r14', 'r15')       # xn
    a.MULS('r16', 'r7', 'r12', 16); a.MULS('r17', 'r10', 'r9', 16); a.SUB('r16', 'r16', 'r17')       # yn
    a.DIVQ('r14', 'r14', 'r13'); a.DIVQ('r16', 'r16', 'r13')
    a.SLLI('r18', 'r27', 1)
    a.ST('r14', 'r18', RC); a.ST('r16', 'r18', RC + 1)
    a.ADDI('r27', 'r27', 1); a.JMP('rf_ix')
    L('rf_ok')
    a.LDI('r1', 1); a.JMP('rf_ret')
    L('rf_fail')
    a.LDI('r1', 0)
    L('rf_ret')
    a.LD('r20', 'r0', 90); a.LD('r21', 'r0', 91); a.LD('r22', 'r0', 92); a.LD('r23', 'r0', 93)
    a.JR('r31')

    # ======================================================================= decode
    # in: RC.  out: r1 = match word (id | rot<<10 | ham<<12) or -1.  HOM = a,b,c,d,e,f,g,h (Q16)
    L('decode')
    a.ST('r20', 'r0', 90); a.ST('r21', 'r0', 91); a.ST('r22', 'r0', 92); a.ST('r23', 'r0', 93)
    a.LD('r1', 'r0', RC + 0); a.LD('r2', 'r0', RC + 1)      # x0 y0
    a.LD('r3', 'r0', RC + 2); a.LD('r4', 'r0', RC + 3)      # x1 y1
    a.LD('r5', 'r0', RC + 4); a.LD('r6', 'r0', RC + 5)      # x2 y2
    a.LD('r7', 'r0', RC + 6); a.LD('r8', 'r0', RC + 7)      # x3 y3
    a.SUB('r9', 'r3', 'r5'); a.SUB('r10', 'r7', 'r5')                                   # dx1 dx2
    a.SUB('r11', 'r1', 'r3'); a.ADD('r11', 'r11', 'r5'); a.SUB('r11', 'r11', 'r7')      # dx3
    a.SUB('r12', 'r4', 'r6'); a.SUB('r13', 'r8', 'r6')                                  # dy1 dy2
    a.SUB('r14', 'r2', 'r4'); a.ADD('r14', 'r14', 'r6'); a.SUB('r14', 'r14', 'r8')      # dy3
    a.MULS('r15', 'r9', 'r13', 24); a.MULS('r16', 'r10', 'r12', 24); a.SUB('r15', 'r15', 'r16')   # D (Q8)
    a.ABS('r16', 'r15'); a.LDI('r17', 4096); a.BLT('r16', 'r17', 'dec_fail')
    a.MULS('r16', 'r11', 'r13', 24); a.MULS('r17', 'r10', 'r14', 24); a.SUB('r16', 'r16', 'r17')  # ng
    a.MULS('r17', 'r9', 'r14', 24); a.MULS('r18', 'r11', 'r12', 24); a.SUB('r17', 'r17', 'r18')   # nh
    a.DIVQ('r16', 'r16', 'r15'); a.DIVQ('r17', 'r17', 'r15')                            # g h
    a.MULS('r18', 'r16', 'r3', 16); a.SUB('r19', 'r3', 'r1'); a.ADD('r19', 'r19', 'r18')          # a
    a.MULS('r18', 'r17', 'r7', 16); a.SUB('r20', 'r7', 'r1'); a.ADD('r20', 'r20', 'r18')          # b
    a.MULS('r18', 'r16', 'r4', 16); a.SUB('r21', 'r4', 'r2'); a.ADD('r21', 'r21', 'r18')          # d
    a.MULS('r18', 'r17', 'r8', 16); a.SUB('r22', 'r8', 'r2'); a.ADD('r22', 'r22', 'r18')          # e
    # keep: a=r19 b=r20 c=r1 d=r21 e=r22 f=r2 g=r16 h=r17
    a.LDI('r23', 0)      # code lo
    a.LDI('r24', 0)      # code hi
    a.LDI('r25', 0)      # row
    L('dec_row')
    a.LDI('r26', 6); a.BGE('r25', 'r26', 'dec_match')
    a.SLLI('r5', 'r25', 1); a.ADDI('r5', 'r5', 3); a.SLLI('r5', 'r5', 12)     # v = (2r+3)/16 in Q16
    a.LDI('r26', 0)      # col
    L('dec_col')
    a.LDI('r6', 6); a.BGE('r26', 'r6', 'dec_rownext')
    a.SLLI('r6', 'r26', 1); a.ADDI('r6', 'r6', 3); a.SLLI('r6', 'r6', 12)     # u
    a.MULS('r7', 'r16', 'r6', 16); a.MULS('r8', 'r17', 'r5', 16); a.ADD('r7', 'r7', 'r8')
    a.LUI('r8', 1); a.ADD('r7', 'r7', 'r8')                                   # w = 1 + g u + h v
    a.MULS('r8', 'r19', 'r6', 16); a.MULS('r9', 'r20', 'r5', 16); a.ADD('r8', 'r8', 'r9'); a.ADD('r8', 'r8', 'r1')   # xn
    a.MULS('r9', 'r21', 'r6', 16); a.MULS('r10', 'r22', 'r5', 16); a.ADD('r9', 'r9', 'r10'); a.ADD('r9', 'r9', 'r2')  # yn
    a.DIVQ('r8', 'r8', 'r7'); a.DIVQ('r9', 'r9', 'r7')
    a.LUI('r10', 0); a.ORI('r10', 'r10', 0x8000)
    a.ADD('r8', 'r8', 'r10'); a.SRAI('r8', 'r8', 16)
    a.ADD('r9', 'r9', 'r10'); a.SRAI('r9', 'r9', 16)
    a.PIX('r10', 'r8', 'r9')                                                   # 1 = black
    a.LDI('r11', 1); a.SUB('r10', 'r11', 'r10')                                # data bit: white = 1
    a.SRLI('r11', 'r23', 31); a.SLLI('r24', 'r24', 1); a.OR('r24', 'r24', 'r11')
    a.SLLI('r23', 'r23', 1); a.OR('r23', 'r23', 'r10')
    a.ADDI('r26', 'r26', 1); a.JMP('dec_col')
    L('dec_rownext')
    a.ADDI('r25', 'r25', 1); a.JMP('dec_row')
    L('dec_match')
    a.ANDI('r24', 'r24', 15)
    a.TAGMATCH('r1', 'r23', 'r24')
    a.JMP('dec_ret')
    L('dec_fail')
    a.LDI('r1', -1)
    L('dec_ret')
    a.LD('r20', 'r0', 90); a.LD('r21', 'r0', 91); a.LD('r22', 'r0', 92); a.LD('r23', 'r0', 93)
    a.JR('r31')

    # ======================================================================= emit
    # in: r1 = match word, r22 tag index.  Rotates the corner list so corner 0 is the tag's top-left.
    L('emit')
    a.SLLI('r4', 'r22', 4); a.ADDI('r4', 'r4', 16)                 # record base
    a.LUI('r5', 0x8000); a.OR('r5', 'r5', 'r1'); a.TWR('r5', 'r4', 0)
    a.SRLI('r6', 'r1', 10); a.ANDI('r6', 'r6', 3)                  # rot
    a.LDI('r7', 0)                                                 # i
    L('em_c')
    a.LDI('r8', 4); a.BGE('r7', 'r8', 'em_done')
    a.SUB('r8', 'r7', 'r6'); a.ANDI('r8', 'r8', 3); a.SLLI('r8', 'r8', 1)      # source corner (i-rot)&3
    a.LD('r9', 'r8', RC); a.LD('r10', 'r8', RC + 1)
    a.SLLI('r11', 'r7', 1); a.ADD('r11', 'r11', 'r4')
    a.TWR('r9', 'r11', 1); a.TWR('r10', 'r11', 2)
    a.ADDI('r7', 'r7', 1); a.JMP('em_c')
    L('em_done')
    a.LD('r5', 'r0', CINFO + 1); a.TWR('r5', 'r4', 9)
    a.LD('r5', 'r0', CINFO + 0); a.TWR('r5', 'r4', 10)
    a.CFG('r5', 0); a.TWR('r5', 'r4', 11)
    a.LD('r5', 'r0', CINFO + 4); a.TWR('r5', 'r4', 12)
    a.JR('r31')
    return a


def program():
    a = build()
    return a.link(), a


if __name__ == '__main__':
    code, a = program()
    out = os.path.join(os.path.dirname(__file__), '..', 'ref', 'tpu', 'tpu_prog.hex')
    a.hexfile(out)
    print('TPU program:', len(code), 'words ->', out)
