#pragma once
#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"
#include "ram.h"

// Register file size
#define NUM_REGS 32

// Need a RAM with two read ports and one write port
// Declare register file RAM
// Triple port, two read ports, one write
#ifdef RISCV_REGFILE_1_CYCLE
// 1 cycle latency like bram
DECL_RAM_TP_R_R_W_1(
  uint32_t,
  reg_file_ram,
  NUM_REGS,
  RAM_INIT_INT_ZEROS
)
#else
// Zero latency
DECL_RAM_TP_R_R_W_0(
  uint32_t,
  reg_file_ram,
  NUM_REGS,
  RAM_INIT_INT_ZEROS
)
#endif

// Split the_reg_file into three parts, 2 read ports, 1 write
typedef struct reg_file_out_t
{
  uint32_t rd_data1;
  uint32_t rd_data2;
}reg_file_out_t;
reg_file_out_t reg_file(
  uint5_t rd_addr1,
  uint5_t rd_addr2,
  uint5_t wr_addr,
  uint32_t wr_data,
  uint1_t wr_en
){
  wr_en &= (wr_addr!=0); // No writes to reg0, always 0
  reg_file_ram_out_t ram_out = reg_file_ram(rd_addr1, rd_addr2, 
                              wr_addr, wr_data, wr_en);
  reg_file_out_t reg_file_out;
  reg_file_out.rd_data1 = ram_out.rd_data0;
  reg_file_out.rd_data2 = ram_out.rd_data1;
  return reg_file_out;
}