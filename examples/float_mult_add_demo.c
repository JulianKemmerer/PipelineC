#pragma PART "xcvu9p-flgb2104-2-i"
//#include "uintN_t.h"
//#include "intN_t.h"

#include "float_e_m_t.h" // Must include header, dont define type here
#define float float_5_11_t // Actual use of FP16 instead of float FP32

float fmuladd(float a, float b, float c) {
  return a * b + c;
}

float fadd(float a, float b) {
  return a + b;
}

#pragma MAIN forward
float forward(
  float var_arg0_0_0, float var_arg0_0_1, float var_arg0_0_2, float var_arg0_1_0, 
  float var_arg0_1_1, float var_arg0_1_2, /*float* var_arg1_0, Assumed output*/ 
  float var_constant_4x3xf32_0_0, float var_constant_4x3xf32_0_1, 
  float var_constant_4x3xf32_0_2, float var_constant_4x3xf32_1_0, 
  float var_constant_4x3xf32_1_1, float var_constant_4x3xf32_1_2, 
  float var_constant_4x3xf32_2_0, float var_constant_4x3xf32_2_1, 
  float var_constant_4x3xf32_2_2, float var_constant_4x3xf32_3_0, 
  float var_constant_4x3xf32_3_1, float var_constant_4x3xf32_3_2, 
  float var_constant_4xf32_0, float var_constant_4xf32_1, 
  float var_constant_4xf32_2, float var_constant_4xf32_3
) {
  float var_constant_666 = 666.0; // Made up
  float var_val_17 = fmuladd(var_arg0_0_0, var_constant_4x3xf32_0_0, var_constant_4xf32_0);
  float var_val_19 = fmuladd(var_arg0_0_1, var_constant_4x3xf32_0_1, var_val_17);
  float var_val_21 = fmuladd(var_arg0_0_2, var_constant_4x3xf32_0_2, var_val_19);
  float var_val_22 = fmuladd(var_arg0_0_0, var_constant_4x3xf32_1_0, var_constant_4xf32_1);
  float var_val_23 = fmuladd(var_arg0_0_1, var_constant_4x3xf32_1_1, var_val_22);
  float var_val_24 = fmuladd(var_arg0_0_2, var_constant_4x3xf32_1_2, var_val_23);
  float var_val_25 = fmuladd(var_arg0_0_0, var_constant_4x3xf32_2_0, var_constant_4xf32_2);
  float var_val_26 = fmuladd(var_arg0_0_1, var_constant_4x3xf32_2_1, var_val_25);
  float var_val_27 = fmuladd(var_arg0_0_2, var_constant_4x3xf32_2_2, var_val_26);
  float var_val_28 = fmuladd(var_arg0_0_0, var_constant_4x3xf32_3_0, var_constant_4xf32_3);
  float var_val_29 = fmuladd(var_arg0_0_1, var_constant_4x3xf32_3_1, var_val_28);
  float var_val_30 = fmuladd(var_arg0_0_2, var_constant_4x3xf32_3_2, var_val_29);
  float var_val_32 = fmuladd(var_arg0_1_0, var_constant_4x3xf32_0_0, var_constant_4xf32_0);
  float var_val_34 = fmuladd(var_arg0_1_1, var_constant_4x3xf32_0_1, var_val_32);
  float var_val_36 = fmuladd(var_arg0_1_2, var_constant_4x3xf32_0_2, var_val_34);
  float var_val_37 = fmuladd(var_arg0_1_0, var_constant_4x3xf32_1_0, var_constant_4xf32_1);
  float var_val_38 = fmuladd(var_arg0_1_1, var_constant_4x3xf32_1_1, var_val_37);
  float var_val_39 = fmuladd(var_arg0_1_2, var_constant_4x3xf32_1_2, var_val_38);
  float var_val_40 = fmuladd(var_arg0_1_0, var_constant_4x3xf32_2_0, var_constant_4xf32_2);
  float var_val_41 = fmuladd(var_arg0_1_1, var_constant_4x3xf32_2_1, var_val_40);
  float var_val_42 = fmuladd(var_arg0_1_2, var_constant_4x3xf32_2_2, var_val_41);
  float var_val_43 = fmuladd(var_arg0_1_0, var_constant_4x3xf32_3_0, var_constant_4xf32_3);
  float var_val_44 = fmuladd(var_arg0_1_1, var_constant_4x3xf32_3_1, var_val_43);
  float var_val_45 = fmuladd(var_arg0_1_2, var_constant_4x3xf32_3_2, var_val_44);
  float var_val_47 = fadd(var_val_21, var_constant_666);
  float var_val_48 = fadd(var_val_24, var_val_47);
  float var_val_49 = fadd(var_val_27, var_val_48);
  float var_val_50 = fadd(var_val_30, var_val_49);
  float var_val_51 = fadd(var_val_36, var_val_50);
  float var_val_52 = fadd(var_val_39, var_val_51);
  float var_val_53 = fadd(var_val_42, var_val_52);
  float var_val_54 = fadd(var_val_45, var_val_53);
  //*var_arg1_0 = var_val_54;
  return var_val_54;
}