#pragma PART "xc7a35ticsg324-1l"
#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"

// Base RISCV components
#include "risc-v.h"

// Configure CPU:
//  Clock
#define CPU_CLK_MHZ 40.0
MAIN_MHZ(risc_v, CPU_CLK_MHZ)
//  Program
#include "gcc_test/mem_init.h"
#define RISCV_MEM_INIT MEM_INIT
#define RISCV_MEM_SIZE_BYTES 2048
//  Memory mapped IO modules to drive hardware wires, ex. debug ports, devices
#include "mem_map.c"

// Combined instruction and data memory w/ ports
// Also includes memory mapped IO
#include "mem_decl.h"

// CPU top level
uint32_t risc_v()
{
  // Program counter
  static uint32_t pc = 0;
  uint32_t pc_plus4 = pc + 4;
  printf("PC = 0x%X\n", pc);

  // Shared instruction and data memory
  //  Data memory signals are not driven until later
  //  but are used now, requiring FEEDBACK pragma
  uint32_t mem_addr;
  uint32_t mem_wr_data;
  uint1_t mem_wr_byte_ens[4];
  #pragma FEEDBACK mem_addr
  #pragma FEEDBACK mem_wr_data
  #pragma FEEDBACK mem_wr_byte_ens
  riscv_mem_out_t mem_out = riscv_mem(
    pc>>2, // Instruction word read address based on PC
    mem_addr, // Main memory read/write address
    mem_wr_data, // Main memory write data
    mem_wr_byte_ens // Main memory write data byte enables
  );

  // Decode the instruction to control signals
  printf("Instruction: 0x%X\n", mem_out.inst);
  decoded_t decoded = decode(mem_out.inst);

  // Register file reads and writes
  //  Register file write signals are not driven until later
  //  but are used now, requiring FEEDBACK pragma
  uint5_t reg_wr_addr;
  uint32_t reg_wr_data;
  uint1_t reg_wr_en;
  #pragma FEEDBACK reg_wr_addr
  #pragma FEEDBACK reg_wr_data
  #pragma FEEDBACK reg_wr_en  
  reg_file_out_t reg_file_out = reg_file(
    decoded.src1, // First read port address
    decoded.src2, // Second read port address
    reg_wr_addr, // Write port address
    reg_wr_data, // Write port data
    reg_wr_en // Write enable
  );
  if(decoded.print_rs1_read){
    printf("Read RegFile[%d] = %d\n", decoded.src1, reg_file_out.rd_data1);
  }
  if(decoded.print_rs2_read){
    printf("Read RegFile[%d] = %d\n", decoded.src2, reg_file_out.rd_data2);
  }

  // Execute stage
  execute_t exe = execute(
    pc, pc_plus4, 
    decoded, 
    reg_file_out.rd_data1, reg_file_out.rd_data2
  );

  // Memory stage, drive inputs (FEEDBACK)
  mem_addr = exe.result; // addr always from execute module, not always used
  mem_wr_data = reg_file_out.rd_data2;
  mem_wr_byte_ens = decoded.mem_wr_byte_ens;
  if(decoded.mem_wr_byte_ens[0]){
    printf("Write Mem[0x%X] = %d\n", mem_addr, mem_wr_data);
  }
  if(decoded.mem_rd){
    printf("Read Mem[0x%X] = %d\n", mem_addr, mem_out.rd_data);
  }  

  // Reg file write back, drive inputs (FEEDBACK)
  reg_wr_en = decoded.reg_wr;
  reg_wr_addr = decoded.dest;
  reg_wr_data = exe.result; // Default needed for FEEDBACK
  // Determine data to write back
  if(decoded.mem_to_reg){
    printf("Write RegFile: MemRd->Reg...\n");
    reg_wr_data = mem_out.rd_data;
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
