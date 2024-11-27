// See primitive func stuff in QUARTUS.py that specifies these normal looking functions as hardware primitives

#include "uintN_t.h"

uint16_t LPM_MULT8X8(uint8_t a, uint8_t b)
{
  return a * b;
}

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
uint48_t mult24x24(uint24_t l, uint24_t r)
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

/*Let's say we need to multiply two mantisa values A and B, 24 bit each:
Value a can be represented as 1.abc with a b and c being 8 bit valies. B is
1.xyz, same width.
Then you can mult:
 A*B=(a*x+a*y+a*z+b*x+b*y+c*x) that is not calculating least significant
term b*z+c*y+c*z. Using the full 9 bits instead of 8 will solve the carry
issues from the least significant term.
*/
// UNTESTED
uint27_t mult27x27(uint27_t x, uint27_t y)
{
  //extract 9 bit fields
  uint9_t a = uint27_26_18(x); // x[26:18]
  uint9_t b = uint27_17_9(x);
  uint9_t c = uint27_8_0(x);
  uint9_t d = uint27_26_18(y);
  uint9_t e = uint27_17_9(y);
  uint9_t f = uint27_8_0(y);

  uint9_t cd = uint18_17_9(LPM_MULT9X9(c, d));  // 18b c*d result top msbits [17:9]
  uint10_t be_cd = cd + uint18_17_9(LPM_MULT9X9(b, e));
  uint11_t be_cd_af = be_cd + uint18_17_9(LPM_MULT9X9(a, f));

  uint18_t bd = LPM_MULT9X9(b, d);
  uint19_t ae_bd = bd + LPM_MULT9X9(a, e);

  uint18_t ad = LPM_MULT9X9(a, d);
  uint27_t r = (ad << 9) + (ae_bd + be_cd_af);
  
  return r;
}
// UNTESTED
uint27_t mult18x18(uint27_t x, uint27_t y)
{
  //extract 9 bit fields
  uint9_t a = uint27_26_18(x); // x[26:18]
  uint9_t b = uint27_17_9(x);
  uint9_t d = uint27_26_18(y);
  uint9_t e = uint27_17_9(y);

  uint10_t be = uint18_17_9(LPM_MULT9X9(b, e));

  uint18_t bd = LPM_MULT9X9(b, d);
  uint19_t ae_bd = bd + LPM_MULT9X9(a, e);

  uint18_t ad = LPM_MULT9X9(a, d);
  uint27_t r = (ad << 9) + (ae_bd + be);
  
  return r;
}

// 15b*15b returning upper 16b of normally 30b output
uint16_t mult15x15_upper16(uint15_t x, uint15_t y){
  return (x*y)>>14; // TODO REPLACE WITH LPM_MULT9X9's
}


// This is a copy of the internal PipelineC FP multiplier
// With the unsigned multiply replaced with cyclone_iv prim


/*TODO try replacing 

uint1_t gte(int64_t left, int64_t right){
  
}
// all L/G/T/E ops with ass/sub compare==0?
// need to re-synth  whole design?
uint1_t BIN_OP_GTE_int22_t_int22_t(int22_t left, int22_t right){
  int23_t sub = left - right;
  uint1_t is_neg = sub(22,22);
  return !is_neg;
}

#define BIN_OP_INT_GTE(lwidth,rwidth,max_width_plus1)\
uint1_t BIN_OP_GTE_int22_t_int22_t(int22_t left, int22_t right){
  int23_t sub = left - right;
  uint1_t is_neg = sub(22,22);
  return !is_neg;
}*/



float_8_14_t BIN_OP_INFERRED_MULT_float_8_14_t_float_8_14_t(float_8_14_t left, float_8_14_t right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  uint14_t x_mantissa;
  x_mantissa = float_8_14_t_13_0(left);
  uint9_t x_exponent_wide;
  x_exponent_wide = float_8_14_t_21_14(left);
  uint1_t x_sign;
  x_sign = float_8_14_t_22_22(left);
  // RIGHT
  uint14_t y_mantissa;
  y_mantissa = float_8_14_t_13_0(right);
  uint9_t y_exponent_wide;
  y_exponent_wide = float_8_14_t_21_14(right);
  uint1_t y_sign;
  y_sign = float_8_14_t_22_22(right);
  
  // Declare the output portions
  uint14_t z_mantissa;
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
    uint15_t aux2_x;
    uint15_t aux2_y;
    uint30_t aux2;
    uint7_t BIAS;
    BIAS = 127;
    
    aux2_x = uint1_uint14(1, x_mantissa);
    aux2_y = uint1_uint14(1, y_mantissa);
    /*
    aux2 =  aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = uint30_29_29(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = uint30_28_15(aux2); 
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = uint30_27_14(aux2); 
    }*/
    uint16_t upper16 = mult15x15_upper16(aux2_x, aux2_y);
    //uint27_t x_27b = (uint27_t)aux2_x << (27-15);
    //uint27_t y_27b = (uint27_t)aux2_y << (27-15);
    //uint27_t mult_result = mult27x27(x_27b, y_27b);
    //uint27_t mult_result = mult18x18(x_27b, y_27b);
    //uint16_t upper16 = mult_result >> (27-16);
    aux = uint16_15_15(upper16);
    if(aux)
    { 
      z_mantissa = uint16_14_1(upper16); 
    }
    else
    { 
      z_mantissa = uint16_13_0(upper16);
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
  return float_uint8_uint14(z_sign, z_exponent, z_mantissa);
}


// UNTESTED
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
    
    aux2_x = uint1_uint23(1, x_mantissa); // Concat '1' bit to MSB/left
    aux2_y = uint1_uint23(1, y_mantissa); // Concat '1' bit to MSB/left
    /*
    aux2 = LPM_MULT24X24(aux2_x, aux2_y); //cyclone_iv_mult24x24(aux2_x, aux2_y); //aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = uint48_47_47(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = uint48_46_24(aux2); // aux2[46:24]
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = uint48_45_23(aux2); // aux2[45:23]
    }*/
    z_mantissa = mult27x27(aux2_x, aux2_y);
    
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
