// See primitive func stuff in QUARTUS.py that specifies these normal looking functions as hardware primitives

#include "uintN_t.h"


uint18_t LPM_MULT9X9(uint9_t a, uint9_t b)
{
  return a * b;
}

uint36_t LPM_MULT18X18(uint18_t a, uint18_t b)
{
  return a * b;
}

uint48_t LPM_MULT24X24(uint24_t a, uint24_t b)
{
  return a * b;
}

/*
uint48_t cyclone_iv_mult24x24(uint24_t l, uint24_t r)
{
  // Essentially rounding up to 36bx3b mult
  // using LPM_MULT18X18's
  // Thanks rlee, maybe Karatusba soon!
  
  // Split left arg into a,b (msb,lsb)
  uint12_t a = uint24_23_12(l);
  uint12_t b = uint24_11_0(l);
  // Right into c,d (msb,lsb)
  uint12_t c = uint24_23_12(r);
  uint12_t d = uint24_11_0(r);
  // Grade school algorithm
  uint24_t ac = LPM_MULT18X18(a, c);
  uint24_t ad = LPM_MULT18X18(a, d);
  uint24_t bc = LPM_MULT18X18(b, c);
  uint24_t bd = LPM_MULT18X18(b, d);
  uint25_t ad_plus_bc = ad + bc;
  uint48_t ac_shifted = ac << 12;
  uint48_t ad_plus_bc_shifted = ad_plus_bc << 12;
  uint48_t ac_shifted_plus_bd = ac_shifted + bd;
  uint48_t result = ac_shifted_plus_bd + ad_plus_bc_shifted;

  return result;
}
*/

// This is a copy of the internal PipelineC FP multiplier
// With the unsigned multiply replaced with cyclone_iv prim
float cyclone_iv_fp_mult(float left, float right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  uint23_t x_mantissa;
  x_mantissa = float_22_0(left);
  uint9_t x_exponent_wide;
  x_exponent_wide = float_30_23(left);
  uint1_t x_sign;
  x_sign = float_31_31(left);
  // RIGHT
  uint23_t y_mantissa;
  y_mantissa = float_22_0(right);
  uint9_t y_exponent_wide;
  y_exponent_wide = float_30_23(right);
  uint1_t y_sign;
  y_sign = float_31_31(right);
  
  // Declare the output portions
  uint23_t z_mantissa;
  uint8_t z_exponent;
  uint1_t z_sign;
  
  // Sign
  z_sign = x_sign ^ y_sign;
  
  // Multiplication with infinity = inf
  if((x_exponent_wide==255) | (y_exponent_wide==255))
  {
    z_exponent = 255;
    z_mantissa = 0;
  }
  // Multiplication with zero = zero
  else if((x_exponent_wide==0) | (y_exponent_wide==0))
  {
    z_exponent = 0;
    z_mantissa = 0;
    z_sign = 0;
  }
  // Normal non zero|inf mult
  else
  {
    // Delcare intermediates
    uint1_t aux;
    uint24_t aux2_x;
    uint24_t aux2_y;
    uint48_t aux2;
    uint7_t BIAS;
    BIAS = 127;
    
    aux2_x = uint1_uint23(1, x_mantissa);
    aux2_y = uint1_uint23(1, y_mantissa);
    aux2 = LPM_MULT24X24(aux2_x, aux2_y); //cyclone_iv_mult24x24(aux2_x, aux2_y); //aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = uint48_47_47(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = uint48_46_24(aux2); 
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = uint48_45_23(aux2); 
    }
    
    // calculate exponent in parts 
    // do sequential unsigned adds and subs to avoid signed numbers for now
    // X and Y exponent are already 1 bit wider than needed
    // (0 & x_exponent) + (0 & y_exponent);
    uint9_t exponent_sum = x_exponent_wide + y_exponent_wide;
    exponent_sum = exponent_sum + aux;
    exponent_sum = exponent_sum - BIAS;
    
    // HACKY NOT CHECKING
    // if (exponent_sum(8)='1') then
    z_exponent = uint9_7_0(exponent_sum);
  }
  
  
  // Assemble output
  return float_uint1_uint8_uint23(z_sign, z_exponent, z_mantissa);
}
