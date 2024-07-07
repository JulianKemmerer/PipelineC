#pragma once
// Common riscv things across all cores

#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"
// TODO remove duplicate code / do resource sharing, in decode+execute logic

// Register file w/ read+write ports
#include "reg_file.h"

// Helpers for building memory maps
#include "mem_map.h"

// OPCODES and such (RV32I)
#define OP_AUIPC  0b0010111
#define OP_BRANCH 0b1100011
#define OP_IMM    0b0010011
#define OP_JAL    0b1101111
#define OP_JALR   0b1100111
#define OP_LOAD   0b0000011
#define OP_LUI    0b0110111
#define OP_OP     0b0110011
#define OP_STORE  0b0100011
#define FUNCT3_ADD_SUB   0b000
#define FUNCT7_ADD 0b0000000
#define FUNCT7_SUB 0b0100000
#define FUNCT3_ADDI  0b000
#define FUNCT3_AND   0b111
#define FUNCT3_ANDI  0b111
#define FUNCT3_BEQ   0b000
#define FUNCT3_BLT   0b100
#define FUNCT3_BLTU  0b110
#define FUNCT3_BGE   0b101
#define FUNCT3_BGEU  0b111
#define FUNCT3_BNE   0b001
#define FUNCT3_LB_SB 0b000
#define FUNCT3_LBU   0b100
#define FUNCT3_LH_SH 0b001
#define FUNCT3_LHU   0b101
#define FUNCT3_LW_SW 0b010
#define FUNCT3_OR    0b110
#define FUNCT3_ORI   0b110
#define FUNCT3_SLLI  0b001
#define FUNCT3_SLL   0b001
#define FUNCT3_SLT   0b010
#define FUNCT3_SLTU  0b011
#define FUNCT3_SLTI  0b010
#define FUNCT3_SLTIU 0b011
#define FUNCT3_SRL_SRA   0b101
#define FUNCT7_SRL 0b0000000
#define FUNCT7_SRA 0b0100000
#define FUNCT3_SRLI_SRAI  0b101
#define FUNCT7_SRLI 0b0000000
#define FUNCT7_SRAI 0b0100000
#define FUNCT3_XOR   0b100
#define FUNCT3_XORI  0b100
// TODO
// Fences, exceptions, csr

// M Extension (Reusing the funct3 bits)
#define FUNCT7_MUL_DIV_REM 0b0000001
#define FUNCT3_MUL   FUNCT3_ADD_SUB
#define FUNCT3_MULH   FUNCT3_SLL
#define FUNCT3_MULHSU   FUNCT3_SLT
#define FUNCT3_MULHU   FUNCT3_SLTU
#define FUNCT3_DIV   FUNCT3_XOR
#define FUNCT3_DIVU   FUNCT3_SRL_SRA
#define FUNCT3_REM   FUNCT3_OR
#define FUNCT3_REMU   FUNCT3_AND

