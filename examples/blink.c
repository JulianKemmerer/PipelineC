#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
// #pragma PART "xc7a35ticsg324-1l" 

// Count to 33333333 iterations * 30ns each ~= 1sec
uint25_t counter;

// LED on off state
uint1_t led;

// 'Called'/'Executing' every 30ns (33.33MHz)
#pragma MAIN_MHZ blink 33.33
uint1_t blink()
{
  // If reached 1 second
  if(counter==(33333333-1))
  {
    // Toggle led
    led = !led;
    // Reset counter
    counter = 0;
  }
  else
  {
    counter += 1; // one 30ns increment
  }
  return led;
}
