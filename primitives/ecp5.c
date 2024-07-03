#include "intN_t.h"
#include "uintN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// See primitive func stuff in OPEN_TOOLS.py that specifies these normal looking funcitons as hardware primitives
uint36_t ECP5_MUL18X18(uint18_t a, uint18_t b)
{
  return a * b;
}
uint18_t ECP5_MUL9X9(uint9_t a, uint9_t b)
{
  return a * b;
}

// u16x16 = u30, and upper 16b of that?
#define PREC 16
uint16_t prod16x16_16(uint16_t a_in, uint16_t b_in) //1 LSB error @11-16 bits
{
  uint18_t a = a_in << (18-PREC);
  uint18_t b = b_in << (18-PREC);

  uint9_t a0 = a & 0x1FF;
  uint9_t a1 = (a >> 9) & 0x1FF; //mask not needed for PipelineC

  uint9_t b0 = b & 0x1FF;
  uint9_t b1 = (b >> 9) & 0x1FF;

  uint18_t c2 = a1 * b1;
  uint19_t c1 = a1 * b0 + a0 * b1;

  return (c1  + (c2 << 9)) >> (PREC-9+(18-PREC)+(18-PREC));
}

// Test FP variants
#pragma PART "LFE5U-85F-6BG381C"

//#pragma MAIN test_mul
/*float_8_14_t test_mul(float_8_14_t x, float_8_14_t y)
{
  return x * y;
}*/
// BIN_OP_INFERRED_MULT_float_8_14_t_float_8_14_t
float_8_14_t test_mul(float_8_14_t left, float_8_14_t right)
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
    uint7_t BIAS;
    BIAS = 127;
    
    aux2_x = uint1_uint14(1, x_mantissa);
    aux2_y = uint1_uint14(1, y_mantissa);

    /* ORIGINAL INTEGER MULTIPLY
    uint30_t aux2;
    aux2 =  aux2_x * aux2_y;
    aux = uint30_29_29(aux2);
    if(aux)
    { 
      z_mantissa = uint30_28_15(aux2); 
    }
    else
    { 
      z_mantissa = uint30_27_14(aux2); 
    }*/
    // Optimized integer multiply
    uint16_t aux2_upper = prod16x16_16(aux2_x, aux2_y);
    aux = uint16_15_15(aux2_upper);
    if(aux)
    { 
      z_mantissa = uint16_14_1(aux2_upper); 
    }
    else
    { 
      z_mantissa = uint16_13_0(aux2_upper); 
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

/*
// ORIGINAL
Info: Device utilisation:
Info: 	          MULT18X18D:     1/  156     0%
Info: 	          TRELLIS_FF:    69/83640     0%
Info: 	        TRELLIS_COMB:    63/83640     0%

ORIGINAL IN FABRIC
Info: Device utilisation:
Info: 	          MULT18X18D:     0/  156     0%
Info: 	          TRELLIS_FF:    69/83640     0%
Info: 	        TRELLIS_COMB:   655/83640     0%

OPTIMIZED w/ prod16x16_16 IN FABRIC (in mults used 3 18b mults oh no!)
Info: Device utilisation:
Info: 	          MULT18X18D:     0/  156     0%
Info: 	          TRELLIS_FF:    64/83640     0%
Info: 	        TRELLIS_COMB:   448/83640     0%
*/

uint24_t alu(
  uint1_t a_sign, uint18_t a,
  uint1_t b_sign, uint18_t b
)
{
__vhdl__("\n\
component ALU24B is \n\
generic ( \n\
  REG_OUTPUT_CLK : string := \"NONE\"; \n\
  REG_OUTPUT_CE : string := \"CE0\"; \n\
  REG_OUTPUT_RST : string := \"RST0\"; \n\
  REG_OPCODE_0_CLK : string := \"NONE\"; \n\
  REG_OPCODE_0_CE : string := \"CE0\"; \n\
  REG_OPCODE_0_RST : string := \"RST0\"; \n\
  REG_OPCODE_1_CLK : string := \"NONE\"; \n\
  REG_OPCODE_1_CE : string := \"CE0\"; \n\
  REG_OPCODE_1_RST : string := \"RST0\"; \n\
  REG_INPUTCFB_CLK : string := \"NONE\"; \n\
  REG_INPUTCFB_CE : string := \"CE0\"; \n\
  REG_INPUTCFB_RST : string := \"RST0\"; \n\
  CLK0_DIV : string := \"ENABLED\"; \n\
  CLK1_DIV : string := \"ENABLED\"; \n\
  CLK2_DIV : string := \"ENABLED\"; \n\
  CLK3_DIV : string := \"ENABLED\"; \n\
  GSR : string := \"ENABLED\"; \n\
  RESETMODE : string := \"SYNC\"  ); \n\
port ( \n\
  CE3 :   in  std_logic; \n\
  CE2 :   in  std_logic; \n\
  CE1 :   in  std_logic; \n\
  CE0 :   in  std_logic; \n\
  CLK3 :   in  std_logic; \n\
  CLK2 :   in  std_logic; \n\
  CLK1 :   in  std_logic; \n\
  CLK0 :   in  std_logic; \n\
  RST3 :   in  std_logic; \n\
  RST2 :   in  std_logic; \n\
  RST1 :   in  std_logic; \n\
  RST0 :   in  std_logic; \n\
  SIGNEDIA :   in  std_logic; \n\
  SIGNEDIB :   in  std_logic; \n\
  MA17 :   in  std_logic; \n\
  MA16 :   in  std_logic; \n\
  MA15 :   in  std_logic; \n\
  MA14 :   in  std_logic; \n\
  MA13 :   in  std_logic; \n\
  MA12 :   in  std_logic; \n\
  MA11 :   in  std_logic; \n\
  MA10 :   in  std_logic; \n\
  MA9 :   in  std_logic; \n\
  MA8 :   in  std_logic; \n\
  MA7 :   in  std_logic; \n\
  MA6 :   in  std_logic; \n\
  MA5 :   in  std_logic; \n\
  MA4 :   in  std_logic; \n\
  MA3 :   in  std_logic; \n\
  MA2 :   in  std_logic; \n\
  MA1 :   in  std_logic; \n\
  MA0 :   in  std_logic; \n\
  MB17 :   in  std_logic; \n\
  MB16 :   in  std_logic; \n\
  MB15 :   in  std_logic; \n\
  MB14 :   in  std_logic; \n\
  MB13 :   in  std_logic; \n\
  MB12 :   in  std_logic; \n\
  MB11 :   in  std_logic; \n\
  MB10 :   in  std_logic; \n\
  MB9 :   in  std_logic; \n\
  MB8 :   in  std_logic; \n\
  MB7 :   in  std_logic; \n\
  MB6 :   in  std_logic; \n\
  MB5 :   in  std_logic; \n\
  MB4 :   in  std_logic; \n\
  MB3 :   in  std_logic; \n\
  MB2 :   in  std_logic; \n\
  MB1 :   in  std_logic; \n\
  MB0 :   in  std_logic; \n\
  CFB23 :   in  std_logic; \n\
  CFB22 :   in  std_logic; \n\
  CFB21 :   in  std_logic; \n\
  CFB20 :   in  std_logic; \n\
  CFB19 :   in  std_logic; \n\
  CFB18 :   in  std_logic; \n\
  CFB17 :   in  std_logic; \n\
  CFB16 :   in  std_logic; \n\
  CFB15 :   in  std_logic; \n\
  CFB14 :   in  std_logic; \n\
  CFB13 :   in  std_logic; \n\
  CFB12 :   in  std_logic; \n\
  CFB11 :   in  std_logic; \n\
  CFB10 :   in  std_logic; \n\
  CFB9 :   in  std_logic; \n\
  CFB8 :   in  std_logic; \n\
  CFB7 :   in  std_logic; \n\
  CFB6 :   in  std_logic; \n\
  CFB5 :   in  std_logic; \n\
  CFB4 :   in  std_logic; \n\
  CFB3 :   in  std_logic; \n\
  CFB2 :   in  std_logic; \n\
  CFB1 :   in  std_logic; \n\
  CFB0 :   in  std_logic; \n\
  CIN23 :   in  std_logic; \n\
  CIN22 :   in  std_logic; \n\
  CIN21 :   in  std_logic; \n\
  CIN20 :   in  std_logic; \n\
  CIN19 :   in  std_logic; \n\
  CIN18 :   in  std_logic; \n\
  CIN17 :   in  std_logic; \n\
  CIN16 :   in  std_logic; \n\
  CIN15 :   in  std_logic; \n\
  CIN14 :   in  std_logic; \n\
  CIN13 :   in  std_logic; \n\
  CIN12 :   in  std_logic; \n\
  CIN11 :   in  std_logic; \n\
  CIN10 :   in  std_logic; \n\
  CIN9 :   in  std_logic; \n\
  CIN8 :   in  std_logic; \n\
  CIN7 :   in  std_logic; \n\
  CIN6 :   in  std_logic; \n\
  CIN5 :   in  std_logic; \n\
  CIN4 :   in  std_logic; \n\
  CIN3 :   in  std_logic; \n\
  CIN2 :   in  std_logic; \n\
  CIN1 :   in  std_logic; \n\
  CIN0 :   in  std_logic; \n\
  OPADDNSUB :   in  std_logic; \n\
  OPCINSEL :   in  std_logic; \n\
  R23 :   out  std_logic; \n\
  R22 :   out  std_logic; \n\
  R21 :   out  std_logic; \n\
  R20 :   out  std_logic; \n\
  R19 :   out  std_logic; \n\
  R18 :   out  std_logic; \n\
  R17 :   out  std_logic; \n\
  R16 :   out  std_logic; \n\
  R15 :   out  std_logic; \n\
  R14 :   out  std_logic; \n\
  R13 :   out  std_logic; \n\
  R12 :   out  std_logic; \n\
  R11 :   out  std_logic; \n\
  R10 :   out  std_logic; \n\
  R9 :   out  std_logic; \n\
  R8 :   out  std_logic; \n\
  R7 :   out  std_logic; \n\
  R6 :   out  std_logic; \n\
  R5 :   out  std_logic; \n\
  R4 :   out  std_logic; \n\
  R3 :   out  std_logic; \n\
  R2 :   out  std_logic; \n\
  R1 :   out  std_logic; \n\
  R0 :   out  std_logic; \n\
  CO23 :   out  std_logic; \n\
  CO22 :   out  std_logic; \n\
  CO21 :   out  std_logic; \n\
  CO20 :   out  std_logic; \n\
  CO19 :   out  std_logic; \n\
  CO18 :   out  std_logic; \n\
  CO17 :   out  std_logic; \n\
  CO16 :   out  std_logic; \n\
  CO15 :   out  std_logic; \n\
  CO14 :   out  std_logic; \n\
  CO13 :   out  std_logic; \n\
  CO12 :   out  std_logic; \n\
  CO11 :   out  std_logic; \n\
  CO10 :   out  std_logic; \n\
  CO9 :   out  std_logic; \n\
  CO8 :   out  std_logic; \n\
  CO7 :   out  std_logic; \n\
  CO6 :   out  std_logic; \n\
  CO5 :   out  std_logic; \n\
  CO4 :   out  std_logic; \n\
  CO3 :   out  std_logic; \n\
  CO2 :   out  std_logic; \n\
  CO1 :   out  std_logic; \n\
  CO0 :   out  std_logic \n\
); \n\
end component; \n\
begin \n\
inst : ALU24B \n\
generic map( \n\
  REG_OUTPUT_CLK => \"NONE\", \n\
  REG_OUTPUT_CE => \"CE0\", \n\
  REG_OUTPUT_RST => \"RST0\", \n\
  REG_OPCODE_0_CLK => \"NONE\", \n\
  REG_OPCODE_0_CE => \"CE0\", \n\
  REG_OPCODE_0_RST => \"RST0\", \n\
  REG_OPCODE_1_CLK => \"NONE\", \n\
  REG_OPCODE_1_CE => \"CE0\", \n\
  REG_OPCODE_1_RST => \"RST0\", \n\
  REG_INPUTCFB_CLK => \"NONE\", \n\
  REG_INPUTCFB_CE => \"CE0\", \n\
  REG_INPUTCFB_RST => \"RST0\", \n\
  CLK0_DIV => \"ENABLED\", \n\
  CLK1_DIV => \"ENABLED\", \n\
  CLK2_DIV => \"ENABLED\", \n\
  CLK3_DIV => \"ENABLED\", \n\
  GSR => \"ENABLED\", \n\
  RESETMODE => \"SYNC\" \n\
) \n\
port map ( \n\
  CE0 => CLOCK_ENABLE(0), \n\
  CE1 => '0', \n\
  CE2 => '0', \n\
  CE3 => '0', \n\
  CLK0 => clk, \n\
  CLK1 => '0', \n\
  CLK2 => '0', \n\
  CLK3 => '0', \n\
  RST0 => '0', \n\
  RST1 => '0', \n\
  RST2 => '0', \n\
  RST3 => '0', \n\
  SIGNEDIA => a_sign(0), \n\
  SIGNEDIB => b_sign(0), \n\
  MA17 => a(17), \n\
  MA16 => a(16), \n\
  MA15 => a(15), \n\
  MA14 => a(14), \n\
  MA13 => a(13), \n\
  MA12 => a(12), \n\
  MA11 => a(11), \n\
  MA10 => a(10), \n\
  MA9 => a(9), \n\
  MA8 => a(8), \n\
  MA7 => a(7), \n\
  MA6 => a(6), \n\
  MA5 => a(5), \n\
  MA4 => a(4), \n\
  MA3 => a(3), \n\
  MA2 => a(2), \n\
  MA1 => a(1), \n\
  MA0 => a(0), \n\
  MB17 => b(17), \n\
  MB16 => b(16), \n\
  MB15 => b(15), \n\
  MB14 => b(14), \n\
  MB13 => b(13), \n\
  MB12 => b(12), \n\
  MB11 => b(11), \n\
  MB10 => b(10), \n\
  MB9 => b(9), \n\
  MB8 => b(8), \n\
  MB7 => b(7), \n\
  MB6 => b(6), \n\
  MB5 => b(5), \n\
  MB4 => b(4), \n\
  MB3 => b(3), \n\
  MB2 => b(2), \n\
  MB1 => b(1), \n\
  MB0 => b(0), \n\
  CFB23 => '0', \n\
  CFB22 => '0', \n\
  CFB21 => '0', \n\
  CFB20 => '0', \n\
  CFB19 => '0', \n\
  CFB18 => '0', \n\
  CFB17 => '0', \n\
  CFB16 => '0', \n\
  CFB15 => '0', \n\
  CFB14 => '0', \n\
  CFB13 => '0', \n\
  CFB12 => '0', \n\
  CFB11 => '0', \n\
  CFB10 => '0', \n\
  CFB9 => '0', \n\
  CFB8 => '0', \n\
  CFB7 => '0', \n\
  CFB6 => '0', \n\
  CFB5 => '0', \n\
  CFB4 => '0', \n\
  CFB3 => '0', \n\
  CFB2 => '0', \n\
  CFB1 => '0', \n\
  CFB0 => '0', \n\
  CIN23 => '0', \n\
  CIN22 => '0', \n\
  CIN21 => '0', \n\
  CIN20 => '0', \n\
  CIN19 => '0', \n\
  CIN18 => '0', \n\
  CIN17 => '0', \n\
  CIN16 => '0', \n\
  CIN15 => '0', \n\
  CIN14 => '0', \n\
  CIN13 => '0', \n\
  CIN12 => '0', \n\
  CIN11 => '0', \n\
  CIN10 => '0', \n\
  CIN9 => '0', \n\
  CIN8 => '0', \n\
  CIN7 => '0', \n\
  CIN6 => '0', \n\
  CIN5 => '0', \n\
  CIN4 => '0', \n\
  CIN3 => '0', \n\
  CIN2 => '0', \n\
  CIN1 => '0', \n\
  CIN0 => '0', \n\
  OPADDNSUB => '1', -- TODO CHECK? \n\
  OPCINSEL => '0', \n\
  R23 => return_output(23), \n\
  R22 => return_output(22), \n\
  R21 => return_output(21), \n\
  R20 => return_output(20), \n\
  R19 => return_output(19), \n\
  R18 => return_output(18), \n\
  R17 => return_output(17), \n\
  R16 => return_output(16), \n\
  R15 => return_output(15), \n\
  R14 => return_output(14), \n\
  R13 => return_output(13), \n\
  R12 => return_output(12), \n\
  R11 => return_output(11), \n\
  R10 => return_output(10), \n\
  R9 => return_output(9), \n\
  R8 => return_output(8), \n\
  R7 => return_output(7), \n\
  R6 => return_output(6), \n\
  R5 => return_output(5), \n\
  R4 => return_output(4), \n\
  R3 => return_output(3), \n\
  R2 => return_output(2), \n\
  R1 => return_output(1), \n\
  R0 => return_output(0), \n\
  CO23 => open, \n\
  CO22 => open, \n\
  CO21 => open, \n\
  CO20 => open, \n\
  CO19 => open, \n\
  CO18 => open, \n\
  CO17 => open, \n\
  CO16 => open, \n\
  CO15 => open, \n\
  CO14 => open, \n\
  CO13 => open, \n\
  CO12 => open, \n\
  CO11 => open, \n\
  CO10 => open, \n\
  CO9 => open, \n\
  CO8 => open, \n\
  CO7 => open, \n\
  CO6 => open, \n\
  CO5 => open, \n\
  CO4 => open, \n\
  CO3 => open, \n\
  CO2 => open, \n\
  CO1 => open, \n\
  CO0 => open \n\
); \n\
");
}

//#pragma MAIN alu_test
uint24_t alu_test(
  uint1_t a_sign, uint18_t a,
  uint1_t b_sign, uint18_t b
)
{
  return alu(a_sign, a, b_sign, b);
}

//#pragma MAIN test_add
/*float_8_14_t test_add(float_8_14_t x, float_8_14_t y)
{
  return x + y;
}*/
// Float add
// BIN_OP_PLUS_float_8_14_t_float_8_14_t
float_8_14_t test_add(float_8_14_t left, float_8_14_t right)
{
  // Get exponent for left and right
  uint8_t left_exponent;
  left_exponent = float_8_14_t_21_14(left);
  uint8_t right_exponent;
  right_exponent = float_8_14_t_21_14(right);
    
  float_8_14_t x;
  float_8_14_t y;
  // Step 1: Copy inputs so that left's exponent >= than right's.
  //    Is this only needed for shift operation that takes unsigned only?
  //    ALLOW SHIFT BY NEGATIVE?????
  if ( right_exponent > left_exponent ) // Lazy switch to GT
  {
     x = right;  
     y = left;
  }
  else
  { 
     x = left;
     y = right;
  }
  
  // Step 2: Break apart into S E M
  // X
  uint14_t x_mantissa; 
  x_mantissa = float_8_14_t_13_0(x);
  uint8_t x_exponent;
  x_exponent = float_8_14_t_21_14(x);
  uint1_t x_sign;
  x_sign = float_8_14_t_22_22(x);
  // Y
  uint14_t y_mantissa;
  y_mantissa = float_8_14_t_13_0(y);
  uint8_t y_exponent;
  y_exponent = float_8_14_t_21_14(y);
  uint1_t y_sign;
  y_sign = float_8_14_t_22_22(y);
  
  // Mantissa needs +3b wider
  // Put 0's in overflow bit and sign bit
  // Put a 1 hidden bit if exponent is non-zero.
  // X
  // Determine hidden bit
  uint1_t x_hidden_bit;
  if(x_exponent == 0) // lazy swith to ==
  {
    x_hidden_bit = 0;
  }
  else
  {
    x_hidden_bit = 1;
  }
  // Apply hidden bit
  uint15_t x_mantissa_w_hidden_bit; 
  x_mantissa_w_hidden_bit = uint1_uint14(x_hidden_bit, x_mantissa);
  // Y
  // Determine hidden bit
  uint1_t y_hidden_bit;
  if(y_exponent == 0) // lazy swith to ==
  {
    y_hidden_bit = 0;
  }
  else
  {
    y_hidden_bit = 1;
  }
  // Apply hidden bit
  uint15_t y_mantissa_w_hidden_bit; 
  y_mantissa_w_hidden_bit = uint1_uint14(y_hidden_bit, y_mantissa);

  // Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
  // STEP 2.B moved here
  // Make wider for twos comp/sign
  int16_t x_mantissa_w_hidden_bit_sign_adj;
  int16_t y_mantissa_w_hidden_bit_sign_adj;
  if(x_sign) //if(x_sign == 1)
  {
    x_mantissa_w_hidden_bit_sign_adj = uint15_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int16t
  }
  else
  {
    x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
  }
  if(y_sign) // if(y_sign == 1)
  {
    y_mantissa_w_hidden_bit_sign_adj = uint15_negate(y_mantissa_w_hidden_bit);
  }
  else
  {
    y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit;
  }
  
  // Padd both x and y on right with zeros (shift left) such that 
  // when y is shifted to the right it doesnt drop mantissa lsbs (as much)
  int22_t x_mantissa_w_hidden_bit_sign_adj_rpad = int16_uint6(x_mantissa_w_hidden_bit_sign_adj, 0);
  int22_t y_mantissa_w_hidden_bit_sign_adj_rpad = int16_uint6(y_mantissa_w_hidden_bit_sign_adj, 0);

  // Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
  // Already swapped left/right based on exponent
  // diff will be >= 0
  uint8_t diff;
  diff = x_exponent - y_exponent;
  // Shift y by diff (bit manip pipelined function)
  int22_t y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;
  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = y_mantissa_w_hidden_bit_sign_adj_rpad >> diff;
  
  // Step 5: Compute sum 
  int23_t sum_mantissa;
  sum_mantissa = x_mantissa_w_hidden_bit_sign_adj_rpad + y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;

  // Step 6: Save sign flag and take absolute value of sum.
  uint1_t sum_sign;
  sum_sign = int23_22_22(sum_mantissa);
  uint22_t sum_mantissa_unsigned;
  sum_mantissa_unsigned = int23_abs(sum_mantissa);

  // Step 7: Normalize sum and exponent. (Three cases.)
  uint1_t sum_overflow;
  sum_overflow = uint22_21_21(sum_mantissa_unsigned);
  uint8_t sum_exponent_normalized;
  uint14_t sum_mantissa_unsigned_normalized;
  if (sum_overflow) //if ( sum_overflow == 1 )
  {
     // Case 1: Sum overflow.
     //         Right shift significand by 1 and increment exponent.
     sum_exponent_normalized = x_exponent + 1;
     sum_mantissa_unsigned_normalized = uint22_20_7(sum_mantissa_unsigned);
  }
  else if(sum_mantissa_unsigned == 0) // laxy switch to ==
  {
     //
     // Case 3: Sum is zero.
     sum_exponent_normalized = 0;
     sum_mantissa_unsigned_normalized = 0;
  }
  else
  {
     // Case 2: Sum is nonzero and did not overflow.
     // Dont waste zeros at start of mantissa
     // Find position of first non-zero digit from left
     // Know (sign) and (overflow) are not set
     // Hidden bit is, can narrow down to including hidden bit 
     uint21_t sum_mantissa_unsigned_narrow;
     sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
     uint4_t leading_zeros; // width = ceil(log2(len(sumsig)))
     leading_zeros = count0s_uint21(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
     // NOT CHECKING xexp < adj
     // Case 2b: Adjust significand and exponent.
     sum_exponent_normalized = x_exponent - leading_zeros;
     uint21_t sum_mantissa_unsigned_normalized_rpad = sum_mantissa_unsigned_narrow << leading_zeros;
     sum_mantissa_unsigned_normalized = uint21_19_6(sum_mantissa_unsigned_normalized_rpad);
  }
  
  // Declare the output portions
  uint14_t z_mantissa;
  uint8_t z_exponent;
  uint1_t z_sign;
  z_sign = sum_sign;
  z_exponent = sum_exponent_normalized;
  z_mantissa = sum_mantissa_unsigned_normalized;
  // Assemble output  
  return float_uint8_uint14(z_sign, z_exponent, z_mantissa);
}