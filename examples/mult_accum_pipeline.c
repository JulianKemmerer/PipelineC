// A II=1 multiply accumulate pipeline

#include "intN_t.h"
#include "uintN_t.h"

// Set FPGA part/synthesis tool see ../main.c for examples.
#pragma PART "LFE5UM5G-85F-8BG756C"

// The accumulation cannot be pipelined (need result in a single cycle)
// So isolate the local state variable function doing just accumulate
uint32_t accum(uint32_t inc){
  static uint32_t total = 0;
  total += inc;
  return total;
}

// Everything outside of 'accum' (the multiply) is autopipelined
//#pragma MAIN_MHZ mult_accum 200.0
#pragma MAIN mult_accum
uint32_t mult_accum(uint32_t x, uint32_t y)
{
  uint32_t prod = x * y;
  return accum(prod);
}
