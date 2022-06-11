// A II=1 multiply accumulate pipeline

#include "intN_t.h"
#include "uintN_t.h"

// Set FPGA part/synthesis tool see ../main.c for examples.
//#pragma PART "LFE5UM5G-85F-8BG756C"

// The accumulation cannot be pipelined (need result in a single cycle)
// So isolate the local state variable function doing just accumulate
float accum(float inc){
  static float total = 0.0;
  total += inc;
  return total;
}

// Everything outside of 'accum' (the multiply) is autopipelined
//#pragma MAIN_MHZ mult_accum 200.0
#pragma MAIN mult_accum
float mult_accum(float x, float y)
{
  float prod = x * y;
  return accum(prod);
}
