// Verilator device under test test bench setup
#include "../dut.h"

#include "uintN_t.h"
#define FLOAT float
#define llvm_dis_float_rsqrt_K0 0.5
#define llvm_dis_float_rsqrt_K1 1.5
#define llvm_dis_float_rsqrt_K2 1597463007
#define LOAD(x) x
#define BITCAST_I32(x) float_31_0(x)
#define BITCAST_FLOAT(x) float_uint32(x)

//#pragma PART "EP4CE22F17C6"

// Temp manually code up multiplier hard coded with Intel mult prims
//#include "primitives/cyclone_iv.c"

//#pragma MAIN_MHZ llvm_dis_Z11float_rsqrtf 250.0
//#pragma MAIN llvm_dis_Z11float_rsqrtf
float llvm_dis_Z11float_rsqrtf( FLOAT a0)
{
  FLOAT a2;
  FLOAT a3;
  FLOAT a4;
  uint32_t a5;
  uint32_t a6;
  uint32_t a7;
  uint32_t a8;
  FLOAT a9;
  FLOAT a10;
  FLOAT a11;
  FLOAT a12;
  FLOAT a13;
  a2 = LOAD(llvm_dis_float_rsqrt_K0); // %2 = load float, float* @float_rsqrt_K0, align 4, !tbaa !3
  a3 = a2 * a0; // %3 = fmul float %2, %0
  a4 = LOAD(llvm_dis_float_rsqrt_K1); // %4 = load float, float* @float_rsqrt_K1, align 4, !tbaa !3
  a5 = BITCAST_I32(a0); // %5 = bitcast float %0 to i32
  a6 = LOAD(llvm_dis_float_rsqrt_K2); // %6 = load i32, i32* @float_rsqrt_K2, align 4, !tbaa !7
  a7 = a5 >> 1; // %7 = lshr i32 %5, 1
  a8 = a6 - a7; // %8 = sub i32 %6, %7
  a9 = BITCAST_FLOAT(a8); // %9 = bitcast i32 %8 to float
  a10 = a3 * a9; // %10 = fmul float %3, %9
  a11 = a10 * a9; // %11 = fmul float %10, %9
  a12 = a4 - a11; // %12 = fsub float %4, %11
  a13 = a12 * a9; // %13 = fmul float %12, %9
  return a13; // ret float %13
}

/*
#pragma MAIN_MHZ llvm_dis_Z11float_rsqrtf_local_opt 400.0
float llvm_dis_Z11float_rsqrtf_local_opt( FLOAT a0)
{
  FLOAT a3;
  FLOAT a2;
  FLOAT a9;
  uint32_t a5;
  FLOAT a10;
  uint32_t a6;
  uint32_t a7;
  //local variables count optimization: from 12 to 7
  a2 = LOAD(llvm_dis_float_rsqrt_K0); // %2 = load float, float* @float_rsqrt_K0, align 4, !tbaa !3
  a3 = a2 * a0; // %3 = fmul float %2, %0
  a2 = LOAD(llvm_dis_float_rsqrt_K1); // %4 = load float, float* @float_rsqrt_K1, align 4, !tbaa !3
  a5 = BITCAST_I32(a0); // %5 = bitcast float %0 to i32
  a6 = LOAD(llvm_dis_float_rsqrt_K2); // %6 = load i32, i32* @float_rsqrt_K2, align 4, !tbaa !7
  a7 = a5 >> 1; // %7 = lshr i32 %5, 1
  a5 = a6 - a7; // %8 = sub i32 %6, %7
  a9 = BITCAST_FLOAT(a5); // %9 = bitcast i32 %8 to float
  a10 = a3 * a9; // %10 = fmul float %3, %9
  a3 = a10 * a9; // %11 = fmul float %10, %9
  a10 = a2 - a3; // %12 = fsub float %4, %11
  a3 = a10 * a9; // %13 = fmul float %12, %9
  return a3; // ret float %13
}
*/

#ifdef __PIPELINEC__
// Define hardware debug hooks

// Generate top level debug ports
#include "debug_port.h"

// Debug ports
#include "clock_crossing/x_DEBUG.h"
DEBUG_INPUT_DECL(float, x)
#include "clock_crossing/result_DEBUG.h"
DEBUG_OUTPUT_DECL(float, result)
// Mark as top level for synthesis
#pragma MAIN test_bench
void test_bench()
{
  // Drive result debug port 
  // with the output of doing 
  // an operation on the two input ports
  DEBUG_SET(result, llvm_dis_Z11float_rsqrtf(DEBUG_GET(x)));
}
#endif

// Define test params + logic using debug hooks

#define DUT_VARS_DECL \
float x;\
float result;\
float c_result;\
float allowed_err;\
float err;

#define DUT_SET_NEXT_INPUTS \
if(test_num==(10000000-1))\
{\
  done = true; \
}\
/*Generate random input*/ \
x = rand_float(false);

#define DUT_SET_INPUTS(top) \
DUT_SET_FLOAT_INPUT(top, x)

#define DUT_SET_NULL_INPUTS(top) \
top->x = 0;

#define DUT_GET_OUTPUTS(top) \
DUT_GET_FLOAT_OUTPUT(top, result)\
c_result = llvm_dis_Z11float_rsqrtf(x);\
/* <= 1e-6 part error allowed */\
allowed_err = max((double)(fabs(c_result)*1e-6), (double)FLT_MIN);

#define DUT_COMPARE_LOG(top) \
err = fabs(c_result - result);\
if(err > allowed_err)\
{\
  cout << "x: " << x << " ";\
  DUT_PRINT_FLOAT(c_result)\
  DUT_PRINT_FLOAT(result)\
  cout << "err: " << err << \
  " allowed_err: " << allowed_err << " ";\
  cout << "FAILED" << endl;\
  test_passed = false;\
}
