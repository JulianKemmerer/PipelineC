// Top level of stream soc cpu
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"
DECL_STREAM_TYPE(uint32_t)

// Top level configuration, IO etc
#include "top.h"

// Devices attached to the CPU
#include "devices.c"

// TODO dataflow interconnecting devices

// Code implementing memory map for devices attached to the CPU
#include "mem_map.c"

// Base multi cycle FSM for this RISC-V CPU
#include "fsm_riscv.c"

// Wire up instance of fsm_riscv CPU
// LEDs for demo
#include "leds/leds_port.c"
// CDC for reset
#include "cdc.h"
// FFT speed measure connected to debug chipscope reg
MAIN_MHZ(cpu_top, 62.5)
void cpu_top(uint1_t areset) // TODO replace reset with global top level wire port
{
  // TODO drive or dont use reset during sim
  // Sync reset
  uint1_t reset = xil_cdc2_bit(areset);
  //uint1_t reset = 0;

  // Clock counter for debug
  static uint32_t cpu_clock;

  // Instance of core
  my_mmio_in_t in;
  in.status.button = 0; // TODO
  in.status.cpu_clock = cpu_clock;
  riscv_out_t out = fsm_riscv(reset, in);

  // Output LEDs for hardware debug
  static uint1_t pc_out_of_range_reg;
  static uint1_t unknown_op_reg;
  static uint1_t mem_out_of_range_reg;
  leds = 0;
  leds |= (uint4_t)out.mem_map_outputs.ctrl.led << 0;
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
  cpu_clock += 1;
}

