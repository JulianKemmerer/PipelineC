// A II=1 multiply accumulate pipeline

#include "intN_t.h"
#include "uintN_t.h"

// Set FPGA part/synthesis tool see ../main.c for examples.
#pragma PART "LFE5UM5G-85F-8BG756C"

//#pragma MAIN_MHZ mult_accum 200.0
#pragma MAIN mult_accum
uint32_t mult_accum(uint32_t x, uint32_t y)
{
  uint32_t prod = x * y;
  uint1_t reset = 0; // Unused reset
  return accum(prod, reset);
}
