"""TPU ("Tag Processing Unit") ISA: assembler + bit-exact instruction-set simulator.

32-bit registers r0..r31 (r0 reads as 0), 32-bit instructions:
   [31:26] op  [25:21] rd  [20:16] ra  [15:11] rb  [10:0] imm11      (R format; shift amount = imm[4:0])
   [31:26] op  [25:21] rd  [20:16] ra  [15:0]  imm16                 (I format)
   branches:  [20:16] ra [15:11] rb [10:0] absolute target
   JMP/JAL :  [15:0] absolute target

Fixed point conventions are the program's business; hardware primitives:
   MULS rd,ra,rb,sh : rd = (int64(ra)*int64(rb)) >>> sh          (arithmetic shift, low 32 bits kept)
   DIVQ rd,ra,rb    : rd = trunc((int64(ra) << 16) / rb)           (rb==0 -> +-0x7FFFFFFF), low 32 bits kept
"""
import re, numpy as np

OPS = ['NOP', 'ADD', 'SUB', 'AND', 'OR', 'XOR', 'SLL', 'SRL', 'SRA', 'MIN', 'MAX', 'ABS', 'MUL', 'MULS', 'DIVQ',
       'ADDI', 'LDI', 'LUI', 'ORI', 'SLLI', 'SRAI', 'SRLI', 'ANDI', 'LD', 'ST', 'CRD', 'TWR', 'PIX',
       'BEQ', 'BNE', 'BLT', 'BGE', 'JMP', 'JAL', 'JR', 'TAGMATCH', 'CNT', 'CFG', 'HALT']
OPC = {n: i for i, n in enumerate(OPS)}
M32 = 0xFFFFFFFF


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------- assembler
class Asm:
    def __init__(self):
        self.code, self.labels, self.fix, self.equ, self.src = [], {}, [], {}, []

    def label(self, name): self.labels[name] = len(self.code)

    def emit(self, w, note=''):
        self.code.append(w & M32); self.src.append(note)

    @staticmethod
    def reg(r):
        if isinstance(r, int): return r
        m = re.fullmatch(r'r(\d+)', r)
        assert m and int(m.group(1)) < 32, f'bad register {r}'
        return int(m.group(1))

    def R(self, op, rd=0, ra=0, rb=0, imm=0):
        self.emit((OPC[op] << 26) | (self.reg(rd) << 21) | (self.reg(ra) << 16) | (self.reg(rb) << 11) | (imm & 0x7FF), op)

    def I(self, op, rd, ra, imm):
        self.emit((OPC[op] << 26) | (self.reg(rd) << 21) | (self.reg(ra) << 16) | (imm & 0xFFFF), op)

    def B(self, op, ra, rb, target):
        self.fix.append((len(self.code), target, 11))
        self.emit((OPC[op] << 26) | (self.reg(ra) << 16) | (self.reg(rb) << 11), op)

    def J(self, op, rd, target):
        self.fix.append((len(self.code), target, 16))
        self.emit((OPC[op] << 26) | (self.reg(rd) << 21), op)

    # convenient mnemonics ------------------------------------------------
    def __getattr__(self, name):
        n = name.upper()
        if n in ('ADD', 'SUB', 'AND', 'OR', 'XOR', 'SLL', 'SRL', 'SRA', 'MIN', 'MAX', 'MUL', 'DIVQ', 'PIX', 'TAGMATCH'):
            return lambda rd, ra, rb=0: self.R(n, rd, ra, rb)
        if n == 'ABS': return lambda rd, ra: self.R('ABS', rd, ra)
        if n == 'MULS': return lambda rd, ra, rb, sh: self.R('MULS', rd, ra, rb, sh)
        if n in ('ADDI', 'ORI', 'ANDI', 'LD', 'ST', 'CRD', 'TWR'): return lambda rd, ra, imm=0: self.I(n, rd, ra, imm)
        if n in ('SLLI', 'SRAI', 'SRLI'): return lambda rd, ra, sh: self.I(n, rd, ra, sh)
        if n == 'LDI': return lambda rd, imm: self.I('LDI', rd, 0, imm)
        if n == 'LUI': return lambda rd, imm: self.I('LUI', rd, 0, imm)
        if n in ('BEQ', 'BNE', 'BLT', 'BGE'): return lambda ra, rb, t: self.B(n, ra, rb, t)
        if n == 'JMP': return lambda t: self.J('JMP', 0, t)
        if n == 'JAL': return lambda rd, t: self.J('JAL', rd, t)
        if n == 'JR': return lambda ra: self.R('JR', 0, ra)
        if n == 'CNT': return lambda rd: self.R('CNT', rd)
        if n == 'CFG': return lambda rd, idx: self.I('CFG', rd, 0, idx)
        if n == 'HALT': return lambda: self.R('HALT')
        if n == 'NOP': return lambda: self.R('NOP')
        raise AttributeError(name)

    def li(self, rd, value):
        """load any 32-bit constant"""
        v = s32(value)
        if -32768 <= v < 32768: self.LDI(rd, v)
        else:
            self.LUI(rd, (v >> 16) & 0xFFFF)
            if v & 0xFFFF: self.ORI(rd, rd, v & 0xFFFF)

    def q16(self, rd, f): self.li(rd, int(round(f * 65536)))

    def link(self):
        for pos, tgt, bits in self.fix:
            addr = self.labels[tgt] if isinstance(tgt, str) else tgt
            assert addr < (1 << bits), 'branch target out of range'
            self.code[pos] |= addr
        return self.code

    def hexfile(self, path):
        code = self.link()
        with open(path, 'w') as f:
            for w in code: f.write(f'{w:08x}\n')


