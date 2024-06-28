#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"

// RISC-V components
#include "risc-v.h"

// Include test gcc compiled program
#include "gcc_test/text_mem_init.h"
#include "gcc_test/data_mem_init.h"

// Declare memory map information
// Starts with shared with software memory map info
#include "gcc_test/mem_map.h" 
// Define inputs and outputs
typedef struct my_mmio_in_t{
  uint1_t button;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  uint32_t return_value;
  uint1_t halt;
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
  WORD_MM_ENTRY(o, THREAD_ID_RETURN_OUTPUT_ADDR, o.outputs.return_value)
  o.outputs.halt = wr_byte_ens[0] & (addr==THREAD_ID_RETURN_OUTPUT_ADDR);
  WORD_MM_ENTRY(o, LED_ADDR, o.outputs.led)
  return o;
}

// Declare a RISCV core type using memory info
#define riscv_name              my_riscv
#define RISCV_IMEM_INIT         text_MEM_INIT // from gcc_test/
#define RISCV_IMEM_SIZE_BYTES   IMEM_SIZE     // from gcc_test/
#define RISCV_DMEM_INIT         data_MEM_INIT // from gcc_test/
#define RISCV_DMEM_SIZE_BYTES   DMEM_SIZE     // from gcc_test/
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#include "multi_cycle_risc-v_decl.h"

// Set clock of instances of CPU
#define CPU_CLK_MHZ 60.0
MAIN_MHZ(my_top, CPU_CLK_MHZ)

// LEDs for demo
#include "leds/leds_port.c"

// Debug output ports for sim and hardware
#include "debug_port.h"
DEBUG_OUTPUT_DECL(uint1_t, unknown_op) // Unknown instruction
DEBUG_OUTPUT_DECL(uint1_t, mem_out_of_range) // Exception, stop sim
DEBUG_OUTPUT_DECL(uint1_t, halt) // Stop/done signal
DEBUG_OUTPUT_DECL(int32_t, main_return) // Output from main()

void my_top()
{
  // Instance of core
  my_mmio_in_t in; // Disconnected for now
  my_riscv_out_t out = my_riscv(in);

  // Sim debug
  unknown_op = out.unknown_op;
  mem_out_of_range = out.mem_out_of_range;
  halt = out.mem_map_outputs.halt;
  main_return = out.mem_map_outputs.return_value;

  // Output LEDs for hardware debug
  leds = 0;
  leds |= (uint4_t)out.mem_map_outputs.led << 0;
  leds |= (uint4_t)mem_out_of_range << 1;
  leds |= (uint4_t)unknown_op << 2;
}