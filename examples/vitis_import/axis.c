#include "uintN_t.h"
#include "axi/axis.h"

#pragma MAIN axis_test
// Not using axis32_t in output struct 
// since conversion to verilog makes nested structs ugly
typedef struct axis_test_t{
  uint32_t axis_out_data;
  uint4_t axis_out_keep;
  uint1_t axis_out_valid;
  uint1_t axis_in_ready;
}axis_test_t;
axis_test_t axis_test(
  axis32_t axis_in,
  uint1_t axis_out_ready
)
{
  // Simple demo doing +1 on each element
  axis_test_t o;
  o.axis_out_data = axis_in.data + 1;
  o.axis_out_keep = axis_in.keep;
  o.axis_out_valid = axis_in.valid;
  o.axis_in_ready = axis_out_ready;
  return o;
}

/*
// static buffer, not autopipelined
// State is buffer of axis data
static axis32_t axis_data;
// Output signals
axis_test_t o;
// Ready if buffer is empty
o.axis_in_ready = !axis_data.valid;
// Output is from buffer
o.axis_out_data = axis_data;
// Buffer written when ready for inputs
// Cleared when ready for output
if(o.axis_in_ready){
  axis_data = axis_in_data;
} else if(axis_out_ready){
  axis_data.valid = 0;
}
// Data is transfered if valid and ready
uint1_t input_xfer_now = axis_in_data.valid & o.axis_in_ready;
*/