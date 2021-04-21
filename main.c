// xc7a35ticsg324-1l     Artix 7 (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xcvu33p-fsvh2104-2L-e Virtex Ultrascale Plus
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 5CGXFC9E7F35C8        Cyclone 5 GX
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G
// ICE40UP5K-SG48        ICE40UP
#pragma PART "xcvu9p-flgb2104-2-i"

// Most recent (and more likely working) examples towards the bottom of list \/
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/fosix/main_bram_loopback.c"
//#include "examples/fir.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/blink.c"
//#include "examples/clock_crossing.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
//#include "examples/arty/src/ddr3/mig_app.c"
//#include "examples/arty/src/eth/loopback_app.c"
//#include "examples/arty/src/eth/work_app.c"
//#include "examples/spw_pkg_guard.c"
//#include "examples/arty/src/mnist/neural_network_fsm.c"
//#include "examples/littleriscy/riscv.c"
#include "examples/NexusProofOfWork/NXSTest_syn.c"
//#include "examples/NexusProofOfWork/NXSTest_syn_inlined.c"

/*
#pragma MAIN_MHZ main 1000.0
float main(float x, float y)
{
  return x+y;
}
*/
//#include "uintN_t.h"
// Given timing data
//#pragma MAIN_MHZ main 250.0   // ~Between 61 and 109
/*
Pipeline Map:
\/ Delay units
0:   ['add10[main_c_l66_c16_4a22]', 'add5[main_c_l65_c16_6ca3]']
...
89:  ['add10[main_c_l66_c16_4a22]', 'add5[main_c_l65_c16_6ca3]']
90:  ['add10[main_c_l66_c16_4a22]', 'add5[main_c_l65_c16_6ca3]']
91:  ['add10[main_c_l66_c16_4a22]']
...
161: ['add10[main_c_l66_c16_4a22]']
162: ['BIN_OP_PLUS[main_c_l67_c10_dbcf]']
...
191: ['BIN_OP_PLUS[main_c_l67_c10_dbcf]']
*/
/*
// Each adder is 3.016 ns = 331.5 MHz

// add5 Path delay (ns): 9.149 = 109.3 MHz
uint32_t add5(uint32_t x, uint32_t y)
{
  uint32_t accum = x;
  uint32_t i;
  for(i=0; i<5; i+=1)
  {
    accum += y;
  }
  return accum;
}
// add10 Path delay (ns): 16.256 = 61.5 MHz
uint32_t add10(uint32_t x, uint32_t y)
{
  uint32_t accum = x;
  uint32_t i;
  for(i=0; i<10; i+=1)
  {
    accum += y;
  }
  return accum;
}
// main Path delay (ns): 17.546 = 56.9 MHz
uint32_t main(uint32_t x, uint32_t y)
{
  uint32_t a = add5(x,y);
  uint32_t b = add10(x,y);
  return a+b;
}
*/

//#pragma PART "xc7a35ticsg324-1l"2
/*
uint7_t main(uint6_t x, uint6_t y, uint1_t c)
{
  __vhdl__("\n\
  begin \n\
     return_output <= ('0'&x) + ('0'&y) + c;\n\
  ");
  // uint1 = (ns): 1.654 = 604.5949214026602 MHz
  // uint2 = (ns): 1.726 = 579.3742757821552 MHz
  // uint3 = (ns): 2.303 = 434.2162396873643 MHz
  // uint4 = (ns): 2.31 = 432.9004329004329 MHz
  // uint5 = (ns): 2.894 = 345.5425017277125 MHz (LUT3=1 LUT5=2)
  // uint6 = (ns): 2.25699 = 443.0660168365087 MHz (CARRY4=2 LUT2=1)
  // uint7 = (ns): 2.283 = 438.02014892685065 MHz
  // uint8 = (ns): 2.332 = 428.81646655231566 MHz
  // uint9 = (ns): 2.258 = 442.8697962798937 MHz
  // uint10 = (ns): 2.371 = 421.76296921130324 MHz
  // uint11 = (ns): 2.397002 = 417.18815185648725 MHz
  // uint12 = (ns): 2.4459999999999997 = 408.83074407195426 MHz
  // uint13 = (ns): 2.372 = 421.5851602023609 MHz
  // uint14 = (ns): 2.4850000000000003 = 402.41448692152915 MHz
  // uint15 = (ns): 2.511 = 398.24771007566704 MHz
  // uint16 = (ns): 2.56 = 390.625 MHz
  //return x + y + c;
}
*/


/*
uint8_t the_ram[128];
 main()
{
  
  // A variable latency globally visible memory access
  
  // Async style send and wait two func and fsm?
  
  // IMplemented as pipeline c func replacing this?  
  the_ram[i] = x
  // How to put a state machine into a user design?
    
}
*/


/*
// Tag main func as being compiled as C code and run on RISCV cpu
// What does interaction with PipelineC main func look like?
#pragma MAIN_MHZ cpu_main 100.0
#pragma MAIN_THREAD cpu_main // Run this as a CPU style thread
void cpu_main()
{
  // CPU style control loop
  while(1)
  {
    // Running around sequentially reading and writing memory
    // / Memory mapped registers to interact with hardware
    // The key being in hardware the registers are at 100MHz as specified
    mem[i] = foo
  
  }
  
}

#pragma MAIN_MHZ fpga_main 100.0
void fpga_main()
{
  // Every ten nanoseconds a value from
  // the RISCV CPU registers can be read/write ~like a variable somehow?
  
  
}
*/
