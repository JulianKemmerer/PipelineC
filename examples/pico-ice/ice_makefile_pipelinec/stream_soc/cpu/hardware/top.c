// Top level of stream soc cpu

// Board top level configuration, IO etc
#include "top.h"

// Devices attached to a CPU mem map module and interconnected in a dataflow network
#include "devices.c"

// Declare configuration of basic multi-cycle FSM RISC-V core
// Declare instruction and data memory with gcc compiled program
// also includes memory mapped IO
#include "text_mem_init.h" // from software make flow
#include "data_mem_init.h" // from software make flow
#define riscv_name              my_riscv_fsm
#define RISCV_IMEM_INIT         text_MEM_INIT
#define RISCV_IMEM_SIZE_BYTES   MY_IMEM_SIZE
#define RISCV_DMEM_INIT         data_MEM_INIT
#define RISCV_DMEM_SIZE_BYTES   MY_DMEM_SIZE
#define riscv_mem_map           my_mm_module
#define riscv_mem_map_regs_t    my_mm_regs_t
#define RISCV_IMEM_1_CYCLE
#define RISCV_DMEM_1_CYCLE
// Multi cycle is not a pipeline
#define RISCV_IMEM_NO_AUTOPIPELINE
#define RISCV_DMEM_NO_AUTOPIPELINE
// Declare register file RAM
#define RISCV_REGFILE_1_CYCLE
#include "risc-v/fsm_riscv_decl.h"

// Wire up instance of my_riscv_fsm CPU

MAIN_MHZ(cpu_top, MY_CPU_CLK_MHZ)
void cpu_top()
{
  // The registers to be memory mapped 
  static my_mm_regs_t my_mm_regs;  

  // Output 1b MMIO LED signal for green LED
  led_g = my_mm_regs.led;
  led_b = 1; // blue off

  // Red LED for hardware debug
  static uint1_t pc_out_of_range_reg;
  static uint1_t unknown_op_reg;
  static uint1_t mem_out_of_range_reg;
  led_r = 1; // default off
  led_r &= ~pc_out_of_range_reg;
  led_r &= ~unknown_op_reg;
  led_r &= ~mem_out_of_range_reg;

  // Instance of core
  uint1_t reset = ~pll_locked; // For for PLL to lock before releasing reset
  riscv_out_t out = my_riscv_fsm(reset, my_mm_regs);
  my_mm_regs = out.mm_regs_out;
  my_mm_regs.cpu_clock = cpu_clock;  

  // Debug regs sticky on so human can see single cycle pulse
  pc_out_of_range_reg |= out.pc_out_of_range;
  unknown_op_reg |= out.unknown_op;
  mem_out_of_range_reg |= out.mem_out_of_range;
  if(reset){
    pc_out_of_range_reg = 0;
    unknown_op_reg = 0;
    mem_out_of_range_reg = 0;
  }
}
