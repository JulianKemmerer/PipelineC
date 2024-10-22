#include "compiler.h"
#pragma PART "xc7a35ticsg324-1l"
#pragma MAIN main
#include "uintN_t.h"
#include "ram.h"

DECL_STREAM_RAM_DP_W_R_1(
  uint32_t, ram1k, 1024, RAM_INIT_INT_ZEROS
)

typedef struct test_out_t{
  uint1_t rd_in_ready;
  uint32_t rd_addr_out;
  uint32_t rd_data_out; 
  uint1_t rd_out_valid;
  uint1_t wr_in_ready;
  uint32_t wr_addr_out;
  uint32_t wr_data_out; 
  uint1_t wr_out_valid; 
}test_out_t;
test_out_t main(
  uint32_t rd_addr_in,
  uint1_t rd_in_valid,
  uint1_t rd_out_ready,
  uint32_t wr_addr_in,
  uint32_t wr_data_in,
  uint1_t wr_in_valid,
  uint1_t wr_out_ready
){

  RAM_DP_W_R_1_STREAM(uint32_t, ram1k, my_ram)

  // Connect test IO
  test_out_t o;
  my_ram_rd_addr_in = rd_addr_in;
  my_ram_rd_in_valid = rd_in_valid;
  my_ram_rd_out_ready = rd_out_ready;
  my_ram_wr_addr_in = wr_addr_in;
  my_ram_wr_data_in = wr_data_in;
  my_ram_wr_in_valid = wr_in_valid;
  my_ram_wr_out_ready = wr_out_ready;
  o.rd_in_ready = my_ram_rd_in_ready;
  o.rd_addr_out = my_ram_rd_addr_out;
  o.rd_data_out = my_ram_rd_data_out; 
  o.rd_out_valid = my_ram_rd_out_valid;
  o.wr_in_ready = my_ram_wr_in_ready;
  o.wr_addr_out = my_ram_wr_addr_out;
  o.wr_data_out = my_ram_wr_data_out; 
  o.wr_out_valid = my_ram_wr_out_valid; 
  return o;
}

