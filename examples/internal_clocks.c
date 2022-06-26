// Generate an internally used slow clock from an externally provided fast clock.

#include "compiler.h"
#include "uintN_t.h"

// Must be integer ratio and divisible by 2 evenly
// since count up to half of period then toggle.
#define SLOW_CLK_MHZ 1.0
#define FAST_CLK_MHZ 100.0
#define CLK_RATIO ((uint32_t)(FAST_CLK_MHZ / SLOW_CLK_MHZ))
#define TOGGLE_COUNT (CLK_RATIO/2)

// Globally visible wire that is the clock signal
uint1_t the_slow_clock;
CLK_MHZ(the_slow_clock, SLOW_CLK_MHZ)
// Temp as test mark as async wire for read
//#pragma ASYNC_WIRE the_slow_clock

// Clock generator runs at fast clock
MAIN_MHZ(clk_gen, FAST_CLK_MHZ)
void clk_gen()
{
  // Make toggling clock using counter
  static uint1_t clock = 0;
  static uint32_t counter = 0;
  // Slow clock driven directly from register
  the_slow_clock = clock;
  // Toggle logic
  if(counter == (TOGGLE_COUNT-1))
  {
    clock = !clock;
    counter = 0;
  }
  else
  {
    counter += 1;
  }
}

// Main func running on the slow clock
MAIN_MHZ(main, SLOW_CLK_MHZ)
uint32_t main()
{
  // Count as demo
  static uint32_t counter = 0;
  uint32_t rv = counter;
  // Temp use clock as increment for read test
  //uint1_t slow_clock = the_slow_clock;
  //counter += slow_clock;
  counter += 1;
  return rv; // So doesnt optimize away
}