// Sorta decode+control
// Debug signal for simulation
//DEBUG_OUTPUT_DECL(uint1_t, unknown_op) // Unknown instruction
typedef struct decoded_t{
  uint5_t src2;
  uint5_t src1;
  uint3_t funct3;
  uint7_t funct7;
  uint5_t dest;
  uint7_t opcode;
  // Derived control flags from decode
  uint1_t reg_wr;
  uint1_t mem_wr_byte_ens[4];
  uint1_t mem_rd_byte_ens[4];
  uint1_t mem_rd_sign_ext;
  uint1_t mem_to_reg;
  uint1_t pc_plus4_to_reg;
  uint1_t exe_to_pc;
  int32_t signed_immediate;
  // Flags to help separate into autopipelines
  uint1_t is_rv32_m_ext; // just one other pipeline for MUL+DIV stuff for now
  // Printf controls
  uint1_t print_rs1_read;
  uint1_t print_rs2_read;
  // Debug
  uint1_t unknown_op;
} decoded_t;
decoded_t decode(uint32_t inst){
  decoded_t rv;
  rv.opcode = inst(6,0);
  rv.dest = inst(11, 7);
  rv.funct3 = inst(14, 12);
  rv.funct7 = inst(31, 25);
  rv.src1 = inst(19, 15);
  rv.src2 = inst(24, 20);
  if(rv.opcode==OP_OP){
    if(rv.funct3==FUNCT3_ADD_SUB){
      if(rv.funct7==FUNCT7_ADD){
        // ADD
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("ADD: r%d + r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7==FUNCT7_SUB){
        // SUB
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SUB: r%d - r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // MUL
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("MUL: r%d * r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_ADD_SUB instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_SLT){
      if(rv.funct7 == 0){ // default alu instruction
        // SLT
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SLT: r%d < r%d ? 1 : 0  -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // MULHSU
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("MULHSU: r%d * r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_SLT instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_SLTU){
      if(rv.funct7 == 0){ // default alu instruction
        // SLTU
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SLTU: (uint32_t)r%d < (uint32_t)r%d ? 1 : 0  -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // MULHU
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("MULHU: r%d * r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_SLTU instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_AND){
      if(rv.funct7 == 0){ // default alu instruction
        // AND
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("AND: r%d & r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // REMU
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("REMU: r%d mod r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_AND instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_OR){
      if(rv.funct7 == 0){ // default alu instruction
        // OR
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("OR: r%d | r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // REM
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("REM: r%d mod r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_OR instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_XOR){
      if(rv.funct7 == 0){ // default alu instruction
        // XOR
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("XOR: r%d ^ r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // DIV
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("DIV: r%d / r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_XOR instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }
    else if(rv.funct3==FUNCT3_SLL){
      if(rv.funct7 == 0){ // default alu instruction
        // SLL
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SLL: r%d << r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // MULH
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("MULH: r%d * r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_SLL instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_SRL_SRA){
      if(rv.funct7==FUNCT7_SRL){
        // SRL
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SRL: r%d >> r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7==FUNCT7_SRA){
        // SRA
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        printf("SRA: (int32_t)r%d >> r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }else if(rv.funct7 == FUNCT7_MUL_DIV_REM){
        // DIVU
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        rv.print_rs2_read = 1;
        rv.is_rv32_m_ext = 1;
        printf("DIVU: r%d / r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
      }
      else{
        printf("Unsupported FUNCT3_SRL_SRA instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else {
      printf("Unsupported OP_OP instruction: 0x%X\n", inst);
      rv.unknown_op = 1;
    }
  }else if(rv.opcode==OP_AUIPC){
    // AUIPC
    uint20_t imm31_12 = inst(31, 12);
    rv.signed_immediate = int32_uint20_12(0, imm31_12);
    rv.reg_wr = 1;
    printf("AUIPC: PC + %d -> r%d \n", rv.signed_immediate, rv.dest);
  }else if(rv.opcode==OP_BRANCH){
    if(rv.funct3==FUNCT3_BLT){
      // BLT
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BLT offset
      int13_t blt_offset;
      blt_offset = int13_uint1_12(blt_offset, imm12);
      blt_offset = int13_uint6_5(blt_offset, imm10_5);
      blt_offset = int13_uint4_1(blt_offset, imm4_1);
      blt_offset = int13_uint1_11(blt_offset, imm11);
      rv.signed_immediate = blt_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BLT: PC = r%d < r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BLTU){
      // BLTU
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BLT offset
      int13_t bltu_offset;
      bltu_offset = int13_uint1_12(bltu_offset, imm12);
      bltu_offset = int13_uint6_5(bltu_offset, imm10_5);
      bltu_offset = int13_uint4_1(bltu_offset, imm4_1);
      bltu_offset = int13_uint1_11(bltu_offset, imm11);
      rv.signed_immediate = bltu_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BLTU: PC = r%d < r%d ? PC+%d : PC+4;\n", (uint32_t)rv.src1, (uint32_t)rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BGE){
      // BGE
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BGE offset
      int13_t bge_offset;
      bge_offset = int13_uint1_12(bge_offset, imm12);
      bge_offset = int13_uint6_5(bge_offset, imm10_5);
      bge_offset = int13_uint4_1(bge_offset, imm4_1);
      bge_offset = int13_uint1_11(bge_offset, imm11);
      rv.signed_immediate = bge_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BGE: PC = r%d >= r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BGEU){
      // BGEU
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BGEU offset
      int13_t bgeu_offset;
      bgeu_offset = int13_uint1_12(bgeu_offset, imm12);
      bgeu_offset = int13_uint6_5(bgeu_offset, imm10_5);
      bgeu_offset = int13_uint4_1(bgeu_offset, imm4_1);
      bgeu_offset = int13_uint1_11(bgeu_offset, imm11);
      rv.signed_immediate = bgeu_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BGEU: PC = r%d >= r%d ? PC+%d : PC+4;\n", (uint32_t)rv.src1, (uint32_t)rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BEQ){
      // BEQ
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BEQ offset
      int13_t beq_offset;
      beq_offset = int13_uint1_12(beq_offset, imm12);
      beq_offset = int13_uint6_5(beq_offset, imm10_5);
      beq_offset = int13_uint4_1(beq_offset, imm4_1);
      beq_offset = int13_uint1_11(beq_offset, imm11);
      rv.signed_immediate = beq_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BEQ: PC = r%d == r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BNE){
      // BNE
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BNE offset
      int13_t bne_offset;
      bne_offset = int13_uint1_12(bne_offset, imm12);
      bne_offset = int13_uint6_5(bne_offset, imm10_5);
      bne_offset = int13_uint4_1(bne_offset, imm4_1);
      bne_offset = int13_uint1_11(bne_offset, imm11);
      rv.signed_immediate = bne_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BNE: PC = r%d != r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else {
      printf("Unsupported OP_BRANCH instruction: 0x%X\n", inst);
      rv.unknown_op = 1;
    }
  }else if(rv.opcode==OP_IMM){
    int12_t imm11_0 = inst(31, 20);
    if(rv.funct3==FUNCT3_ADDI){
      // ADDI
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("ADDI: r%d + %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_ANDI){
      // ANDI
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("ANDI: r%d & %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_ORI){
      // ORI
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("ORI: r%d | %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_SLLI){
      // SLLI
      uint5_t shamt = imm11_0(4, 0);
      rv.signed_immediate = shamt;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("SLLI: r%d << %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_SLTI){
      // SLTI
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("SLTI: r%d < %d ? 1 : 0  -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_SLTIU){
      // SLTIU
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("SLTIU: (uint)r%d < (uint)%d ? 1 : 0  -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_SRLI_SRAI){
      if(rv.funct7==FUNCT7_SRLI){
        // SRLI
        uint5_t shamt = imm11_0(4, 0);
        rv.signed_immediate = shamt;
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        printf("SRLI: r%d >> %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
      }else if(rv.funct7==FUNCT7_SRAI){
        // SRAI
        uint5_t shamt = imm11_0(4, 0);
        rv.signed_immediate = shamt;
        rv.reg_wr = 1;
        rv.print_rs1_read = 1;
        printf("SRAI: r%d >> %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
      }else{
        printf("Unsupported FUNCT3_SRLI_SRAI instruction: 0x%X\n", inst);
        rv.unknown_op = 1;
      }
    }else if(rv.funct3==FUNCT3_XORI){
      // XORI
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("XORI: r%d ^ %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else{
      printf("Unsupported OP_IMM instruction: 0x%X\n", inst);
      rv.unknown_op = 1;
    }
  }else if(rv.opcode==OP_JAL){
    // JAL - Jump and link
    uint1_t imm20 = inst(31);
    uint10_t imm10_1 = inst(30,21);
    uint1_t imm11 = inst(20);
    uint8_t immm19_12 = inst(19, 12);
    // Jump offset
    int21_t jal_offset;
    jal_offset = int21_uint1_20(jal_offset, imm20);
    jal_offset = int21_uint10_1(jal_offset, imm10_1);
    jal_offset = int21_uint1_11(jal_offset, imm11);
    jal_offset = int21_uint8_12(jal_offset, immm19_12);
    rv.signed_immediate = jal_offset;
    // Execute stage does pc related math
    rv.exe_to_pc = 1;
    // And link
    rv.pc_plus4_to_reg = 1;
    rv.reg_wr = 1;
    printf("JAL: PC+=%d, PC+4 -> r%d \n", rv.signed_immediate, rv.dest);
  }else if(rv.opcode==OP_JALR){
    // JALR - Jump and link register
    int12_t jalr_offset = inst(31, 20);
    // Jump offset
    rv.signed_immediate = jalr_offset;
    // Execute stage does pc related math
    rv.print_rs1_read = 1;
    rv.exe_to_pc = 1;
    // And link
    rv.pc_plus4_to_reg = 1;
    rv.reg_wr = 1;
    printf("JALR: PC=(%d + r%d), PC+4 -> r%d \n", rv.signed_immediate, rv.src1, rv.dest);
  }else if(rv.opcode==OP_LOAD){
    // Store offset
    int12_t lw_offset = inst(31, 20);
    int32_t sign_extended_offset = lw_offset;
    rv.signed_immediate = sign_extended_offset;
    uint1_t W_BYTE_ENS[4] = {1,1,1,1};
    uint1_t H_BYTE_ENS[4] = {1,1,0,0};
    uint1_t B_BYTE_ENS[4] = {1,0,0,0};
    if(rv.funct3==FUNCT3_LW_SW){
      // LW
      rv.mem_rd_byte_ens = W_BYTE_ENS;
      rv.mem_to_reg = 1;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("LW: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_LH_SH){
      // LH
      rv.mem_rd_byte_ens = H_BYTE_ENS;
      rv.mem_to_reg = 1;
      rv.mem_rd_sign_ext = 1;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("LH: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_LHU){
      // LHU
      rv.mem_rd_byte_ens = H_BYTE_ENS;
      rv.mem_to_reg = 1;
      rv.mem_rd_sign_ext = 0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("LHU: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_LB_SB){
      // LB
      rv.mem_rd_byte_ens = B_BYTE_ENS;
      rv.mem_to_reg = 1;
      rv.mem_rd_sign_ext = 1;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("LB: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_LBU){
      // LBU
      rv.mem_rd_byte_ens = B_BYTE_ENS;
      rv.mem_to_reg = 1;
      rv.mem_rd_sign_ext = 0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("LBU: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else{
      printf("Unsupported OP_LOAD instruction: 0x%X\n", inst);
      rv.unknown_op = 1;
    }
  }else if(rv.opcode==OP_LUI){
    // LUI
    rv.reg_wr = 1;
    uint20_t imm31_12 = inst(31, 12);
    rv.signed_immediate = int32_uint20_12(0, imm31_12);
    printf("LUI: %d -> r%d \n", rv.signed_immediate, rv.dest);
  }else if(rv.opcode==OP_STORE){
    rv.print_rs1_read = 1;
    rv.print_rs2_read = 1;
    uint7_t imm11_5 = inst(31, 25);
    uint5_t imm4_0 = inst(11, 7);
    // Store offset
    int12_t sw_offset;
    sw_offset = int12_uint7_5(sw_offset, imm11_5);
    sw_offset = int12_uint5_0(sw_offset, imm4_0);
    int32_t sign_extended_offset = sw_offset;
    rv.signed_immediate = sign_extended_offset;
    if(rv.funct3==FUNCT3_LW_SW){
      // SW
      rv.mem_wr_byte_ens[0] = 1;
      rv.mem_wr_byte_ens[1] = 1;
      rv.mem_wr_byte_ens[2] = 1;
      rv.mem_wr_byte_ens[3] = 1;
      printf("SW: addr = r%d + %d, mem[addr] <- r%d \n", rv.src1, rv.signed_immediate, rv.src2);
    }else if(rv.funct3==FUNCT3_LH_SH){
      // SH
      rv.mem_wr_byte_ens[0] = 1;
      rv.mem_wr_byte_ens[1] = 1;
      printf("SH: addr = r%d + %d, mem[addr](15 downto 0) <- r%d \n", rv.src1, rv.signed_immediate, rv.src2);
    }else if(rv.funct3==FUNCT3_LB_SB){
      // SB
      rv.mem_wr_byte_ens[0] = 1;
      printf("SB: addr = r%d + %d, mem[addr](7 downto 0) <- r%d \n", rv.src1, rv.signed_immediate, rv.src2);
    }else {
      printf("Unsupported OP_STORE instruction: 0x%X\n", inst);
      rv.unknown_op = 1;
    }
  }else{
    printf("Unsupported instruction: 0x%X\n", inst);
    rv.unknown_op = 1;
  }
  return rv;
}

// Exceute/ALU

// MUL+DIV version for 'M'
typedef struct execute_rv32_m_ext_in_t{
  decoded_t decoded;
  uint32_t reg1;
  uint32_t reg2;
}execute_rv32_m_ext_in_t;
typedef struct execute_t
{
  uint32_t result;
}execute_t;
execute_t execute_rv32_m_ext(
  execute_rv32_m_ext_in_t i
){
  decoded_t decoded = i.decoded;
  uint32_t reg1 = i.reg1;
  uint32_t reg2 = i.reg2;
  execute_t rv;
  if(decoded.opcode==OP_OP){
    if(decoded.funct3==FUNCT3_ADD_SUB){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (int32_t)reg1 * (int32_t)reg2;
        printf("MUL: (int32_t)%d * (int32_t)%d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_SLT){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (int64_t)((int32_t)reg1 * (uint32_t)reg2) >> 32;
        printf("MULHSU: (int64_t)((int32_t)%d * (uint32_t)%d) >> 32 = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_SLTU){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (uint64_t)(reg1 * reg2) >> 32;
        printf("MULHU: (uint64_t)(%d * %d) >> 32 = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_AND){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = reg1 % reg2;
        printf("REMU: %d / %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_OR){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (int32_t)reg1 % (int32_t)reg2;
        printf("REM: (int32_t)%d / (int32_t)%d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_XOR){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (int32_t)reg1 / (int32_t)reg2;
        printf("DIV: (int32_t)%d / (int32_t)%d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_SLL){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = (int64_t)((int32_t)reg1 * (int32_t)reg2) >> 32;
        printf("MULH: (int64_t)((int32_t)%d * (int32_t)%d) >> 32 = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_SRL_SRA){
      if(decoded.funct7==FUNCT7_MUL_DIV_REM){
        rv.result = reg1 / reg2;
        printf("DIVU: %d / %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }
  }
  return rv;
}

// Original RV32I execute stage
typedef struct execute_t
{
  uint32_t result;
}execute_t;
execute_t execute(
  uint32_t pc, uint32_t pc_plus4, 
  decoded_t decoded, uint32_t reg1, uint32_t reg2)
{
  execute_t rv;
  if(decoded.opcode==OP_OP){
    if(decoded.funct3==FUNCT3_ADD_SUB){
      if(decoded.funct7==FUNCT7_ADD){
        rv.result = reg1 + reg2;
        printf("ADD: %d + %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }else if(decoded.funct7==FUNCT7_SUB){
        rv.result = reg1 - reg2;
        printf("SUB: %d - %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }else if(decoded.funct3==FUNCT3_SLT){
      rv.result = (int32_t)reg1 < (int32_t)reg2;
      printf("SLT: %d < %d = %d -> r%d;\n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SLTU){
      rv.result = (uint32_t)reg1 < (uint32_t)reg2;
      printf("SLTU: %d < %d = %d -> r%d;\n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_AND){
      rv.result = reg1 & reg2;
      printf("AND: %d & %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_OR){
      rv.result = reg1 | reg2;
      printf("OR: %d | %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_XOR){
      rv.result = reg1 ^ reg2;
      printf("XOR: %d ^ %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SLL){
      rv.result = reg1 << (uint5_t)reg2;
      printf("SLL: %d << %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SRL_SRA){
      if(decoded.funct7==FUNCT7_SRL){
        rv.result = reg1 >> (uint5_t)reg2;
        printf("SRL: %d >> %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }else if(decoded.funct7==FUNCT7_SRA){
        rv.result = (int32_t)reg1 >> (uint5_t)reg2;
        printf("SRA: (int32_t)%d >> %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
      }
    }
  }else if(decoded.opcode==OP_AUIPC){
    rv.result = pc + decoded.signed_immediate;
    printf("AUIPC: PC %d + %d = 0x%X -> r%d\n", pc, decoded.signed_immediate, (int32_t)rv.result, decoded.dest);
  }else if(decoded.opcode==OP_BRANCH){
    if(decoded.funct3==FUNCT3_BLT){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if((int32_t)reg1 < (int32_t)reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BLT: PC = %d < %d ? 0x%X : PC+4 0x%X;\n", reg1, reg2, pc_plus_imm, pc_plus4);
    }else if(decoded.funct3==FUNCT3_BLTU){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if((uint32_t)reg1 < (uint32_t)reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BLTU: PC = %d < %d ? 0x%X : PC+4 0x%X;\n", (uint32_t)reg1, (uint32_t)reg2, pc_plus_imm, pc_plus4);
    }else if(decoded.funct3==FUNCT3_BGE){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if((int32_t)reg1 >= (int32_t)reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BGE: PC = %d >= %d ? 0x%X : PC+4 0x%X;\n", reg1, reg2, pc_plus_imm, pc_plus4);
    }else if(decoded.funct3==FUNCT3_BGEU){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if((uint32_t)reg1 >= (uint32_t)reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BGEU: PC = %d >= %d ? 0x%X : PC+4 0x%X;\n", (uint32_t)reg1, (uint32_t)reg2, pc_plus_imm, pc_plus4);
    }else if(decoded.funct3==FUNCT3_BEQ){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if(reg1 == reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BEQ: PC = %d == %d ? 0x%X : PC+4 0x%X;\n", reg1, reg2, pc_plus_imm, pc_plus4);
    }else if(decoded.funct3==FUNCT3_BNE){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if(reg1 != reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BNE: PC = %d != %d ? 0x%X : PC+4 0x%X;\n", reg1, reg2, pc_plus_imm, pc_plus4);
    }
  }else if(decoded.opcode==OP_IMM){
    if(decoded.funct3==FUNCT3_ADDI){
      rv.result = reg1 + decoded.signed_immediate;
      printf("ADDI: %d + %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_ANDI){
      rv.result = reg1 & decoded.signed_immediate;
      printf("ANDI: %d & %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_ORI){
      rv.result = reg1 | decoded.signed_immediate;
      printf("ORI: %d | %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_XORI){
      rv.result = reg1 ^ decoded.signed_immediate;
      printf("XORI: %d ^ %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SLLI){
      rv.result = reg1 << decoded.signed_immediate;
      printf("SLLI: %d << %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SLTI){
      rv.result = ((int32_t)reg1) < decoded.signed_immediate ? 1 : 0;
      printf("SLTI: %d < %d = %d ? 1 : 0 -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SLTIU){
      rv.result = reg1 < (uint32_t)decoded.signed_immediate ? 1 : 0;
      printf("SLTIU: 0x%X < 0x%X = %d ? 1 : 0 -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_SRLI_SRAI){
      if(decoded.funct7==FUNCT7_SRLI){
        rv.result = reg1 >> decoded.signed_immediate;
        printf("SRLI: %d >> %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
      }else if(decoded.funct7==FUNCT7_SRAI){
        rv.result = ((int32_t)reg1) >> decoded.signed_immediate;
        printf("SRAI: %d >> %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
      }
    }
  }else if(decoded.opcode==OP_JAL){
    rv.result = pc + decoded.signed_immediate;
    printf("JAL: PC = %d + %d = 0x%X\n", pc, decoded.signed_immediate, (int32_t)rv.result);
  }else if(decoded.opcode==OP_JALR){
    rv.result = decoded.signed_immediate + reg1;
    rv.result = int32_uint1_0(rv.result, 0); // rv.result[0] = 0;
    printf("JALR: PC = %d + %d = 0x%X\n", decoded.signed_immediate, reg1, (int32_t)rv.result);
  }else if(decoded.opcode==OP_LOAD){
    rv.result = reg1 + decoded.signed_immediate;
    if(decoded.funct3==FUNCT3_LW_SW){
      printf("LW: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_LH_SH){
      printf("LH: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_LHU){
      printf("LHU: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_LB_SB){
      printf("LB: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }else if(decoded.funct3==FUNCT3_LBU){
      printf("LBU: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }
  }else if(decoded.opcode==OP_LUI){
    rv.result = decoded.signed_immediate;
    printf("LUI: exe result = %d \n", decoded.signed_immediate);
  }else if(decoded.opcode==OP_STORE){
    rv.result = reg1 + decoded.signed_immediate;
    if(decoded.funct3==FUNCT3_LW_SW){
      printf("SW: addr = %d + %d = %d, mem[0x%X] <- %d \n", reg1, decoded.signed_immediate, rv.result, rv.result, reg2);
    }else if(decoded.funct3==FUNCT3_LH_SH){
      printf("SH: addr = %d + %d = %d, mem[0x%X](15 downto 0) <- %d \n", reg1, decoded.signed_immediate, rv.result, rv.result, (uint16_t)reg2);
    }else if(decoded.funct3==FUNCT3_LB_SB){
      printf("SB: addr = %d + %d = %d, mem[0x%X](7 downto 0) <- %d \n", reg1, decoded.signed_immediate, rv.result, rv.result, (uint8_t)reg2);
    }
  }
  return rv;
}
// RV32I for pipelining via helper macro expecting 1 input and 1 output
typedef struct execute_rv32i_in_t{
  uint32_t pc;
  uint32_t pc_plus4;
  decoded_t decoded;
  uint32_t reg1;
  uint32_t reg2;
}execute_rv32i_in_t;
execute_t execute_rv32i(
  execute_rv32i_in_t i
){
  uint32_t pc = i.pc;
  uint32_t pc_plus4 = i.pc_plus4;
  decoded_t decoded = i.decoded;
  uint32_t reg1 = i.reg1;
  uint32_t reg2 = i.reg2;
  return execute(pc, pc_plus4, decoded, reg1, reg2);
}

// Determine register file data to write back
uint32_t select_reg_wr_data(
  decoded_t decoded,
  execute_t exe,
  uint32_t mem_rd_data,
  uint32_t pc_plus4
){
  uint32_t reg_wr_data = exe.result;
  if(decoded.mem_to_reg){
    printf("Write RegFile: MemRd->Reg...\n");
    reg_wr_data = mem_rd_data;
    if(decoded.mem_rd_sign_ext){
      int32_t i32_value;
      if(
        ~decoded.mem_rd_byte_ens[3] &
        ~decoded.mem_rd_byte_ens[2] &
        decoded.mem_rd_byte_ens[1] &
        decoded.mem_rd_byte_ens[0]
      ){
        // Sign extend bottom two bytes
        i32_value = (int16_t)mem_rd_data(15,0);
        reg_wr_data = i32_value;
      }else if(
        ~decoded.mem_rd_byte_ens[3] &
        ~decoded.mem_rd_byte_ens[2] &
        ~decoded.mem_rd_byte_ens[1] &
        decoded.mem_rd_byte_ens[0]
      ){
        // Sign extend bottom byte
        i32_value = (int8_t)mem_rd_data(7,0);
        reg_wr_data = i32_value;
      }
    }        
  }else if(decoded.pc_plus4_to_reg){
    printf("Write RegFile: PC+4->Reg...\n");
    reg_wr_data = pc_plus4;
  }else{
    if(decoded.reg_wr)
      printf("Write RegFile: Execute Result->Reg...\n");
  }
  if(decoded.reg_wr){
    printf("Write RegFile[%d] = %d\n", decoded.dest, reg_wr_data);
  }
  return reg_wr_data;
}

// Branch/Increment PC
uint32_t select_next_pc(
  decoded_t decoded,
  execute_t exe,
  uint32_t pc_plus4
){
  uint32_t pc;
  if(decoded.exe_to_pc){
    printf("Next PC: Execute Result = 0x%X...\n", exe.result);
    pc = exe.result;
  }else{
    // Default next pc
    printf("Next PC: Default = 0x%X...\n", pc_plus4);
    pc = pc_plus4;
  }
  return pc;
}