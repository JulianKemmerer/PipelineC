#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
// #pragma PART "xc7a35ticsg324-1l"

// Time counter registers
uint25_t counter;

// LED on off state registers
uint1_t led;

#pragma MAIN blink
uint1_t blink()
{
  printf("Counter: %d, LED: %d\n", counter, led);
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
    counter += 1;
  }
  return led;
}
