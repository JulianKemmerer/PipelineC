// A II=1 pipeline from a pure C function (no globals or local static vars)

// Set FPGA part/synthesis tool see ../main.c for examples.
#pragma PART "LFE5UM5G-85F-8BG756C"

#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN my_pipeline
uint64_t my_pipeline(uint64_t x, uint64_t y)
{
  uint64_t rv;
  if(x > y)
  {
    rv = x + y;
  }
  else
  {
    rv = x * y;
  }
  return rv;
}
