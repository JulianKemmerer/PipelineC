// Arbitrary bit width uints
#include "uintN_t.h"

// Counting module, decrements each clock if not loading/resetting
uint8_t my_count_down(uint1_t reset, uint1_t load, uint8_t val)
{
  static uint8_t count;
  uint8_t rv = count;
  count -= 1;
  if(load)
  {
    count = val;
  }
  if(reset)
  {
    count = 0;
  }
  return rv;
}

// Return 1 bit flag signaling testbench is done
#pragma MAIN_MHZ my_test_bench 100.0
// Test setting count to N and waiting N clocks then checking for zero count
#define VAL 10
uint1_t my_test_bench()
{
  // Counter reg to do reset, then wait some
  static uint8_t clk_count;
  // Reg holding the expecected time of count down finish
  static uint8_t clk_count_end;
  // Record if passed test or not with flag reg
  static uint8_t pass;
  // Signals into my_counter
  uint1_t reset;
  uint1_t load;
  uint1_t done;

  // Use first two cycles to reset and load counter
  if(clk_count==0)
  {
    reset = 1;
  }
  else if(clk_count==1)
  {
    load = 1;
    clk_count_end = clk_count + VAL + 1;
  }
  
  // The instance of your counter
  uint8_t the_count = my_count_down(reset, load, VAL);
  
  // Wait a little to check at expected end time
  if(clk_count == clk_count_end)
  {
    // Stop sim
    done = 1;
    
    // Check if countdown completed
    if(the_count==0)
    {
      pass = 1;
      printf("The test passed!\n");
    }
    else
    {
      pass = 0;
      printf("The test failed!\n");
    }
  }
  clk_count+=1;
  
  return done;
}
