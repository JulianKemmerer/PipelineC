// Based on Single-precision e^x function from GNU C Library
// glibc/sysdeps/ieee754/flt-32/e_expf.c

// PipelineC specific
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
#define double float_11_52_t

uint32_t asuint(float x){
  return x(31, 0);
}
uint64_t asuint64(double x){
  return x(63, 0);
}
double asdouble(uint64_t x){
  return float_11_52_t_uint64(x);
}
double float_to_double(float x){
  return (double)x; // TODO pipelinec specific
}
float double_to_float(double x){
  return (float)x; // TODO pipelinec specific
}

#define EXP2F_TABLE_BITS 5
#define EXP2F_POLY_ORDER 3
#define N (1 << EXP2F_TABLE_BITS)
#define EXP2F_TABLE_BITS 5
#define EXP2F_POLY_ORDER 3
typedef struct exp2f_data_t
{
  uint64_t tab[1 << EXP2F_TABLE_BITS];
  double shift_scaled;
  double poly[EXP2F_POLY_ORDER];
  double shift;
  double invln2_scaled;
  double poly_scaled[EXP2F_POLY_ORDER];
} exp2f_data_t;
exp2f_data_t exp2f_data = {
  /* tab[i] = uint(2^(i/N)) - (i << 52-BITS)
     used for computing 2^(k/N) for an int |k| < 150 N as
     double(tab[k%N] + (k << 52-BITS)) */
  .tab = {
0x3ff0000000000000, 0x3fefd9b0d3158574, 0x3fefb5586cf9890f, 0x3fef9301d0125b51,
0x3fef72b83c7d517b, 0x3fef54873168b9aa, 0x3fef387a6e756238, 0x3fef1e9df51fdee1,
0x3fef06fe0a31b715, 0x3feef1a7373aa9cb, 0x3feedea64c123422, 0x3feece086061892d,
0x3feebfdad5362a27, 0x3feeb42b569d4f82, 0x3feeab07dd485429, 0x3feea47eb03a5585,
0x3feea09e667f3bcd, 0x3fee9f75e8ec5f74, 0x3feea11473eb0187, 0x3feea589994cce13,
0x3feeace5422aa0db, 0x3feeb737b0cdc5e5, 0x3feec49182a3f090, 0x3feed503b23e255d,
0x3feee89f995ad3ad, 0x3feeff76f2fb5e47, 0x3fef199bdd85529c, 0x3fef3720dcef9069,
0x3fef5818dcfba487, 0x3fef7c97337b9b5f, 0x3fefa4afa2a490da, 0x3fefd0765b6e4540,
  },
  .shift_scaled = 0x1.8p+52 / N,
  .poly = { 0x1.c6af84b912394p-5, 0x1.ebfce50fac4f3p-3, 0x1.62e42ff0c52d6p-1 },
  .shift = 0x1.8p+52,
  .invln2_scaled = 0x1.71547652b82fep+0 * N,
  .poly_scaled = {
0x1.c6af84b912394p-5/N/N/N, 0x1.ebfce50fac4f3p-3/N/N, 0x1.62e42ff0c52d6p-1/N
  },
};

uint64_t mod_N(uint64_t x)
{
  return x(EXP2F_TABLE_BITS-1, 0);
}

#define InvLn2N exp2f_data.invln2_scaled
#define T exp2f_data.tab
#define C exp2f_data.poly_scaled
uint32_t top12(float x)
{
  return asuint (x) >> 20;
}

#pragma MAIN expf
float expf(float x)
{
  uint64_t ki, t;
  double kd, xd, z, r, r2, y, s;

  xd = float_to_double(x);
  
  /* x*N/Ln2 = k + r with r in [-1/2, 1/2] and int k.  */
  z = InvLn2N * xd;

  /* Round and convert z to int, the result is in [-150*N, 128*N] and
     ideally ties-to-even rule is used, otherwise the magnitude of r
     can be bigger which gives larger approximation error.  */
  # define SHIFT exp2f_data.shift
  kd = z + SHIFT; /* Needs to be double.  */
  ki = asuint64 (kd);
  kd -= SHIFT;

  r = z - kd;

  /* exp(x) = 2^(k/N) * 2^(r/N) ~= s * (C0*r^3 + C1*r^2 + C2*r + 1) */
  t = T[mod_N(ki)];
  t += ki << (52 - EXP2F_TABLE_BITS);
  s = asdouble (t);
  z = C[0] * r + C[1];
  r2 = r * r;
  y = C[2] * r + 1;
  y = z * r2 + y;
  y = y * s;
  return double_to_float(y);
}


#if 0
// Not handling, -INF, INF, overflow, underflow
  if (abstop >= top12 (88.0f))
    {
      /* |x| >= 88 or x is nan.  */
      if (asuint (x) == asuint (-INFINITY))
	return 0.0f;
      if (abstop >= top12 (INFINITY))
	return x + x;
      if (x > 0x1.62e42ep6f) /* x > log(0x1p128) ~= 88.72 */
	return __math_oflowf (0);
      if (x < -0x1.9fe368p6f) /* x < log(0x1p-150) ~= -103.97 */
	return __math_uflowf (0);
#if WANT_ERRNO_UFLOW
      if (x < -0x1.9d1d9ep6f) /* x < log(0x1p-149) ~= -103.28 */
	return __math_may_uflowf (0);
#endif
    }
#endif

