"""RV32I decode, immediate generation, execute and the two datapath muxes.

These combinational blocks are the boxes of the textbook single-cycle datapath:
Patterson & Hennessy, "Computer Organization and Design, RISC-V Edition",
chapter 4, and Harris & Harris, "Digital Design and Computer Architecture,
RISC-V Edition", chapter 7. Signal names follow those books: `reg_write` is
RegWrite, `result_src` is ResultSrc, `pc_src` is PCSrc and so on. A core
connects the blocks to its own PC, register file and memories;
`riscv.single_cycle` connects them for one instruction per clock.

RV32I instruction formats. Every format that has the opcode, rd, funct3, rs1,
rs2 or funct7 field keeps it at the same bits, so decode can slice all of them
before it knows the format. The immediate's bits move around between formats;
bit 31 is always its sign bit.

             31          25 24   20 19   15 14    12 11           7 6      0
    R-type  | funct7       | rs2   | rs1   | funct3 | rd           | opcode |
    I-type  | imm[11:0]            | rs1   | funct3 | rd           | opcode |
    S-type  | imm[11:5]    | rs2   | rs1   | funct3 | imm[4:0]     | opcode |
    B-type  | imm[12|10:5] | rs2   | rs1   | funct3 | imm[4:1|11]  | opcode |
    U-type  | imm[31:12]                            | rd           | opcode |
    J-type  | imm[20|10:1|11|19:12]                 | rd           | opcode |
"""

from enum import IntEnum
from typing import NamedTuple

from pypeline import *

# Opcodes, instruction bits 6:0. The comment gives the format and the instructions.
OP_LUI = 0b0110111  # U: LUI
OP_AUIPC = 0b0010111  # U: AUIPC
OP_JAL = 0b1101111  # J: JAL
OP_JALR = 0b1100111  # I: JALR
OP_BRANCH = 0b1100011  # B: BEQ BNE BLT BGE BLTU BGEU
OP_LOAD = 0b0000011  # I: LB LH LW LBU LHU
OP_STORE = 0b0100011  # S: SB SH SW
OP_IMM = 0b0010011  # I: ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI
OP_OP = 0b0110011  # R: ADD SUB SLL SLT SLTU XOR SRL SRA OR AND
OP_MISC_MEM = 0b0001111  # I: FENCE
OP_SYSTEM = 0b1110011  # I: ECALL EBREAK

# ALU operations of OP and OP-IMM, instruction bits 14:12 (funct3). The
# register and immediate forms share a code: ADD and ADDI are both 000.
FUNCT3_ADD_SUB = 0b000
FUNCT3_SLL = 0b001
FUNCT3_SLT = 0b010
FUNCT3_SLTU = 0b011
FUNCT3_XOR = 0b100
FUNCT3_SRL_SRA = 0b101
FUNCT3_OR = 0b110
FUNCT3_AND = 0b111
# Instruction bits 31:25 (funct7) pick SUB over ADD and SRA over SRL. For
# SRLI and SRAI the same bits are the top of the immediate.
FUNCT7_ADD = 0b0000000
FUNCT7_SUB = 0b0100000
FUNCT7_SRL = 0b0000000
FUNCT7_SRA = 0b0100000

# Branch comparisons, funct3 of OP_BRANCH. Codes 010 and 011 are unused.
FUNCT3_BEQ = 0b000
FUNCT3_BNE = 0b001
FUNCT3_BLT = 0b100
FUNCT3_BGE = 0b101
FUNCT3_BLTU = 0b110
FUNCT3_BGEU = 0b111

# Access widths, funct3 of OP_LOAD and OP_STORE. Bit 2 set means a load
# zero-extends its result instead of sign-extending it.
FUNCT3_LB = 0b000
FUNCT3_LH = 0b001
FUNCT3_LW = 0b010
FUNCT3_LBU = 0b100
FUNCT3_LHU = 0b101
FUNCT3_SB = 0b000
FUNCT3_SH = 0b001
FUNCT3_SW = 0b010

# The two SYSTEM instructions a core without CSRs recognizes, as whole words.
INST_ECALL = 0x00000073
INST_EBREAK = 0x00100073

# Which bytes of a 32-bit memory word a load or store uses, one bit per byte
# with bit 0 the lowest address. The memory stage shifts the mask left by the
# address's byte offset.
BYTE_MASK = 0b0001
HALF_MASK = 0b0011
WORD_MASK = 0b1111


