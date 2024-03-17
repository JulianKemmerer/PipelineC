#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"

// RISC-V components
#include "risc-v.h"

// Include test gcc compiled program
#include "gcc_test/mem_init.h"
#include "gcc_test/mem_map.h"

// LEDs for demo
#include "leds/leds_port.c"

// Declare a RISCV core type
#define riscv_name my_riscv
#define RISCV_MEM_INIT MEM_INIT
#define RISCV_MEM_SIZE_BYTES MEM_INIT_SIZE
#define riscv_mem_map my_mem_map_module
mem_map_out_t my_mem_map_module(
  uint32_t addr,
  uint32_t wr_data,
  uint1_t wr_byte_ens[4]
){
  // Outputs
  mem_map_out_t o;
  // Memory muxing/select logic
  if(addr==RETURN_OUTPUT_ADDR){
    // The return/halt debug signal
    o.addr_is_mapped = 1;
    o.rd_data = 0;
    if(wr_byte_ens[0]){
      //main_return = wr_data;
      //halt = 1;
    }
  }
  WORD_MM_ENTRY(LEDS_ADDR, leds)
  return o;
}
#include "risc-v_instance.h"

// Set clock of instances of CPU
#define CPU_CLK_MHZ 40.0
MAIN_MHZ(risc_v, CPU_CLK_MHZ)
uint32_t risc_v()
{
  return my_riscv();
}