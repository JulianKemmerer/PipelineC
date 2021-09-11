#include "uintN_t.h"

uint8_t my_counter(uint1_t reset, uint1_t load, uint8_t val)
{
  static uint8_t counter;
  uint8_t rv = counter;
  counter += 1;
  if(load)
  {
    counter = val;
  }
  if(reset)
  {
    counter = 0;
  }
  return rv;
}


// Return 1 bit flag signaling testbench is done
#pragma MAIN_MHZ my_test_bench 100.0
uint1_t my_test_bench()
{
  static uint8_t clk_count = 0;
  static uint8_t pass;
  uint1_t reset;
  uint1_t load;
  uint8_t val;
  uint1_t done;

  if(clk_count==0)
  {
    reset = 1;
  }
  else if(clk_count==1)
  {
    load = 1;
    val = 10;
  }
  
  uint8_t the_count = my_counter(reset, load, val);
  
  if(clk_count >= 10)
  {
    pass = 0;
    if(the_count==(clk_count-1))
    {
      pass = 1;
    }
    done = 1;
  }
  clk_count+=1;
  return done;
}