@enum
class result_src_t(IntEnum):
    """ResultSrc: which value the write-back stage writes to rd.

    No member may share a name, in any case, with a port of a function that
    uses it: result_mux's `alu_result` and `read_data` ports would hide
    members named ALU_RESULT and READ_DATA in the generated VHDL. See
    docs/issues_inventory.md#31-358i358-enum-member-names-clash-with-other-vhdl-names.
    """

    ALU = 0  # execute's result: arithmetic, LUI and AUIPC
    MEMORY = 1  # the loaded value from data memory
    PC_PLUS_4 = 2  # the return address of JAL and JALR


@struct
class decoded_t(NamedTuple):
    # Instruction fields, at the bits shown in the module docstring.
    opcode: uint7_t
    rd: uint5_t
    funct3: uint3_t
    rs1: uint5_t
    rs2: uint5_t
    funct7: uint7_t
    # Control signals. Each is 0 unless the instruction needs it.
    reg_write: uint1_t  # RegWrite: write the result to rd
    result_src: result_src_t  # ResultSrc: which result rd gets
    mem_read: uint1_t  # MemRead: a load
    mem_write: uint1_t  # MemWrite: a store
    mem_byte_mask: uint4_t  # bytes a load or store uses (BYTE_, HALF_, WORD_MASK)
    mem_sign_extend: uint1_t  # LB and LH sign-extend; LBU and LHU do not
    pc_src: uint1_t  # PCSrc: the next PC is execute's result, not PC + 4
    # Instructions that stop this core, and encodings it does not implement.
    is_ecall: uint1_t
    is_ebreak: uint1_t
    illegal_instruction: uint1_t


@hw_func
def decode(instr: uint32_t) -> decoded_t:
    """Control unit: slice the instruction's fields and set the control signals.

    A field left unset is 0, so each opcode sets only the signals it needs.
    Any encoding RV32I does not define sets `illegal_instruction` and
    no write or memory access.
    """
    rv: decoded_t
    rv.opcode = instr[6:0]
    rv.rd = instr[11:7]
    rv.funct3 = instr[14:12]
    rv.rs1 = instr[19:15]
    rv.rs2 = instr[24:20]
    rv.funct7 = instr[31:25]
    if rv.opcode == OP_OP:
        # rd = rs1 op rs2. Only ADD/SUB and SRL/SRA use a nonzero funct7.
        if rv.funct3 == FUNCT3_ADD_SUB:
            if (rv.funct7 == FUNCT7_ADD) | (rv.funct7 == FUNCT7_SUB):
                rv.reg_write = 1
            else:
                rv.illegal_instruction = 1
        elif rv.funct3 == FUNCT3_SRL_SRA:
            if (rv.funct7 == FUNCT7_SRL) | (rv.funct7 == FUNCT7_SRA):
                rv.reg_write = 1
            else:
                rv.illegal_instruction = 1
        else:
            if rv.funct7 == 0:
                rv.reg_write = 1
            else:
                rv.illegal_instruction = 1
    elif rv.opcode == OP_IMM:
        # rd = rs1 op imm. A shift's imm[4:0] is the shift amount and its top
        # seven bits are a funct7: zero, or FUNCT7_SRA for SRAI.
        if (rv.funct3 == FUNCT3_SLL) | (rv.funct3 == FUNCT3_SRL_SRA):
            if (rv.funct7 == FUNCT7_SRL) | (
                (rv.funct3 == FUNCT3_SRL_SRA) & (rv.funct7 == FUNCT7_SRA)
            ):
                rv.reg_write = 1
            else:
                rv.illegal_instruction = 1
        else:
            rv.reg_write = 1
    elif (rv.opcode == OP_LUI) | (rv.opcode == OP_AUIPC):
        # rd = imm (LUI) or PC + imm (AUIPC), computed by execute.
        rv.reg_write = 1
    elif rv.opcode == OP_JAL:
        # Jump to PC + imm and write the return address PC + 4 to rd.
        rv.pc_src = 1
        rv.reg_write = 1
        rv.result_src = result_src_t.PC_PLUS_4
    elif (rv.opcode == OP_JALR) & (rv.funct3 == 0):
        # Jump to rs1 + imm and write the return address PC + 4 to rd.
        rv.pc_src = 1
        rv.reg_write = 1
        rv.result_src = result_src_t.PC_PLUS_4
    elif rv.opcode == OP_BRANCH:
        # Execute compares rs1 with rs2 and supplies the next PC either way.
        if (rv.funct3 == 0b010) | (rv.funct3 == 0b011):
            rv.illegal_instruction = 1
        else:
            rv.pc_src = 1
    elif rv.opcode == OP_LOAD:
        # rd = memory[rs1 + imm], extended to 32 bits.
        rv.mem_read = 1
        rv.reg_write = 1
        rv.result_src = result_src_t.MEMORY
        if rv.funct3 == FUNCT3_LW:
            rv.mem_byte_mask = WORD_MASK
        elif rv.funct3 == FUNCT3_LH:
            rv.mem_byte_mask = HALF_MASK
            rv.mem_sign_extend = 1
        elif rv.funct3 == FUNCT3_LHU:
            rv.mem_byte_mask = HALF_MASK
        elif rv.funct3 == FUNCT3_LB:
            rv.mem_byte_mask = BYTE_MASK
            rv.mem_sign_extend = 1
        elif rv.funct3 == FUNCT3_LBU:
            rv.mem_byte_mask = BYTE_MASK
        else:
            rv.illegal_instruction = 1
            rv.mem_read = 0
            rv.reg_write = 0
            rv.result_src = result_src_t.ALU
    elif rv.opcode == OP_STORE:
        # memory[rs1 + imm] = the low bytes of rs2.
        rv.mem_write = 1
        if rv.funct3 == FUNCT3_SW:
            rv.mem_byte_mask = WORD_MASK
        elif rv.funct3 == FUNCT3_SH:
            rv.mem_byte_mask = HALF_MASK
        elif rv.funct3 == FUNCT3_SB:
            rv.mem_byte_mask = BYTE_MASK
        else:
            rv.illegal_instruction = 1
            rv.mem_write = 0
    elif rv.opcode == OP_MISC_MEM:
        # FENCE orders memory accesses; this core already completes them in
        # order, so FENCE does nothing. FENCE.I (funct3 001) is not supported.
        if rv.funct3 != 0b000:
            rv.illegal_instruction = 1
    elif rv.opcode == OP_SYSTEM:
        rv.is_ecall = instr == INST_ECALL
        rv.is_ebreak = instr == INST_EBREAK
        rv.illegal_instruction = ~(rv.is_ecall | rv.is_ebreak)
    else:
        rv.illegal_instruction = 1
    return rv


