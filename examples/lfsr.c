// Comparing to demo migen code: https://pramode.in/2016/10/05/random-bitstream-using-lfsr/
#include "uintN_t.h"

#define MAX_PERIOD 5000000

uint16_t new_val(uint16_t lfsr){
  uint16_t bit = ((lfsr >> 0) ^
        (lfsr >> 2) ^
        (lfsr >> 3) ^
        (lfsr >> 5)) & 1;
  return (lfsr >> 1)  | (bit << 15);
}

#pragma MAIN_MHZ m 100
uint1_t m()
{
  static uint16_t lfsr = 0xACE1;
  static uint23_t counter;
  static uint32_t period = MAX_PERIOD;
  uint1_t led1 = lfsr(0);
  if(counter==0){
    counter = period;
    lfsr = new_val(lfsr);
  }else{
    counter = counter - 1;
  }
  return led1;
}