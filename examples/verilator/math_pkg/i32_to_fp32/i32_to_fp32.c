// types for any N
#include "intN_t.h"
#include "uintN_t.h"

// Function to test

float i32_to_fp32(int32_t x)
{
  return (float)x;
}

// Verilator device under test test bench setup
#include "../dut.h"

#ifdef __PIPELINEC__
// Define hardware debug hooks

// Generate top level debug ports
#include "debug_port.h"

// Debug ports, two inputs, one output
DEBUG_INPUT_DECL(int32_t, x)
DEBUG_OUTPUT_DECL(float, result)
// Mark as top level for synthesis
#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  result = i32_to_fp32(x);
}
#endif

// Define test params + logic using debug hooks

#define DUT_VARS_DECL \
int32_t x;\
float result;\
float c_result;\
float allowed_err;\
float err;

#define DUT_SET_NEXT_INPUTS \
if(test_num==(100000000-1))\
{\
  done = true; \
}\
/*Generate random input*/ \
x = rand_int_range(int_min_val(32), int_max_val(32));

#define DUT_SET_INPUTS(top) \
DUT_SET_INPUT(top, x)

#define DUT_GET_OUTPUTS(top) \
DUT_GET_FLOAT_OUTPUT(top, result)\
c_result = i32_to_fp32(x);\
/* <= 1e-6 part error allowed */\
allowed_err = max((double)(fabs(c_result)*1e-6), (double)FLT_MIN);

#define DUT_COMPARE_LOG(top) \
err = abs(c_result - result);\
if(err > allowed_err)\
{\
  DUT_PRINT_INT(x)\
  DUT_PRINT_FLOAT(c_result)\
  DUT_PRINT_FLOAT(result)\
  cout << "err: " << err << \
  " allowed_err: " << allowed_err << " ";\
  cout << "FAILED" << endl;\
  test_passed = false;\
}
