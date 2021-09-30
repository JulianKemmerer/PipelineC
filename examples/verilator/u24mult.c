#include "uintN_t.h"  // uintN_t types for any N

// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"

// Debug ports, two inputs, one output
#include "clock_crossing/x_DEBUG.h"
DEBUG_INPUT_DECL(uint24_t, x)
#include "clock_crossing/y_DEBUG.h"
DEBUG_INPUT_DECL(uint24_t, y)
#include "clock_crossing/result_DEBUG.h"
DEBUG_OUTPUT_DECL(uint48_t, result)

#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  result(x() * y());
}