@hw_func
def imm_gen(instr: uint32_t) -> int32_t:
    """Immediate generator: gather the immediate's bits and sign-extend them.

    Each format scatters the immediate differently (see the module
    docstring). B and J immediates are byte offsets with bit 0 always zero.
    U immediates fill the upper 20 bits. Instructions without an immediate
    get the I-type bits, which nothing uses.
    """
    opcode = instr[6:0]
    i_imm: int12_t = instr[31:20]
    s_imm: int12_t = concat(instr[31:25], instr[11:7])
    b_imm: int13_t = concat(instr[31], instr[7], instr[30:25], instr[11:8], uint1_t(0))
    u_imm: uint32_t = concat(instr[31:12], uint12_t(0))
    j_imm: int21_t = concat(
        instr[31], instr[19:12], instr[20], instr[30:21], uint1_t(0)
    )
    imm: int32_t = i_imm
    if opcode == OP_STORE:
        imm = s_imm
    elif opcode == OP_BRANCH:
        imm = b_imm
    elif (opcode == OP_LUI) | (opcode == OP_AUIPC):
        imm = u_imm
    elif opcode == OP_JAL:
        imm = j_imm
    return imm


@hw_func
def execute(
    pc: uint32_t,
    pc_plus4: uint32_t,
    decoded: decoded_t,
    imm: int32_t,
    read_data1: uint32_t,
    read_data2: uint32_t,
) -> uint32_t:
    """ALU and branch unit: compute the instruction's one 32-bit result.

    The result is the arithmetic value for OP, OP-IMM, LUI and AUIPC, the
    memory address for a load or store, and the next PC for a jump or branch.
    A branch compares rs1 with rs2 here and returns its target if taken and
    PC + 4 if not, so `pc_src` can select the result for every branch.
    """
    result: uint32_t = 0
    # The same register bits read as two's-complement numbers, for SLT,
    # SLTI, SRA, SRAI, BLT and BGE.
    signed1: int32_t = read_data1
    signed2: int32_t = read_data2
    imm_bits: uint32_t = imm
    # Shifts use only the low five bits of rs2 or of the immediate.
    shamt_reg: uint5_t = read_data2[4:0]
    shamt_imm: uint5_t = imm_bits[4:0]
    # PCTarget: the branch, JAL and AUIPC adder.
    pc_plus_imm: uint32_t = pc + imm_bits
    if decoded.opcode == OP_OP:
        if decoded.funct3 == FUNCT3_ADD_SUB:
            if decoded.funct7 == FUNCT7_SUB:
                result = read_data1 - read_data2
            else:
                result = read_data1 + read_data2
        elif decoded.funct3 == FUNCT3_SLT:
            result = signed1 < signed2
        elif decoded.funct3 == FUNCT3_SLTU:
            result = read_data1 < read_data2
        elif decoded.funct3 == FUNCT3_AND:
            result = read_data1 & read_data2
        elif decoded.funct3 == FUNCT3_OR:
            result = read_data1 | read_data2
        elif decoded.funct3 == FUNCT3_XOR:
            result = read_data1 ^ read_data2
        elif decoded.funct3 == FUNCT3_SLL:
            result = read_data1 << shamt_reg
        elif decoded.funct3 == FUNCT3_SRL_SRA:
            if decoded.funct7 == FUNCT7_SRA:
                result = signed1 >> shamt_reg
            else:
                result = read_data1 >> shamt_reg
    elif decoded.opcode == OP_IMM:
        if decoded.funct3 == FUNCT3_ADD_SUB:
            result = read_data1 + imm_bits
        elif decoded.funct3 == FUNCT3_AND:
            result = read_data1 & imm_bits
        elif decoded.funct3 == FUNCT3_OR:
            result = read_data1 | imm_bits
        elif decoded.funct3 == FUNCT3_XOR:
            result = read_data1 ^ imm_bits
        elif decoded.funct3 == FUNCT3_SLL:
            result = read_data1 << shamt_imm
        elif decoded.funct3 == FUNCT3_SLT:
            result = signed1 < imm
        elif decoded.funct3 == FUNCT3_SLTU:
            result = read_data1 < imm_bits
        elif decoded.funct3 == FUNCT3_SRL_SRA:
            if decoded.funct7 == FUNCT7_SRA:
                result = signed1 >> shamt_imm
            else:
                result = read_data1 >> shamt_imm
    elif decoded.opcode == OP_AUIPC:
        result = pc_plus_imm
    elif decoded.opcode == OP_LUI:
        result = imm_bits
    elif decoded.opcode == OP_BRANCH:
        taken: uint1_t = 0
        if decoded.funct3 == FUNCT3_BLT:
            taken = signed1 < signed2
        elif decoded.funct3 == FUNCT3_BLTU:
            taken = read_data1 < read_data2
        elif decoded.funct3 == FUNCT3_BGE:
            taken = signed1 >= signed2
        elif decoded.funct3 == FUNCT3_BGEU:
            taken = read_data1 >= read_data2
        elif decoded.funct3 == FUNCT3_BEQ:
            taken = read_data1 == read_data2
        elif decoded.funct3 == FUNCT3_BNE:
            taken = read_data1 != read_data2
        result = pc_plus_imm if taken else pc_plus4
    elif decoded.opcode == OP_JAL:
        result = pc_plus_imm
    elif decoded.opcode == OP_JALR:
        # JALR clears bit 0 of the sum, so the target is always even.
        target: uint32_t = read_data1 + imm_bits
        target[0] = 0
        result = target
    elif (decoded.opcode == OP_LOAD) | (decoded.opcode == OP_STORE):
        # The memory address.
        result = read_data1 + imm_bits
    return result


@hw_func
def result_mux(
    decoded: decoded_t, alu_result: uint32_t, read_data: uint32_t, pc_plus4: uint32_t
) -> uint32_t:
    """The ResultSrc mux: choose the value written to rd."""
    result = alu_result
    if decoded.result_src == result_src_t.MEMORY:
        result = read_data
    elif decoded.result_src == result_src_t.PC_PLUS_4:
        result = pc_plus4
    return result


@hw_func
def next_pc_mux(
    decoded: decoded_t, alu_result: uint32_t, pc_plus4: uint32_t
) -> uint32_t:
    """The PCSrc mux: jumps and branches take execute's result, the rest PC + 4."""
    return alu_result if decoded.pc_src else pc_plus4
