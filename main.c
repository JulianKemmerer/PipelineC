// xc7a35ticsg324-1l    Artix 7 (Arty)
// xcvu9p-flgb2104-2-i  Virtex Ultrascale Plus (AWS F1)
// xc7v2000tfhg1761-2   Virtex 7
// EP2AGX45CU17I3       Arria II GX
// 10CL120ZF780I8G      Cyclone 10 LP
// 10M50SCE144I7G       Max 10
// LFE5U-85F-6BG381C    ECP5U
#pragma PART "xc7a35ticsg324-1l"

// Most recent (and likely working) examples towards the bottom of list \/
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/keccak.pc"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/fosix/main_bram_loopback.c"
//#include "examples/fir.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/blink.c"
//#include "examples/clock_crossing.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
#include "examples/arty/src/ddr3/mig_app.c"

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 100.0

uint32_t main(uint32_t x, uint32_t y)
{
  uint32_t x_feedback;
  #pragma FEEDBACK x_feedback
  
  // This doesnt make sense/comple unless FEEDBACK pragma'd
  // x_feedback has not been assigned a value
  uint32_t x_looped_back = x_feedback;
  
  // This last assignment to x_feedback is what 
  // shows up as the first x_feedback read value
  x_feedback = x + 1;
  
  return x_looped_back + y;
}
*/






