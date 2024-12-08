#include "uintN_t.h"  // uintN_t types for any N
#include "debug_port.h"

// Install+configure synthesis tool then specify part here
#pragma PART "ICE40UP5K-SG48" // ice40 (pico-ice)
//#pragma PART "xc7a100tcsg324-1" // Artix 7 100T (Arty)

DEBUG_OUTPUT_DECL(uint32_t, counter_debug)

// 'Called'/'Executing' every 40ns (25MHz)
#pragma MAIN_MHZ main 25.0
uint32_t main()
{
  // static = registers
  static uint32_t the_counter_reg;
  // debug signals connect to extra top level ports
  counter_debug = the_counter_reg;
  // printf's work in simulation
  printf("Counter register value: %d\n", the_counter_reg);
  // an adder
  the_counter_reg += 1;
  // connection to output port
  return the_counter_reg;
  
  /*
  // Version where register connects directly to output
  static uint32_t the_counter_reg;
  uint32_t output = the_counter_reg;
  // an adder
  the_counter_reg += 1;
  // connection to output port
  return output;
  */
}
