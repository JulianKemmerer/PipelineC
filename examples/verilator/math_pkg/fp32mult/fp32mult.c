// types for any N
#include "intN_t.h"
#include "uintN_t.h"

// Function to test

float fp32mult(float x, float y)
{
  return x * y;
}

// Verilator device under test test bench setup
#include "../dut.h"

#ifdef __PIPELINEC__
// Define hardware debug hooks

// Generate top level debug ports
#include "debug_port.h"

// Debug ports, two inputs, one output
DEBUG_INPUT_DECL(float, x)
DEBUG_INPUT_DECL(float, y)
DEBUG_OUTPUT_DECL(float, result)
// Mark as top level for synthesis
#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  result = fp32mult(x, y);
}
#endif

// Define test params + logic using debug hooks

#define DUT_VARS_DECL \
float x;\
float y;\
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
rand_two_floats(&x, &y);

#define DUT_SET_INPUTS(top) \
DUT_SET_FLOAT_INPUT(top, x)\
DUT_SET_FLOAT_INPUT(top, y)

#define DUT_SET_NULL_INPUTS(top) \
top->x = 0;\
top->y = 0;

#define DUT_GET_OUTPUTS(top) \
DUT_GET_FLOAT_OUTPUT(top, result)\
c_result = fp32mult(x, y);\
/* <= 1e-6 part error allowed */\
allowed_err = max((double)(fabs(c_result)*1e-6), (double)FLT_MIN);

#define DUT_COMPARE_LOG(top) \
err = fabs(c_result - result);\
if(err > allowed_err)\
{\
  DUT_PRINT_FLOAT(x)\
  DUT_PRINT_FLOAT(y)\
  DUT_PRINT_FLOAT(c_result)\
  DUT_PRINT_FLOAT(result)\
  cout << "err: " << err << \
  " allowed_err: " << allowed_err << " ";\
  cout << "FAILED" << endl;\
  test_passed = false;\
}
