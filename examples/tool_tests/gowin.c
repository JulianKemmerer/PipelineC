// @tiagosr: adding --device_version (or --device_name) at the end as 
// PipelineC currently recognizes vendors by the first letters of the part name
#pragma PART "GW2AR-LV18QN88PC8/I7 --device_version C"
#pragma MAIN_MHZ my_pipeline 100.0
// TEMP NOT UNTIL DONE DEV #include "examples/pipeline.c"
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN my_pipeline
// @tiagosr: sized ports down to fit the amount of I/O in the device
uint16_t my_pipeline(uint16_t x, uint16_t y)
{
  return x + y;
}