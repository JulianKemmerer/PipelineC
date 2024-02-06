// @tiagosr: changed part number recognition to pick latest version of a given part
// it would be good to discuss a standard for device versions. Maybe use a colon for the version?
// speed grade C8 is equivalent to I7 in this context, and resolves to the expected C8/I7
// for gw_sh not to complain.
#pragma PART GW2AR-LV18QN88PC8
#pragma MAIN_MHZ my_pipeline 100.0
// TEMP NOT UNTIL DONE DEV #include "examples/pipeline.c"
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN my_pipeline
// @tiagosr: sized ports down to fit the amount of I/O in the device
uint32_t my_pipeline(uint32_t x, uint32_t y)
{
  return x + y;
}