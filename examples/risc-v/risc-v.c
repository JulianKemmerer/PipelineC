#pragma MAIN risc_v
#include "uintN_t.h"
#include "intN_t.h"

// TODO resource sharing + more in decode logic to control fewer resources

// Register file read+write ports
#include "reg_file.c"

// Combined instruction and data memory ports
#include "mem.c"

// OPCODES and such
#define OP_ADD 0b0110011
#define OP_JAL 0b1101111
#define OP_IMM 0b0010011
#define OP_AUIPC 0b0010111
#define FUNCT3_ADDI 0b000

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
  int32_t signed_immediate;
  // Printf controls
  uint1_t print_reg_reads;
} decoded_t;
decoded_t decode(uint32_t inst){
  decoded_t rv;
  rv.opcode = inst(6,0);
  rv.dest = inst(11, 7);
  if(rv.opcode==OP_ADD){
    // ADD
    rv.src2 = inst(24, 20);
    rv.src1 = inst(19, 15);
    rv.reg_wr = 1;
    rv.print_reg_reads = 1;
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
    rv.src1 = inst(19, 15);
    rv.funct3 = inst(14, 12);
    if(rv.funct3==FUNCT3_ADDI){
      // ADDI
      rv.reg_wr = 1;
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
    int21_t offset;
    offset = int21_uint1_20(offset, imm20);
    offset = int21_uint10_1(offset, imm10_1);
    offset = int21_uint1_11(offset, imm11);
    offset = int21_uint8_12(offset, immm19_12);
    int32_t sign_extended_offset = offset;
    rv.signed_immediate = sign_extended_offset;
    // And link
    rv.pc_plus4_to_reg = 1;
    rv.reg_wr = 1; //
    printf("JAL: PC+=%d, PC+4 -> r%d \n", rv.signed_immediate, rv.dest);
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
  }else if(decoded.opcode==OP_IMM){
    if(decoded.funct3==FUNCT3_ADDI){
      rv.result = reg1 + decoded.signed_immediate;
      printf("ADDI: %d + %d = %d -> r%d \n", reg1, decoded.signed_immediate, rv.result, decoded.dest);
    }
  }else if(decoded.opcode==OP_JAL){
    rv.result = pc + decoded.signed_immediate;
    printf("JAL: PC = %d + %d = %d\n", pc, decoded.signed_immediate, (int32_t)rv.result);
  }else if(decoded.opcode==OP_AUIPC){
    rv.result = pc + decoded.signed_immediate;
    printf("AUIPC: PC %d + %d = %d -> r%d\n", pc, decoded.signed_immediate, (int32_t)rv.result, decoded.dest);
  }
  return rv;
}

uint32_t risc_v()
{
  // Program counter
  static uint32_t pc = 0;
  uint32_t pc_plus4 = pc + 4;
  printf("PC = %d\n", pc);

  // Read instruction at PC
  uint32_t inst = inst_read(pc>>2);
  printf("Instruction: 0x%X\n", inst);

  // Decode the instruction to control signals
  decoded_t decoded = decode(inst);

  // Register file reads, from port0 and port1
  uint32_t rd_data1 = reg_read0(decoded.src1);
  uint32_t rd_data2 = reg_read1(decoded.src2);
  if(decoded.print_reg_reads){
    printf("Read RegFile[%d] = %d\n", decoded.src1, rd_data1);
    printf("Read RegFile[%d] = %d\n", decoded.src2, rd_data2);
  }

  // Execute stage
  execute_t exe = execute(pc, decoded, rd_data1, rd_data2);

  // Memory stage, assemble inputs
  mem_rw_in_t mem_rw_in;
  // TEMP addr always from execute module
  if(decoded.mem_rd | mem_rw_in.wr_en){
    mem_rw_in.addr = exe.result; 
    if(mem_rw_in.wr_en){
      mem_rw_in.wr_data = rd_data2;
      mem_rw_in.wr_en = decoded.mem_wr;
      printf("Write Mem[%d] = %d\n", mem_rw_in.addr, mem_rw_in.wr_data);
    }
  }  
  // Actual connection to memory read+write port
  uint32_t data_mem_rd_val = mem_read_write(mem_rw_in);
  if(decoded.mem_rd){
      printf("Read Mem[%d] = %d\n", mem_rw_in.addr, data_mem_rd_val);
  }  

  // Second half of reg file
  // Reg file write, assemble inputs
  reg_file_wr_in_t reg_wr_inputs;
  reg_wr_inputs.wr_en = decoded.reg_wr;
  reg_wr_inputs.wr_addr = decoded.dest;
  // Determine data to write back
  if(decoded.reg_wr){
    if(decoded.mem_to_reg){
      printf("Write RegFile: MemRd->Reg...\n");
      reg_wr_inputs.wr_data = data_mem_rd_val;
    }else if(decoded.pc_plus4_to_reg){
      printf("Write RegFile: PC+4->Reg...\n");
      reg_wr_inputs.wr_data = pc_plus4;
    }else{
      printf("Write RegFile: Execute Result->Reg...\n");
      reg_wr_inputs.wr_data = exe.result;
    }
    printf("Write RegFile[%d] = %d\n", decoded.dest, reg_wr_inputs.wr_data);
  }
  // Actual connection to reg file write port
  reg_write(reg_wr_inputs);

  // Branch/Increment PC
  if(decoded.opcode==OP_JAL){
    printf("Next PC: Execute Result = %d...\n", exe.result);
    pc = exe.result;
  }else{
    // Default next pc
    printf("Next PC: Default = %d...\n", pc_plus4);
    pc = pc_plus4;
  }

  // Dummy output
  return pc;
}