#pragma MAIN risc_v
#include "uintN_t.h"
#include "intN_t.h"

// TODO resource sharing + more in decode logic to control fewer resources

// Register file read+write ports
#include "reg_file.c"

// Combined instruction and data memory ports
#include "mem.c"

// OPCODES and such
#define OP_ADD   0b0110011
#define OP_AUIPC 0b0010111
#define OP_IMM   0b0010011
#define OP_JAL   0b1101111
#define OP_JALR  0b1100111
#define OP_LOAD  0b0000011
#define OP_STORE 0b0100011
#define FUNCT3_ADDI  0b000
#define FUNCT3_LW_SW 0b010

// Sorta decode+control
typedef struct decoded_t{
  uint5_t src2;
  uint5_t src1;
  uint3_t funct3;
  uint5_t dest;
  uint7_t opcode;
  // Derived control flags from decode
  uint1_t reg_wr;
  uint1_t mem_wr;
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
    int20_t imm31_12 = inst(31, 12);
    rv.signed_immediate = int32_uint20_12(0, imm31_12);
    rv.reg_wr = 1;
    printf("AUIPC: PC + %d -> r%d \n", rv.signed_immediate, rv.dest);
  }else if(rv.opcode==OP_IMM){
    int12_t imm11_0 = inst(31, 20);
    rv.signed_immediate = imm11_0;
    if(rv.funct3==FUNCT3_ADDI){
      // ADDI
      rv.reg_wr = 1;
      rv.print_rs1_read = 1;
      printf("ADDI: r%d + %d -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    } else {
      printf("Unsupported OP_IMM instruction: 0x%X\n", inst);
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
    int32_t sign_extended_offset = jal_offset;
    rv.signed_immediate = sign_extended_offset;
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
    int32_t sign_extended_offset = jalr_offset;
    rv.signed_immediate = sign_extended_offset;
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
      rv.print_rs1_read = 1;
      // Store offset
      int12_t lw_offset = inst(31, 20);
      int32_t sign_extended_offset = lw_offset;
      rv.signed_immediate = sign_extended_offset;
      printf("LW: addr = r%d + %d, mem[addr] -> r%d \n", rv.src1, rv.signed_immediate, rv.dest);
    } else {
      printf("Unsupported OP_LOAD instruction: 0x%X\n", inst);
    }
  }else if(rv.opcode==OP_STORE){
    if(rv.funct3==FUNCT3_LW_SW){
      // SW
      rv.mem_wr = 1;
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
      printf("SW: addr = r%d + %d, mem[addr] <- r%d \n", rv.src1, rv.signed_immediate, rv.src2);
    } else {
      printf("Unsupported OP_STORE instruction: 0x%X\n", inst);
    }
  }else{
    printf("Unsupported instruction: 0x%X\n", inst);
  }
  
  return rv;
}

typedef struct execute_t
{
  uint32_t result;
}execute_t;
execute_t execute(uint32_t pc, decoded_t decoded, uint32_t reg1, uint32_t reg2)
{
  execute_t rv;
  if(decoded.opcode==OP_ADD){
    rv.result = reg1 + reg2;
    printf("ADD: %d + %d = %d -> r%d \n", reg1, reg2, rv.result, decoded.dest);
  }else if(decoded.opcode==OP_AUIPC){
    rv.result = pc + decoded.signed_immediate;
    printf("AUIPC: PC %d + %d = %d -> r%d\n", pc, decoded.signed_immediate, (int32_t)rv.result, decoded.dest);
  }else if(decoded.opcode==OP_IMM){
    if(decoded.funct3==FUNCT3_ADDI){
      rv.result = reg1 + decoded.signed_immediate;
      printf("ADDI: %d + %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }
  }else if(decoded.opcode==OP_JAL){
    rv.result = pc + decoded.signed_immediate;
    printf("JAL: PC = %d + %d = %d\n", pc, decoded.signed_immediate, (int32_t)rv.result);
  }else if(decoded.opcode==OP_JALR){
    rv.result = decoded.signed_immediate + reg1;
    rv.result = int32_uint1_0(rv.result, 0); // rv.result[0] = 0;
    printf("JALR: PC = %d + %d = %d\n", decoded.signed_immediate, reg1, (int32_t)rv.result);
  }else if(decoded.opcode==OP_LOAD){
    if(decoded.funct3==FUNCT3_LW_SW){
      rv.result = reg1 + decoded.signed_immediate;
      printf("LW: addr = %d + %d = %d, mem[0x%X] -> r%d \n", reg1, decoded.signed_immediate, rv.result, rv.result, decoded.dest);
    }
  }else if(decoded.opcode==OP_STORE){
    if(decoded.funct3==FUNCT3_LW_SW){
      rv.result = reg1 + decoded.signed_immediate;
      printf("SW: addr = %d + %d = %d, mem[0x%X] <- %d \n", reg1, decoded.signed_immediate, rv.result, rv.result, reg2);
    }
  }
  return rv;
}

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
  execute_t exe = execute(pc, decoded, rd_data1, rd_data2);

  // Memory stage, assemble inputs
  mem_rw_in_t mem_rw_in;
  mem_rw_in.addr = exe.result; // TEMP addr always from execute module
  mem_rw_in.wr_data = rd_data2;
  mem_rw_in.wr_en = decoded.mem_wr;
  // Actual connection to memory read+write port
  uint32_t data_mem_rd_val = mem_read_write(mem_rw_in);
  if(decoded.mem_wr){
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