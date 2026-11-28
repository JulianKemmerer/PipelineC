"""Combinational RV32I instruction decode, execute and result selection."""

from typing import NamedTuple

from pypeline import *

# RV32I major opcodes, indexed by instruction bits 6:0.
OP_AUIPC = 0b0010111
OP_BRANCH = 0b1100011
OP_IMM = 0b0010011
OP_JAL = 0b1101111
OP_JALR = 0b1100111
OP_LOAD = 0b0000011
OP_LUI = 0b0110111
OP_OP = 0b0110011
OP_STORE = 0b0100011
OP_MISC_MEM = 0b0001111
OP_SYSTEM = 0b1110011

# Suboperations selected by funct3 and funct7 within a major opcode.
FUNCT3_ADD_SUB_MUL = 0b000
FUNCT7_ADD = 0b0000000
FUNCT3_ADDI = 0b000
FUNCT3_AND_REMU = 0b111
FUNCT3_ANDI = 0b111
FUNCT3_BEQ = 0b000
FUNCT3_BLT = 0b100
FUNCT3_BLTU = 0b110
FUNCT3_BGE = 0b101
FUNCT3_BGEU = 0b111
FUNCT3_BNE = 0b001
FUNCT3_LB_SB = 0b000
FUNCT3_LBU = 0b100
FUNCT3_LH_SH = 0b001
FUNCT3_LHU = 0b101
FUNCT3_LW_SW = 0b010
FUNCT3_OR_REM = 0b110
FUNCT3_ORI = 0b110
FUNCT3_SLLI = 0b001
FUNCT3_SLL_MULH = 0b001
FUNCT3_SLT_MULHSU = 0b010
FUNCT3_SLTU_MULHU = 0b011
FUNCT3_SLTI = 0b010
FUNCT3_SLTIU = 0b011
FUNCT3_SRL_SRA_DIVU = 0b101
FUNCT7_SRL = 0b0000000
FUNCT7_SRA = 0b0100000
FUNCT3_SRLI_SRAI = 0b101
FUNCT7_SRLI = 0b0000000
FUNCT7_SRAI = 0b0100000
FUNCT7_SUB = 0b0100000
FUNCT3_XOR_DIV = 0b100
FUNCT3_XORI = 0b100
# Complete SYSTEM instruction words recognized by the trap-free core.
INST_ECALL = 0x00000073
INST_EBREAK = 0x00100073


@struct
class decoded_t(NamedTuple):
    src2: uint5_t
    src1: uint5_t
    funct3: uint3_t
    funct7: uint7_t
    dest: uint5_t
    opcode: uint7_t
    reg_wr: uint1_t
    mem_wr_byte_ens: uint1_t[4]
    mem_rd_byte_ens: uint1_t[4]
    mem_rd_sign_ext: uint1_t
    mem_to_reg: uint1_t
    reg_to_mem: uint1_t
    pc_plus4_to_reg: uint1_t
    exe_to_pc: uint1_t
    signed_immediate: int32_t
    is_ecall: uint1_t
    is_ebreak: uint1_t
    unknown_op: uint1_t


@hw_func
def b_offset(inst: uint32_t) -> int32_t:
    off: int13_t = concat(inst[31], inst[7], inst[30:25], inst[11:8], uint1_t(0))
    return off


