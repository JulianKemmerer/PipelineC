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

// Memory mapped IO addresses to drive debug ports
#include "mem_map.h"
// Debug ports for simulation
DEBUG_OUTPUT_DECL(uint1_t, halt) // Stop/done signal
DEBUG_OUTPUT_DECL(int32_t, main_return) // Output from main()

// Drive LEDs with memory mapped io
#include "leds/leds_port.c"

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
mem_out_t mem(
  uint32_t rd_addr,
  mem_rw_in_t mem_rw
){
  // Check for write to memory mapped IO addresses
  if(mem_rw.wr_en){
    // Mem map io does not write actual RAM memory
    if(mem_rw.addr==RETURN_OUTPUT_ADDR){
      // The return/halt signal
      main_return = mem_rw.wr_data;
      halt = 1;
      mem_rw.wr_en = 0;
    } else if(mem_rw.addr==LEDS_ADDR){
      // LEDs
      leds = mem_rw.wr_data;
      mem_rw.wr_en = 0;
    }
  }

  // Convert byte addresses to 4-byte word address
  uint32_t mem_rw_word_index = mem_rw.addr >> 2;
  uint32_t rd_addr_word_index = rd_addr >> 2;
  // The single RAM instance with connections splitting in two
  the_mem_outputs_t ram_out = the_mem(mem_rw_word_index, mem_rw.wr_data, mem_rw.wr_en, rd_addr);
  mem_out_t mem_out;
  mem_out.mem_read_write = ram_out.rd_data0;
  mem_out.inst_read = ram_out.rd_data1;
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