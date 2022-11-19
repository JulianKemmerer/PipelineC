#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"
#include "debug_port.h"

// Set CPU clock
#define CPU_CLK_MHZ 40.0
MAIN_MHZ(risc_v, CPU_CLK_MHZ)

// TODO remove duplicate code / do resource sharing, in decode+execute logic

// Register file w/ read+write ports
#include "reg_file.c"

// Combined instruction and data memory w/ ports
// Also includes memory mapped IO
#include "mem.c"

// OPCODES and such
#define OP_ADD    0b0110011
#define OP_AUIPC  0b0010111
#define OP_BRANCH 0b1100011
#define OP_IMM    0b0010011
#define OP_JAL    0b1101111
#define OP_JALR   0b1100111
#define OP_LOAD   0b0000011
#define OP_LUI    0b0110111
#define OP_STORE  0b0100011
#define FUNCT3_ADDI  0b000
#define FUNCT3_ANDI  0b111
#define FUNCT3_BEQ   0b000
#define FUNCT3_BLT   0b100
#define FUNCT3_BGE   0b101
#define FUNCT3_BNE   0b001
#define FUNCT3_LB_SB 0b000
#define FUNCT3_LH_SH 0b001
#define FUNCT3_LW_SW 0b010
#define FUNCT3_SLLI  0b001
#define FUNCT3_SLTI  0b010
#define FUNCT3_SLTIU 0b011
#define FUNCT3_SRAI  0b101
#define FUNCT3_XORI  0b100