@hw_func
def decode(inst: uint32_t) -> decoded_t:
    rv: decoded_t
    rv.opcode = inst[6:0]
    rv.dest = inst[11:7]
    rv.funct3 = inst[14:12]
    rv.funct7 = inst[31:25]
    rv.src1 = inst[19:15]
    rv.src2 = inst[24:20]
    w_byte_ens: uint1_t[4] = [1, 1, 1, 1]
    h_byte_ens: uint1_t[4] = [1, 1, 0, 0]
    b_byte_ens: uint1_t[4] = [1, 0, 0, 0]
    imm11_0: int12_t = inst[31:20]
    if rv.opcode == OP_OP:
        if rv.funct3 == FUNCT3_ADD_SUB_MUL:
            if (rv.funct7 == FUNCT7_ADD) | (rv.funct7 == FUNCT7_SUB):
                rv.reg_wr = 1
            else:
                rv.unknown_op = 1
        elif rv.funct3 == FUNCT3_SRL_SRA_DIVU:
            if (rv.funct7 == FUNCT7_SRL) | (rv.funct7 == FUNCT7_SRA):
                rv.reg_wr = 1
            else:
                rv.unknown_op = 1
        else:
            if rv.funct7 == 0:
                rv.reg_wr = 1
            else:
                rv.unknown_op = 1
    elif rv.opcode == OP_AUIPC:
        rv.signed_immediate = concat(inst[31:12], uint12_t(0))
        rv.reg_wr = 1
    elif rv.opcode == OP_BRANCH:
        if (rv.funct3 == 0b010) | (rv.funct3 == 0b011):
            rv.unknown_op = 1
        else:
            rv.signed_immediate = b_offset(inst=inst)
            rv.exe_to_pc = 1
    elif rv.opcode == OP_IMM:
        if (rv.funct3 == FUNCT3_SLLI) | (rv.funct3 == FUNCT3_SRLI_SRAI):
            shamt: uint5_t = imm11_0[4:0]
            rv.signed_immediate = shamt
            if (rv.funct7 != FUNCT7_SRLI) & ~(
                (rv.funct3 == FUNCT3_SRLI_SRAI) & (rv.funct7 == FUNCT7_SRAI)
            ):
                rv.unknown_op = 1
            else:
                rv.reg_wr = 1
        else:
            rv.signed_immediate = imm11_0
            rv.reg_wr = 1
    elif rv.opcode == OP_JAL:
        jal_offset: int21_t = concat(
            inst[31], inst[19:12], inst[20], inst[30:21], uint1_t(0)
        )
        rv.signed_immediate = jal_offset
        rv.exe_to_pc = 1
        rv.pc_plus4_to_reg = 1
        rv.reg_wr = 1
    elif (rv.opcode == OP_JALR) & (rv.funct3 == 0):
        rv.signed_immediate = imm11_0
        rv.exe_to_pc = 1
        rv.pc_plus4_to_reg = 1
        rv.reg_wr = 1
    elif rv.opcode == OP_LOAD:
        rv.mem_to_reg = 1
        rv.reg_wr = 1
        rv.signed_immediate = imm11_0
        if rv.funct3 == FUNCT3_LW_SW:
            rv.mem_rd_byte_ens = w_byte_ens
        elif rv.funct3 == FUNCT3_LH_SH:
            rv.mem_rd_byte_ens = h_byte_ens
            rv.mem_rd_sign_ext = 1
        elif rv.funct3 == FUNCT3_LHU:
            rv.mem_rd_byte_ens = h_byte_ens
        elif rv.funct3 == FUNCT3_LB_SB:
            rv.mem_rd_byte_ens = b_byte_ens
            rv.mem_rd_sign_ext = 1
        elif rv.funct3 == FUNCT3_LBU:
            rv.mem_rd_byte_ens = b_byte_ens
        else:
            rv.unknown_op = 1
            rv.reg_wr = 0
            rv.mem_to_reg = 0
    elif rv.opcode == OP_LUI:
        rv.reg_wr = 1
        rv.signed_immediate = concat(inst[31:12], uint12_t(0))
    elif rv.opcode == OP_STORE:
        rv.reg_to_mem = 1
        sw_offset: int12_t = concat(inst[31:25], inst[11:7])
        rv.signed_immediate = sw_offset
        if rv.funct3 == FUNCT3_LW_SW:
            rv.mem_wr_byte_ens = w_byte_ens
        elif rv.funct3 == FUNCT3_LH_SH:
            rv.mem_wr_byte_ens = h_byte_ens
        elif rv.funct3 == FUNCT3_LB_SB:
            rv.mem_wr_byte_ens = b_byte_ens
        else:
            rv.unknown_op = 1
            rv.reg_to_mem = 0
    elif rv.opcode == OP_MISC_MEM:
        if rv.funct3 != 0b000:  # FENCE is a no-op; FENCE.I is not supported
            rv.unknown_op = 1
    elif rv.opcode == OP_SYSTEM:
        rv.is_ecall = inst == INST_ECALL
        rv.is_ebreak = inst == INST_EBREAK
        rv.unknown_op = ~(rv.is_ecall | rv.is_ebreak)
    else:
        rv.unknown_op = 1
    return rv


@struct
class execute_t(NamedTuple):
    result: uint32_t


