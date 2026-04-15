// Top level of stream soc cpu
#include "uintN_t.h"
#include "stream/stream.h"
DECL_STREAM_TYPE(uint32_t)
#include "cdc.h" // CDC helpers for reset

// Board top level configuration, IO etc
#include "top.h"

// Devices attached to a CPU mem map module and interconnected in a dataflow network
#include "devices.c"

// Declare configuration of basic multi-cycle FSM RISC-V core
// Declare instruction and data memory with gcc compiled program
// also includes memory mapped IO
#include "text_mem_init.h" // from software make flow
#include "data_mem_init.h" // from software make flow
#define riscv_name fsm_riscv
#define RISCV_IMEM_INIT         text_MEM_INIT
#define RISCV_IMEM_SIZE_BYTES   IMEM_SIZE
#define RISCV_DMEM_INIT         data_MEM_INIT
#define RISCV_DMEM_SIZE_BYTES   DMEM_SIZE
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_regs_t    mm_regs_t
#define RISCV_IMEM_1_CYCLE
#define RISCV_DMEM_1_CYCLE
// Multi cycle is not a pipeline
#define RISCV_IMEM_NO_AUTOPIPELINE
#define RISCV_DMEM_NO_AUTOPIPELINE
// Declare register file RAM
#define RISCV_REGFILE_1_CYCLE
#include "risc-v/fsm_riscv_decl.h"

// Wire up instance of fsm_riscv CPU

MAIN_MHZ(cpu_top, CPU_CLK_MHZ)
void cpu_top(uint1_t areset) // TODO replace reset with global top level wire port
{
  // TODO drive or dont use reset during sim
  // Sync reset
  uint1_t reset = xil_cdc2_bit(areset);
  //uint1_t reset = 0;

  // Instance of core
  static mm_regs_t mm_regs; // The registers to be memory mapped  
  riscv_out_t out = fsm_riscv(reset, mm_regs);
  mm_regs = out.mm_regs_out;
  mm_regs.switches = sw;
  mm_regs.buttons = btn;
  mm_regs.cpu_clock = cpu_clock;

  // Output LEDs for hardware debug
  static uint1_t pc_out_of_range_reg;
  static uint1_t unknown_op_reg;
  static uint1_t mem_out_of_range_reg;
  leds = 0;
  leds |= (uint4_t)mm_regs.led << 0;
  leds |= (uint4_t)pc_out_of_range_reg << 1;
  leds |= (uint4_t)unknown_op_reg << 2;
  leds |= (uint4_t)mem_out_of_range_reg << 3;

  // Sticky on so human can see single cycle pulse
  pc_out_of_range_reg |= out.pc_out_of_range;
  unknown_op_reg |= out.unknown_op;
  mem_out_of_range_reg |= out.mem_out_of_range;
  if(reset){
    pc_out_of_range_reg = 0;
    unknown_op_reg = 0;
    mem_out_of_range_reg = 0;
  }
}