// Sorta decode+control
// Debug signal for simulation
DEBUG_OUTPUT_DECL(uint1_t, unknown_op) // Unknown instruction
typedef struct decoded_t{
  uint5_t src2;
  uint5_t src1;
  uint3_t funct3;
  uint5_t dest;
  uint7_t opcode;
  // Derived control flags from decode
  uint1_t reg_wr;
  uint1_t mem_wr_byte_ens[4];
  uint1_t mem_rd;
  uint1_t mem_to_reg;
  uint1_t pc_plus4_to_reg;
  uint1_t exe_to_pc;
  int32_t signed_immediate;
  // Printf controls
  uint1_t print_rs1_read;
  uint1_t print_rs2_read;
} decoded_t;
decoded_t decode(uint32_t inst){
  decoded_t rv;
  rv.opcode = inst(6,0);
  rv.dest = inst(11, 7);
  rv.funct3 = inst(14, 12);
  rv.src1 = inst(19, 15);
  rv.src2 = inst(24, 20);
  if(rv.opcode==OP_ADD){
    // ADD
    rv.reg_wr = 1;
    rv.print_rs1_read = 1;
    rv.print_rs2_read = 1;
    printf("ADD: r%d + r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
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
      int12_t blt_offset;
      blt_offset = int12_uint1_12(blt_offset, imm12);
      blt_offset = int12_uint6_5(blt_offset, imm10_5);
      blt_offset = int12_uint4_1(blt_offset, imm4_1);
      blt_offset = int12_uint1_11(blt_offset, imm11);
      rv.signed_immediate = blt_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BLT: PC = r%d < r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BGE){
      // BGE
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BGE offset
      int12_t bge_offset;
      bge_offset = int12_uint1_12(bge_offset, imm12);
      bge_offset = int12_uint6_5(bge_offset, imm10_5);
      bge_offset = int12_uint4_1(bge_offset, imm4_1);
      bge_offset = int12_uint1_11(bge_offset, imm11);
      rv.signed_immediate = bge_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BGE: PC = r%d >= r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else if(rv.funct3==FUNCT3_BEQ){
      // BEQ
      uint1_t imm12 = inst(31);
      uint6_t imm10_5 = inst(30, 25);
      uint4_t imm4_1 = inst(11, 8);
      uint1_t imm11 = inst(7);
      // BEQ offset
      int12_t beq_offset;
      beq_offset = int12_uint1_12(beq_offset, imm12);
      beq_offset = int12_uint6_5(beq_offset, imm10_5);
      beq_offset = int12_uint4_1(beq_offset, imm4_1);
      beq_offset = int12_uint1_11(beq_offset, imm11);
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
      int12_t bne_offset;
      bne_offset = int12_uint1_12(bne_offset, imm12);
      bne_offset = int12_uint6_5(bne_offset, imm10_5);
      bne_offset = int12_uint4_1(bne_offset, imm4_1);
      bne_offset = int12_uint1_11(bne_offset, imm11);
      rv.signed_immediate = bne_offset;
      // Compare two regs
      rv.print_rs1_read = 1;
      rv.print_rs2_read = 1;
      // Execute stage does pc related math
      rv.exe_to_pc = 1;
      printf("BNE: PC = r%d != r%d ? PC+%d : PC+4;\n", rv.src1, rv.src2, rv.signed_immediate);
    }else {
      printf("Unsupported OP_BRANCH instruction: 0x%X\n", inst);
      unknown_op = 1;
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
    }else if(rv.funct3==FUNCT3_SRAI){
      // SRAI
      uint5_t shamt = imm11_0(4, 0);
      rv.signed_immediate = shamt;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("SRAI: r%d >> %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else if(rv.funct3==FUNCT3_XORI){
      // XOR
      rv.signed_immediate = imm11_0;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("XORI: r%d ^ %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    }else{
      printf("Unsupported OP_IMM instruction: 0x%X\n", inst);
      unknown_op = 1;
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
    if(rv.funct3==FUNCT3_LW_SW){
      // LW
      rv.mem_rd = 1;
      rv.mem_to_reg = 1;
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      // Store offset
      int12_t lw_offset = inst(31, 20);
      int32_t sign_extended_offset = lw_offset;
      rv.signed_immediate = sign_extended_offset;
      printf("LW: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    } else {
      printf("Unsupported OP_LOAD instruction: 0x%X\n", inst);
      unknown_op = 1;
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
      unknown_op = 1;
    }
  }else{
    printf("Unsupported instruction: 0x%X\n", inst);
    unknown_op = 1;
  }
  return rv;
}

// Exceute/ALU
typedef struct execute_t
{
  uint32_t result;
}execute_t;
execute_t execute(
  uint32_t pc, uint32_t pc_plus4, 
  decoded_t decoded, uint32_t reg1, uint32_t reg2)
{
  execute_t rv;
  if(decoded.opcode==OP_ADD){
    rv.result = reg1 + reg2;
    printf("ADD: %d + %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
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
    }else if(decoded.funct3==FUNCT3_BGE){
      int32_t pc_plus_imm = pc + decoded.signed_immediate;
      if((int32_t)reg1 >= (int32_t)reg2){
        rv.result = pc_plus_imm;
      } else {
        rv.result = pc_plus4;
      }
      printf("BGE: PC = %d >= %d ? 0x%X : PC+4 0x%X;\n", reg1, reg2, pc_plus_imm, pc_plus4);
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
    }else if(decoded.funct3==FUNCT3_SRAI){
      rv.result = ((int32_t)reg1) >> decoded.signed_immediate;
      printf("SRAI: %d >> %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }
  }else if(decoded.opcode==OP_JAL){
    rv.result = pc + decoded.signed_immediate;
    printf("JAL: PC = %d + %d = 0x%X\n", pc, decoded.signed_immediate, (int32_t)rv.result);
  }else if(decoded.opcode==OP_JALR){
    rv.result = decoded.signed_immediate + reg1;
    rv.result = int32_uint1_0(rv.result, 0); // rv.result[0] = 0;
    printf("JALR: PC = %d + %d = 0x%X\n", decoded.signed_immediate, reg1, (int32_t)rv.result);
  }else if(decoded.opcode==OP_LOAD){
    if(decoded.funct3==FUNCT3_LW_SW){
      rv.result = reg1 + decoded.signed_immediate;
      printf("LW: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
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

// CPU top level
uint32_t risc_v()
{
  // Program counter
  static uint32_t pc = 0;
  uint32_t pc_plus4 = pc + 4;
  printf("PC = 0x%X\n", pc);

  // Read instruction at PC
  uint32_t inst = inst_read(pc>>2);
  printf("Instruction: 0x%X\n", inst);

  // Decode the instruction to control signals
  decoded_t decoded = decode(inst);

  // Register file reads, from port0 and port1
  uint32_t rd_data1 = reg_read0(decoded.src1);
  uint32_t rd_data2 = reg_read1(decoded.src2);
  if(decoded.print_rs1_read){
    printf("Read RegFile[%d] = %d\n", decoded.src1, rd_data1);
  }
  if(decoded.print_rs2_read){
    printf("Read RegFile[%d] = %d\n", decoded.src2, rd_data2);
  }

  // Execute stage
  execute_t exe = execute(pc, pc_plus4, decoded, rd_data1, rd_data2);

  // Memory stage, assemble inputs
  mem_rw_in_t mem_rw_in;
  mem_rw_in.addr = exe.result; // TEMP addr always from execute module
  mem_rw_in.wr_data = rd_data2;
  mem_rw_in.wr_byte_ens = decoded.mem_wr_byte_ens;
  // Actual connection to memory read+write port
  uint32_t data_mem_rd_val = mem_read_write(mem_rw_in);
  if(decoded.mem_wr_byte_ens[0]){
    printf("Write Mem[0x%X] = %d\n", mem_rw_in.addr, mem_rw_in.wr_data);
  }
  if(decoded.mem_rd){
    printf("Read Mem[0x%X] = %d\n", mem_rw_in.addr, data_mem_rd_val);
  }  

  // Second half of reg file
  // Reg file write, assemble inputs
  reg_file_wr_in_t reg_wr_inputs;
  reg_wr_inputs.wr_en = decoded.reg_wr;
  reg_wr_inputs.wr_addr = decoded.dest;
  // Determine data to write back
  if(decoded.mem_to_reg){
    printf("Write RegFile: MemRd->Reg...\n");
    reg_wr_inputs.wr_data = data_mem_rd_val;
  }else if(decoded.pc_plus4_to_reg){
    printf("Write RegFile: PC+4->Reg...\n");
    reg_wr_inputs.wr_data = pc_plus4;
  }else{
    if(decoded.reg_wr)
      printf("Write RegFile: Execute Result->Reg...\n");
    reg_wr_inputs.wr_data = exe.result;
  }
  if(decoded.reg_wr){
    printf("Write RegFile[%d] = %d\n", decoded.dest, reg_wr_inputs.wr_data);
  }
  // Actual connection to reg file write port
  reg_write(reg_wr_inputs);

  // Branch/Increment PC
  if(decoded.exe_to_pc){
    printf("Next PC: Execute Result = 0x%X...\n", exe.result);
    pc = exe.result;
  }else{
    // Default next pc
    printf("Next PC: Default = 0x%X...\n", pc_plus4);
    pc = pc_plus4;
  }

  // Dummy output
  return pc;
}