@hw_func
def execute(
    pc: uint32_t, pc_plus4: uint32_t, decoded: decoded_t, reg1: uint32_t, reg2: uint32_t
) -> execute_t:
    rv: execute_t
    imm: int32_t = decoded.signed_immediate
    imm_u: uint32_t = imm
    s1: int32_t = reg1
    s2: int32_t = reg2
    shamt_r: uint5_t = reg2[4:0]
    shamt_i: uint5_t = imm_u[4:0]
    pc_plus_imm: uint32_t = pc + imm_u
    if decoded.opcode == OP_OP:
        if decoded.funct3 == FUNCT3_ADD_SUB_MUL:
            if decoded.funct7 == FUNCT7_SUB:
                rv.result = reg1 - reg2
            else:
                rv.result = reg1 + reg2
        elif decoded.funct3 == FUNCT3_SLT_MULHSU:
            rv.result = s1 < s2
        elif decoded.funct3 == FUNCT3_SLTU_MULHU:
            rv.result = reg1 < reg2
        elif decoded.funct3 == FUNCT3_AND_REMU:
            rv.result = reg1 & reg2
        elif decoded.funct3 == FUNCT3_OR_REM:
            rv.result = reg1 | reg2
        elif decoded.funct3 == FUNCT3_XOR_DIV:
            rv.result = reg1 ^ reg2
        elif decoded.funct3 == FUNCT3_SLL_MULH:
            rv.result = reg1 << shamt_r
        elif decoded.funct3 == FUNCT3_SRL_SRA_DIVU:
            if decoded.funct7 == FUNCT7_SRA:
                rv.result = s1 >> shamt_r
            else:
                rv.result = reg1 >> shamt_r
    elif decoded.opcode == OP_AUIPC:
        rv.result = pc_plus_imm
    elif decoded.opcode == OP_BRANCH:
        taken: uint1_t = 0
        if decoded.funct3 == FUNCT3_BLT:
            taken = s1 < s2
        elif decoded.funct3 == FUNCT3_BLTU:
            taken = reg1 < reg2
        elif decoded.funct3 == FUNCT3_BGE:
            taken = s1 >= s2
        elif decoded.funct3 == FUNCT3_BGEU:
            taken = reg1 >= reg2
        elif decoded.funct3 == FUNCT3_BEQ:
            taken = reg1 == reg2
        elif decoded.funct3 == FUNCT3_BNE:
            taken = reg1 != reg2
        rv.result = pc_plus_imm if taken else pc_plus4
    elif decoded.opcode == OP_IMM:
        if decoded.funct3 == FUNCT3_ADDI:
            rv.result = reg1 + imm_u
        elif decoded.funct3 == FUNCT3_ANDI:
            rv.result = reg1 & imm_u
        elif decoded.funct3 == FUNCT3_ORI:
            rv.result = reg1 | imm_u
        elif decoded.funct3 == FUNCT3_XORI:
            rv.result = reg1 ^ imm_u
        elif decoded.funct3 == FUNCT3_SLLI:
            rv.result = reg1 << shamt_i
        elif decoded.funct3 == FUNCT3_SLTI:
            rv.result = s1 < imm
        elif decoded.funct3 == FUNCT3_SLTIU:
            rv.result = reg1 < imm_u
        elif decoded.funct3 == FUNCT3_SRLI_SRAI:
            if decoded.funct7 == FUNCT7_SRAI:
                rv.result = s1 >> shamt_i
            else:
                rv.result = reg1 >> shamt_i
    elif decoded.opcode == OP_JAL:
        rv.result = pc_plus_imm
    elif decoded.opcode == OP_JALR:
        target: uint32_t = reg1 + imm_u
        target[0] = 0
        rv.result = target
    elif (decoded.opcode == OP_LOAD) | (decoded.opcode == OP_STORE):
        rv.result = reg1 + imm_u
    elif decoded.opcode == OP_LUI:
        rv.result = imm_u
    return rv


@hw_func
def select_reg_wr_data(
    decoded: decoded_t, exe: execute_t, mem_rd_data: uint32_t, pc_plus4: uint32_t
) -> uint32_t:
    result = exe.result
    if decoded.mem_to_reg:
        result = mem_rd_data
    elif decoded.pc_plus4_to_reg:
        result = pc_plus4
    return result


@hw_func
def select_next_pc(decoded: decoded_t, exe: execute_t, pc_plus4: uint32_t) -> uint32_t:
    return exe.result if decoded.exe_to_pc else pc_plus4
