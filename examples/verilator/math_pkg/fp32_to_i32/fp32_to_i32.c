// types for any N
#include "intN_t.h"
#include "uintN_t.h"

// Function to test

int32_t fp32_to_i32(float x)
{
  return (int32_t)x;
}

// Verilator device under test test bench setup
#include "../dut.h"

#ifdef __PIPELINEC__
// Define hardware debug hooks

// Generate top level debug ports
#include "debug_port.h"

// Debug ports, two inputs, one output
DEBUG_INPUT_DECL(float, x)
DEBUG_OUTPUT_DECL(int32_t, result)
// Mark as top level for synthesis
#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  result = fp32_to_i32(x);
}
#endif

// Define test params + logic using debug hooks

#define DUT_VARS_DECL \
float x;\
int32_t result;\
int32_t c_result;\
uint allowed_err;\
uint err;

#define DUT_SET_NEXT_INPUTS \
if(test_num==(100000000-1))\
{\
  done = true; \
}\
/*Generate random input*/ \
x = rand_float();\
while(x>int_max_val(32) || x<int_min_val(32)) \
{\
  x = rand_float();\
}

#define DUT_SET_INPUTS(top) \
DUT_SET_FLOAT_INPUT(top, x)

#define DUT_GET_OUTPUTS(top) \
DUT_GET_SIGNED_OUTPUT(top, result, 32)\
c_result = fp32_to_i32(x);\
allowed_err = 1;

#define DUT_COMPARE_LOG(top) \
err = abs(c_result - result);\
if(err > allowed_err)\
{\
  DUT_PRINT_FLOAT(x)\
  DUT_PRINT_INT(c_result)\
  DUT_PRINT_INT(result)\
  cout << "err: " << err << \
  " allowed_err: " << allowed_err << " ";\
  cout << "FAILED" << endl;\
  test_passed = false;\
}