# ----------------------------------------------------------------------- rotations / codes
def rot6(code):
    """rotate the 6x6 bit grid (row-major, MSB = row0/col0) by 90 degrees clockwise"""
    g = [[(code >> (35 - (6 * r + c))) & 1 for c in range(6)] for r in range(6)]
    n = [[g[5 - c][r] for c in range(6)] for r in range(6)]
    v = 0
    for r in range(6):
        for c in range(6): v = (v << 1) | n[r][c]
    return v


# ---------------------------------------------------------------------------- ISS
class Machine:
    def __init__(self, code, codes, frame_bit, cand, cfg, scratch_words=1024, res_words=512):
        self.code, self.codes, self.frame_bit, self.cand, self.cfg = code, codes, frame_bit, cand, cfg
        self.r = [0] * 32
        self.mem = [0] * scratch_words
        self.res = [0] * res_words
        self.pc = 0
        self.cycles = 0
        self.halted = False
        self.rotsets = None

    def match(self, lo, hi):
        code = ((hi & 0xF) << 32) | (lo & M32)
        rots = [code]
        for _ in range(3): rots.append(rot6(rots[-1]))
        best = (99, 0, 0)
        for i, c in enumerate(self.codes):
            for k in range(4):
                h = bin(c ^ rots[k]).count('1')
                if h < best[0]: best = (h, i, k)
        if best[0] <= self.cfg['maxham']:
            return best[2] << 10 | best[1] | (best[0] << 12) , 590
        return -1, 590

    def step(self):
        w = self.code[self.pc]
        op = OPS[w >> 26]; rd = (w >> 21) & 31; ra = (w >> 16) & 31; rb = (w >> 11) & 31
        imm11 = w & 0x7FF; imm16 = w & 0xFFFF
        simm16 = imm16 - 65536 if imm16 & 0x8000 else imm16
        R = self.r
        A, B = (R[ra] if ra else 0), (R[rb] if rb else 0)
        npc = self.pc + 1
        cyc = 2
        res = None
        if op == 'NOP': pass
        elif op == 'ADD': res = A + B
        elif op == 'SUB': res = A - B
        elif op == 'AND': res = A & B
        elif op == 'OR': res = A | B
        elif op == 'XOR': res = A ^ B
        elif op == 'SLL': res = (A & M32) << (B & 31)
        elif op == 'SRL': res = (A & M32) >> (B & 31)
        elif op == 'SRA': res = A >> (B & 31)
        elif op == 'MIN': res = min(A, B)
        elif op == 'MAX': res = max(A, B)
        elif op == 'ABS': res = abs(A)
        elif op == 'MUL': res = A * B; cyc = 4
        elif op == 'MULS': res = (A * B) >> (imm11 & 31); cyc = 4
        elif op == 'DIVQ':
            if B == 0: res = 0x7FFFFFFF if A >= 0 else -0x7FFFFFFF
            else:
                n = abs(A) << 16; d = abs(B); q = n // d
                res = q if (A < 0) == (B < 0) else -q
            cyc = 52
        elif op == 'ADDI': res = A + simm16
        elif op == 'LDI': res = simm16
        elif op == 'LUI': res = imm16 << 16
        elif op == 'ORI': res = (A & M32) | imm16
        elif op == 'SLLI': res = (A & M32) << (imm16 & 31)
        elif op == 'SRAI': res = A >> (imm16 & 31)
        elif op == 'SRLI': res = (A & M32) >> (imm16 & 31)
        elif op == 'ANDI': res = A & imm16
        elif op == 'LD': res = self.mem[(A + simm16) & 1023]; cyc = 3
        elif op == 'ST': self.mem[(A + simm16) & 1023] = s32(R[rd] if rd else 0); cyc = 3
        elif op == 'CRD': res = self.cand[(A + simm16) & 1023]; cyc = 3
        elif op == 'TWR': self.res[(A + simm16) & 511] = s32(R[rd] if rd else 0); cyc = 3
        elif op == 'PIX': res = self.frame_bit(A, B); cyc = 5
        elif op == 'BEQ': npc = imm11 if A == B else npc
        elif op == 'BNE': npc = imm11 if A != B else npc
        elif op == 'BLT': npc = imm11 if A < B else npc
        elif op == 'BGE': npc = imm11 if A >= B else npc
        elif op == 'JMP': npc = imm16
        elif op == 'JAL': res = self.pc + 1; npc = imm16
        elif op == 'JR': npc = A & 0xFFFF
        elif op == 'TAGMATCH': res, cyc = self.match(A, B); cyc += 4
        elif op == 'CNT': res = self.cfg['cand_count']
        elif op == 'CFG': res = self.cfg[['frame_id', 'maxham', 'cand_count', 'minside'][imm16 & 3]]
        elif op == 'HALT': self.halted = True; npc = self.pc
        if res is not None and rd: R[rd] = s32(res)
        self.pc = npc
        self.cycles += cyc

    def run(self, max_steps=20_000_000):
        n = 0
        while not self.halted and n < max_steps:
            self.step(); n += 1
        assert self.halted, 'TPU program did not halt'
        return self
