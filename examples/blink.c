#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
// #pragma PART "xc7a35ticsg324-1l" 

// Count to 200000000 iterations * 5ns each = 1sec
uint28_t counter;

// LED on off state
uint1_t led;

// 'Called'/'Executing' every 5ns (200MHz)
#pragma MAIN_MHZ blink 200.0
uint1_t blink()
{
  // If reached 1 second
  if(counter==(200000000-1))
  {
    // Toggle led
    led = !led;
    // Reset counter
    counter = 0;
  }
  else
  {
    counter += 1; // one 5ns increment
  }
  return led;
}





