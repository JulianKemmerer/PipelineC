// Arty FPGA demo part
#pragma PART "xc7a35ticsg324-1l"

// Arbitrary with ints
#include "intN_t.h"
#include "uintN_t.h"

// Define float to be standard 32b float
// with 8b exponent and 23b mantissa
#include "float_e_m_t.h"
#define div2(f) (f<<-1) // Built in, todo auto replace /2.0 in code
#define float float_8_23_t
#define uint_to_float float_8_23_t_uint32
#define float_to_uint float_8_23_t_31_0
#define fabs(x) float_8_23_t_abs(x)
#define is_negative float_8_23_t_sign
#define RSQRT_MAGIC 0x5f3759df

// Top level is recip func
#pragma MAIN float_recip

// 1/sqrt(x), https://en.wikipedia.org/wiki/Fast_inverse_square_root
float float_rsqrt(float number)
{
  float x2 = div2(number); // number/2.0
  float conv_f = uint_to_float(RSQRT_MAGIC - (float_to_uint(number) >> 1));
  return conv_f*(1.5 - conv_f*conv_f*x2);
}
// 1/x = (1/sqrt(x))^2 (with sign correction)
float float_recip(float x)
{
  uint1_t neg = is_negative(x);
  float y = float_rsqrt(neg ? -x : x);
  y = y * y;
  return neg ? -y : y;
}