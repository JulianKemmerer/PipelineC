#pragma MAIN risc_v
#include "uintN_t.h"
#include "intN_t.h"

#define DATA_MEM_SIZE 16
#define INST_MEM_SIZE 16
#define NUM_REGS 16

#define OP_ADD 0b0110011
#define OP_JAL 0b1101111

// Sorta decode+control
typedef struct decoded_t
{
  uint5_t src2;
  uint5_t src1;
  uint5_t dest;
  uint7_t opcode;
  // Derived control flags from decode
  uint1_t reg_wr;
  uint1_t mem_wr;
  uint1_t mem_to_reg;
  uint1_t pc_plus4_to_reg;
  int32_t signed_immediate;
} decoded_t;

decoded_t decode(uint32_t inst)
{
  decoded_t rv;
  rv.opcode = inst(6,0);
  if(rv.opcode==OP_ADD)
  {
    // ADD
    rv.src2 = inst(24, 20);
    rv.src1 = inst(19, 15);
    rv.dest = inst(11, 7);
    rv.reg_wr = 1;
    printf("ADD: r%d + r%d -> r%d \n", rv.src1, rv.src2, rv.dest);
  }
  else if(rv.opcode==OP_JAL)
  {
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
    rv.dest = inst(11, 7);
    rv.pc_plus4_to_reg = 1;
    rv.reg_wr = 1; //
    printf("JAL: PC+=%d, PC+4 -> r%d \n", rv.signed_immediate, rv.dest);
  }
  else
  {
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
  // TODO resource sharing
  if(decoded.opcode==OP_ADD)
  {
    rv.result = reg1 + reg2;
    printf("ADD: %d + %d = %d \n", reg1, reg2, rv.result);
  }
  else if(decoded.opcode==OP_JAL)
  {
    rv.result = pc + decoded.signed_immediate;
    printf("JAL: PC %d + %d = %d\n", pc, decoded.signed_immediate, (int32_t)rv.result);
  }
  return rv;
}

uint32_t risc_v()
{
  // Program counter
  static uint32_t pc;
  uint32_t pc_plus4 = pc + 4;
  printf("PC = %d\n", pc);

  // Read instruction at PC
  static uint32_t inst_mem[INST_MEM_SIZE] = {
    // ADD r3+r2->r2
    0b00000000001100010000000100110011,
    // JAL to PC-=4, return linked in reg1
    0b11111111110111111111000011101111
  };
  uint32_t inst = inst_mem[pc>>2];
  printf("Instruction: 0x%X\n", inst);

  // Decode the instruction to control signals
  decoded_t decoded = decode(inst);

  // Register file
  static uint32_t reg_file[NUM_REGS] = {
    0, // x0 = Zero
    0, // x1 = Used for return Addr
    1, // Test
    1  // Test
  };
  // Reg file reads
  uint32_t rd_data1 = reg_file[decoded.src1];
  uint32_t rd_data2 = reg_file[decoded.src2];
  printf("Read RegFile[%d] = %d\n", decoded.src1, rd_data1);
  printf("Read RegFile[%d] = %d\n", decoded.src2, rd_data2);

  // Execute stage
  execute_t exe = execute(pc, decoded, rd_data1, rd_data2);

  // Memory stage
  static uint32_t data_mem[DATA_MEM_SIZE];
  uint32_t data_mem_rd_val = data_mem[exe.result];
  printf("Read DataMem[%d] = %d\n", exe.result, data_mem_rd_val);
  if(decoded.mem_wr)
  {
    printf("Write DataMem[%d] = %d\n", exe.result, rd_data2);
    data_mem[exe.result] = rd_data2;
  }

  // Second half of reg file
  // Determine data to write back
  uint32_t wr_data;
  if(decoded.mem_to_reg)
  {
    printf("Write Data: Mem->Reg...\n");
    wr_data = data_mem_rd_val;
  }
  else if(decoded.pc_plus4_to_reg)
  {
    printf("Write Data: PC+4->Reg...\n");
    wr_data = pc_plus4;
  }
  else
  {
    printf("Write Data: Execute Result...\n");
    wr_data = exe.result;
  }
  // Reg file write
  if(decoded.reg_wr)
  {
    printf("Write RegFile[%d] = %d\n", decoded.dest, wr_data);
    reg_file[decoded.dest] = wr_data;
  }

  // Branch/Increment PC
  if(decoded.opcode==OP_JAL)
  {
    printf("Next PC Execute Result = %d...\n", exe.result);
    pc = exe.result;
  }
  else
  {
    // Default next pc
    printf("Next PC: Default = %d...\n", pc_plus4);
    pc = pc_plus4;
  }  

  // Dummy output
  return pc;
}


/*uint7_t funct7;
  uint5_t rs2;
  uint5_t rs1;
  uint3_t funct3;
  uint5_t rd;
  uint7_t opcode;*/
  /*rv.funct7 = inst(31, 25);
  rv.rs2 = inst(24, 20);
  rv.rs1 = inst(19, 15);
  rv.funct3 = inst(14, 12);
  rv.rd = inst(11, 7);
  rv.opcode = inst(6, 0);*/