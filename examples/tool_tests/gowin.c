#pragma PART "GW2AR-18C GW2AR-LV18QN88PC8/I7"
#pragma MAIN_MHZ my_pipeline 100.0
// TEMP NOT UNTIL DONE DEV #include "examples/pipeline.c"
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN my_pipeline
uint32_t my_pipeline(uint32_t x, uint32_t y)
{
  return x + y;
}