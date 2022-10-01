#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
// #pragma PART "xc7a35ticsg324-1l" 

// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
DEBUG_OUTPUT_DECL(uint25_t, counter_debug)
DEBUG_OUTPUT_DECL(uint1_t, led_debug)
//DEBUG_INPUT_DECL(uint4_t, inc_debug)

// Time counter registers
uint25_t counter;

// LED on off state registers
uint1_t led;

#pragma MAIN blink
uint1_t blink()
{
  // Connect to verilator debug wires
  counter_debug = counter;
  led_debug = led;
  
  // If reached timeout (short for demo)
  if(counter==(3-1))
  {
    // Toggle led
    led = !led;
    // Reset counter
    counter = 0;
  }
  else
  {
    // TODO: Try setting inputs from verilator
    counter += 1;
  }  
  
  return led;
}
