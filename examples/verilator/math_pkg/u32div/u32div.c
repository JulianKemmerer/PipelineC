// uintN_t types for any N
#include "uintN_t.h"

// Function to test
uint32_t u32div(uint32_t x, uint32_t y)
{
  return x / y;
}

// Verilator device under test test bench setup
#include "../dut.h"

#ifdef __PIPELINEC__
// Define hardware debug hooks

// Generate top level debug ports
#include "debug_port.h"

// Debug ports, two inputs, one output
DEBUG_INPUT_DECL(uint32_t, x)
DEBUG_INPUT_DECL(uint32_t, y)
DEBUG_OUTPUT_DECL(uint32_t, result)
// Mark as top level for synthesis
#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  result = u32div(x, y);
}
#endif

// Define test params + logic using debug hooks

#define DUT_VARS_DECL \
uint32_t x;\
uint32_t y;\
uint32_t result;\
uint32_t c_result;

#define DUT_SET_NEXT_INPUTS \
if(test_num==(100000000-1))\
{\
  done = true; \
}\
/*Generate random input, no 0 divisors*/ \
x = rand() % (int)pow(2, 32); \
y = 0; \
while(y==0) \
{ \
  y = rand() % (int)pow(2, 32); \
}

#define DUT_SET_INPUTS(top) \
DUT_SET_INPUT(top, x)\
DUT_SET_INPUT(top, y)

#define DUT_SET_NULL_INPUTS(top) \
top->x = 0;\
top->y = 0;

#define DUT_GET_OUTPUTS(top) \
DUT_GET_OUTPUT(top, result)\
c_result = u32div(x, y);

#define DUT_COMPARE_LOG(top) \
if(c_result != result)\
{\
  cout << "Verilator result " << result << " C compare FAILED " << x << " / " << y << " c_result " << c_result << endl;\
  test_passed = false;\
}
