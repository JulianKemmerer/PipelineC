#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"
#include "debug_port.h"
#include "ram.h"

// Combined instruction and data memory initialized from gcc compile
#define MEM_SIZE_IN_BYTES 2048
#define MEM_NUM_WORDS (MEM_SIZE_IN_BYTES/4)
#include "gcc_test/mem_init.h"
// Need a RAM with one read port for instructions, one r/w port for data mem
DECL_RAM_DP_RW_R_0(
  uint32_t,
  the_mem,
  MEM_NUM_WORDS,
  MEM_INIT
)

// Memory mapped IO addresses to drive hardware wires, ex. debug ports, devices
#include "mem_map.h"
// Debug ports for simulation
DEBUG_OUTPUT_DECL(uint1_t, halt) // Stop/done signal
DEBUG_OUTPUT_DECL(int32_t, main_return) // Output from main()
#include "leds/leds_port.c"
#include "frame_buffer.c"
typedef struct mem_map_out_t
{
  uint1_t addr_is_mapped;
  uint32_t rd_data;
}mem_map_out_t;
mem_map_out_t mem_map_module(
  uint32_t addr,
  uint32_t wr_data,
  uint1_t wr_en)
{
  // Outputs
  mem_map_out_t o;

  // In+out registers for frame buffer wires, for better fmax
  static uint1_t frame_buffer_wr_data_in_reg;
  static uint16_t frame_buffer_x_in_reg;
  static uint16_t frame_buffer_y_in_reg;
  static uint1_t frame_buffer_wr_enable_in_reg;
  static uint1_t frame_buffer_rd_data_out_reg;
  //
  static uint1_t line_bufs_line_sel_in_reg;
  static uint16_t line_bufs_x_in_reg;
  static uint1_t line_bufs_wr_data_in_reg;
  static uint1_t line_bufs_wr_enable_in_reg;
  static uint1_t line_bufs_rd_data_out_reg;

  // Connect frame buffer inputs from registers for better fmax
  frame_buffer_wr_data_in = frame_buffer_wr_data_in_reg;
  frame_buffer_x_in = frame_buffer_x_in_reg;
  frame_buffer_y_in = frame_buffer_y_in_reg;
  frame_buffer_wr_enable_in = frame_buffer_wr_enable_in_reg;
  //
  line_bufs_line_sel_in = line_bufs_line_sel_in_reg;
  line_bufs_x_in = line_bufs_x_in_reg;
  line_bufs_wr_data_in = line_bufs_wr_data_in_reg;
  line_bufs_wr_enable_in = line_bufs_wr_enable_in_reg;

  // Some defaults for single cycle pulses
  frame_buffer_wr_enable_in_reg = 0;
  line_bufs_wr_enable_in_reg = 0;

  if(addr==RETURN_OUTPUT_ADDR){
    // The return/halt debug signal
    o.addr_is_mapped = 1;
    o.rd_data = 0;
    if(wr_en){
      main_return = wr_data;
      halt = 1;
    }
  }else if(addr==LEDS_ADDR){
    // LEDs
    o.addr_is_mapped = 1;
    o.rd_data = leds;
    if(wr_en){
      leds = wr_data;
    }
  }else if(addr==FRAME_BUF_X_ADDR){
    // Frame buffer x
    o.addr_is_mapped = 1;
    o.rd_data = frame_buffer_x_in_reg;
    if(wr_en){
      frame_buffer_x_in_reg = wr_data;
    }
  }else if(addr==FRAME_BUF_Y_ADDR){
    // Frame buffer y
    o.addr_is_mapped = 1;
    o.rd_data = frame_buffer_y_in_reg;
    if(wr_en){
      frame_buffer_y_in_reg = wr_data;
    }
  }else if(addr==FRAME_BUF_DATA_ADDR){
    // Frame buffer data
    o.addr_is_mapped = 1;
    o.rd_data = frame_buffer_rd_data_out_reg;
    frame_buffer_wr_enable_in_reg = wr_en;
    if(wr_en){
      frame_buffer_wr_data_in_reg = wr_data;
    }
  }else if(addr==LINE_BUF_SEL_ADDR){
    // Line buf sel
    o.addr_is_mapped = 1;
    o.rd_data = line_bufs_line_sel_in_reg;
    if(wr_en){
      line_bufs_line_sel_in_reg = wr_data;
    }
  }else if(addr==LINE_BUF_X_ADDR){
    // Line buf x
    o.addr_is_mapped = 1;
    o.rd_data = line_bufs_x_in_reg;
    if(wr_en){
      line_bufs_x_in_reg = wr_data;
    }
  }else if(addr==LINE_BUF_DATA_ADDR){
    // Line buffer data
    o.addr_is_mapped = 1;
    o.rd_data = line_bufs_rd_data_out_reg;
    line_bufs_wr_enable_in_reg = wr_en;
    if(wr_en){
      line_bufs_wr_data_in_reg = wr_data;
    }
  }

  // Connect frame buffer outputs to registers for better fmax
  frame_buffer_rd_data_out_reg = frame_buffer_rd_data_out;
  //
  line_bufs_rd_data_out_reg = line_bufs_rd_data_out;

  return o;
}

// Split main memory the_mem into two parts,
// one read port for instructions, one r/w port for data mem
typedef struct mem_out_t
{
  uint32_t inst_read;
  uint32_t mem_read_write;
}mem_out_t;
typedef struct mem_rw_in_t{
  uint32_t addr;
  uint32_t wr_data;
  uint1_t wr_en;
}mem_rw_in_t;
DEBUG_OUTPUT_DECL(uint1_t, mem_out_of_range) // Exception, stop sim
mem_out_t mem(
  uint32_t rd_addr,
  mem_rw_in_t mem_rw
){
  // Check for write to memory mapped IO addresses
  mem_map_out_t mem_map_out = mem_map_module(
    mem_rw.addr,
    mem_rw.wr_data,
    mem_rw.wr_en);
  
  // Mem map write does not write actual RAM memory
  mem_rw.wr_en &= !mem_map_out.addr_is_mapped;

  // Convert byte addresses to 4-byte word address
  uint32_t mem_rw_word_index = mem_rw.addr >> 2;
  uint32_t rd_addr_word_index = rd_addr >> 2;

  // Sanity check, stop sim if out of range access
  if((mem_rw_word_index >= MEM_NUM_WORDS) & mem_rw.wr_en){
    mem_out_of_range = 1;
  }

  // The single RAM instance with connections splitting in two
  the_mem_outputs_t ram_out = the_mem(mem_rw_word_index, mem_rw.wr_data, mem_rw.wr_en, rd_addr);
  mem_out_t mem_out;
  mem_out.mem_read_write = ram_out.rd_data0;
  mem_out.inst_read = ram_out.rd_data1;

  // Mem map read comes from memory map module not RAM memory
  if(mem_map_out.addr_is_mapped){
    mem_out.mem_read_write = mem_map_out.rd_data;
  }

  return mem_out;
}
MAIN_SPLIT2(
  mem_out_t,
  mem,
  inst_read,
  uint32_t,
  uint32_t,
  mem_read_write,
  mem_rw_in_t,
  uint32_t
)
