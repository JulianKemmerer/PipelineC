// A II=1 pipeline from a pure C function (no globals or local static vars)

// Set FPGA part/synthesis tool see ../main.c for examples.
//#pragma PART "LFE5UM5G-85F-8BG756C"

#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN_MHZ my_pipeline 100.0
float my_pipeline(float x, float y)
{
  return x + y;
}
