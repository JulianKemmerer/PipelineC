#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"

// RISC-V components
#include "risc-v.h"

// Include test gcc compiled program
#include "gcc_test/mem_init.h" // MEM_INIT,MEM_INIT_SIZE

// Declare memory map information
// Starts with shared with software memory map info
#include "gcc_test/mem_map.h" 
// Define inputs and outputs
typedef struct my_mmio_in_t{
  uint1_t button;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  uint1_t led;
}my_mmio_out_t;
// Define the hardware memory for those IO
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  // Outputs
  static riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  o.addr_is_mapped = 0; // since o is static regs
  // Memory muxing/select logic
  // Uses helper comparing word address and driving a variable
  WORD_MM_ENTRY(o, LEDS_ADDR, o.outputs.led)
  return o;
}

// Declare a RISCV core type using memory info
#define riscv_name              my_riscv
#define RISCV_MEM_INIT          MEM_INIT // from gcc_test
#define RISCV_MEM_SIZE_BYTES    MEM_INIT_SIZE // from gcc_test
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#include "risc-v_decl.h"

// Set clock of instances of CPU
#define CPU_CLK_MHZ 40.0
MAIN_MHZ(risc_v_cores, CPU_CLK_MHZ)

// LEDs for demo
#include "leds/leds_port.c"

#define NUM_CORES 4
void risc_v_cores()
{
  // CPU instances with LED output connected to LED port
  leds = 0;
  uint32_t i;
  for (i = 0; i < NUM_CORES; i+=1)
  {
    my_mmio_in_t in; // Disconnected for now
    my_mmio_out_t out = my_riscv(in);
    leds |= ((uint4_t)out.led << i);
  }
}