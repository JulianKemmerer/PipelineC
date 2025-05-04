#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
#pragma PART "LFE5U-85F-6BG381C"
//#pragma PART "xc7a35ticsg324-1l"
//#pragma PART "5CEBA4F23C8"

// 'Called'/'Executing' every 30ns (33.33MHz)
#pragma MAIN_MHZ blink 33.33
uint1_t blink()
{
  // Count to 33333333 iterations * 30ns each ~= 1sec
  static uint25_t counter;

  // LED on off state
  static uint1_t led;

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
