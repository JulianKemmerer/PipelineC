#pragma once
#include "intN_t.h"
#include "uintN_t.h"
/*
 * A fixed-point number has a fixed (constant) number of digits before and after the radix point. 
 * All of our representations use base 2, 
 * so we substitute bit for digit, and binary point or simply point for radix point. 
 * The bits to the left of the point are the integer part, and the bits to the right of the point are the fractional part.

We speak of integer PCM, because fixed-point values are usually stored and manipulated as integer values.
*  The interpretation as fixed-point is implicit.

We use two's complement for all signed fixed-point representations, 
* so the following holds where all values are in units of one LSB:

|largest negative value| = |largest positive value| + 1
Q and U notation
There are various notations for fixed-point representation in an integer. 
* We use Q notation: Qm.n means m integer bits and n fractional bits. 
* The "Q" counts as one bit, though the value is expressed in two's complement. 
* The total number of bits is m + n + 1.
Um.n is for unsigned numbers: m integer bits and n fractional bits, and the "U" counts as zero bits. The total number of bits is m + n.

For example for a Q2.6 number,
its range is [-2m, 2m - 2-n]
its resolution is 2-n
range is  [-22, 22 - 2-6] = [-4 , 3.984375 ].
resolution is 2-n  = 2-6  = 0.015625.
* */

// As struct since dont want to allow, ex. regular '*' or '/' operators for these numbers
typedef struct q0_23_t
{
  int24_t qmn;
}q0_23_t;
float q0_23_to_float(q0_23_t x)
{
  float x_int_float = x.qmn;
  float rv = x_int_float * 1.1920929e-7; // 1.1920929e-7 = 2^-23
  //printf("q0_23_t int24 %d = float %f\n", x.qmn, rv);
  return rv;
}

#define saturate_int24(i24_out_val, i25_or_larger_val) \
{ \
  /* Saturate int24 */ \
  /* 23 bits of 1's is max */ \
  int24_t saturate_int24_max_val = uint1_23(1); \
  /* 24th bit, bit[23]= 1 is min  */ \
  int24_t saturate_int24_min_val = uint1_uint23(1,0); \
  /* Default lose bits */ \
  i24_out_val = i25_or_larger_val; \
  /* Check max+min */ \
  if(i25_or_larger_val > saturate_int24_max_val) \
  { \
    i24_out_val = saturate_int24_max_val; \
  } \
  else if(i25_or_larger_val < saturate_int24_min_val) \
  { \
    i24_out_val = saturate_int24_min_val; \
  } \
}

q0_23_t q0_23_add(q0_23_t a, q0_23_t b)
{    
    // Add, i25 result
    int25_t sum_w_overflow = a.qmn + b.qmn; 
    
    // Saturate int24
    int24_t sum;
    saturate_int24(sum, sum_w_overflow)
    
    // Return
    q0_23_t rv;
    rv.qmn = sum;
    return rv;
}

q0_23_t q0_23_mult(q0_23_t a, q0_23_t b)
{ 
  // Multiply, int48 result
  int48_t product_w_overflow = a.qmn * b.qmn;
  
  // Rounding; mid values are rounded up
  product_w_overflow += (1 << (23 - 1)); 
  // Correct by dividing by base 
  product_w_overflow = product_w_overflow >> 23;
  // Saturate int24
  int24_t product;
  saturate_int24(product, product_w_overflow)
  
  // Return
  q0_23_t rv;
  rv.qmn = product;
  return rv;
}
