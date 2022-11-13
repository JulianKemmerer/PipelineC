
#include "uintN_t.h"
//#pragma PART "xc7a35ticsg324-1l" 

// Some simple RAMs can be derived from static local array variables
// https://github.com/JulianKemmerer/PipelineC/wiki/Automatically-Generated-Functionality#rams
// However, many other RAM types, ex. dual port, are currently not built in yet
// https://github.com/JulianKemmerer/PipelineC/issues/93
// This demo shows how to use the a RAM defined from ram.h
// (that are very similar to built in RAMs)
#include "ram.h"

// Declare a RAM
// dual port, first port is read+write,
// second port is read only
// 1 cycle of latency
#define RAM_SIZE (640*480)
DECL_RAM_DP_RW_R_1(
  uint24_t, // Element type
  the_ram, // RAM function name
  RAM_SIZE, // Number of elements
  RAM_INIT_INT_ZEROS // Initial value VHDL string, from ram.h
)

// Demo function writing zeros, then ones repeatedly to RAM
// Read only port is connected as dummy output
#pragma MAIN my_func
uint24_t my_func()
{
  static uint32_t rdaddr = 0; // Read address
  static uint32_t rwaddr = 0; // Write+read address
  static uint24_t wdata = 0; // Write data, start writing zeros

  // The RAM instance
  uint1_t wr_en = 1; // RW port always writing (not reading)
  uint1_t rw_valid = 1; // Always have valid RAM inputs
  uint1_t rw_out_en = 1; // Always ready for RAM outputs
  uint1_t rd_valid = 1; // Always have valid RAM inputs
  uint1_t rd_out_en = 1; // Always ready for RAM outputs
  the_ram_outputs_t ram_out = the_ram(
    rwaddr, wdata, wr_en, rw_valid, rw_out_en, 
    rdaddr, rd_valid, rd_out_en);

  // Test pattern: move to next address, 
  // flipping data bits once starting over
  if(rwaddr < (RAM_SIZE-1)){
    rwaddr += 1;
  }else{
    rwaddr = 0;
    wdata = !wdata;
  }
  if(rdaddr < (RAM_SIZE-1)){
    rdaddr += 1;
  }else{
    rdaddr = 0;
  }

  // Dummy second port always reading
  // connected to output
  return ram_out.rd_data1;
}