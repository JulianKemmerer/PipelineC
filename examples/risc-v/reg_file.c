#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"
#include "ram.h"

// Register file size
#define NUM_REGS 32

// Need a RAM with two read ports and one write port
// Declare register file RAM
// Triple port, two read ports, one write
// Zero latency
DECL_RAM_TP_R_R_W_0(
  uint32_t,
  the_reg_file,
  NUM_REGS,
  RAM_INIT_INT_ZEROS
)

// Split the_reg_file into three parts, 2 read ports, 1 write
typedef struct reg_file_out_t
{
  uint32_t reg_read0;
  uint32_t reg_read1;
  uint1_t reg_write; // Dummy output
}reg_file_out_t;
typedef struct reg_file_wr_in_t{
  uint5_t wr_addr;
  uint32_t wr_data;
  uint1_t wr_en;
}reg_file_wr_in_t;
reg_file_out_t reg_file(
  uint5_t rd_addr0,
  uint5_t rd_addr1,
  reg_file_wr_in_t reg_write
){
  reg_write.wr_en &= (reg_write.wr_addr!=0); // No writes to reg0, always 0
  the_reg_file_out_t ram_out = the_reg_file(rd_addr0, rd_addr1, 
                              reg_write.wr_addr, reg_write.wr_data, reg_write.wr_en);
  reg_file_out_t reg_file_out;
  reg_file_out.reg_read0 = ram_out.rd_data0;
  reg_file_out.reg_read1 = ram_out.rd_data1;
  reg_file_out.reg_write = reg_write.wr_en; // Dummy output
  return reg_file_out;
}
MAIN_SPLIT3(
  reg_file_out_t,
  reg_file,
  reg_read0,
  uint5_t,
  uint32_t,
  reg_read1,
  uint5_t,
  uint32_t,
  reg_write,
  reg_file_wr_in_t,
  uint1_t
)