// Full part string examples:
// xc7a35ticsg324-1l     Artix 7 (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xcvu33p-fsvh2104-2-e  Virtex Ultrascale Plus
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 5CGXFC9E7F35C8        Cyclone V GX
// EP4CE22F17C6          Cyclone IV
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G
// ICE40UP5K-SG48        ICE40UP
// T8F81                 Trion T8 (Xyloni)
// Ti60F225              Titanium
#pragma PART "xc7a35ticsg324-1l"

// Most recent (and more likely working) examples towards the bottom of list \/
// Please see: https://github.com/JulianKemmerer/PipelineC/wiki/Examples
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
//#include "examples/arty/src/ddr3/mig_app.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/blink.c"
//#include "examples/littleriscy/riscv.c"
//#include "examples/NexusProofOfWork/NXSTest_syn.c"
//#include "examples/fir.c"
//#include "examples/arty/src/i2s/i2s_passthrough_app.c"
//#include "examples/arty/src/audio/distortion.c"
//#include "examples/arty/src/i2s/i2s_app.c"
//#include "examples/fosix/main_bram_loopback.c"
//#include "examples/groestl/groestl.c"
//#include "examples/aes/aes.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/clock_crossing.c"
//#include "examples/pipeline_and_fsm.c"
//#include "examples/edaplay.c"
//#include "examples/fosix/main_game_clk_step.c"
//#include "examples/blink.c"
//#include "examples/llvm/rsqrtf.c"
//#include "examples/arty/src/vga/test_pattern.c"
//#include "examples/verilator/blink.c"
//#include "examples/verilator/math_pkg/u24add/u24add.c"
//#include "examples/verilator/math_pkg/u24mult/u24mult.c"
//#include "examples/verilator/math_pkg/i25sub/i25sub.c"
//#include "examples/verilator/math_pkg/fp32_to_i32/fp32_to_i32.c"
//#include "examples/verilator/math_pkg/i32_to_fp32/i32_to_fp32.c"
//#include "examples/verilator/math_pkg/fp32add/fp32add.c"
//#include "examples/verilator/math_pkg/fp32sub/fp32sub.c"
//#include "examples/verilator/math_pkg/fp32mult/fp32mult.c"
//#include "examples/verilator/math_pkg/fp32div/fp32div.c"
//#include "examples/verilator/math_pkg/rsqrtf/rsqrtf.c"
//#include "examples/arty/src/vga/test_pattern_modular.c"
//#include "examples/arty/src/vga/bouncing_images.c"
//#include "examples/pipeline.c"
//#include "examples/pipeline_feedback_on_self.c"
//#include "examples/arty/src/vga/pong.c"
//#include "examples/arty/src/vga/pong_volatile.c"
//#include "examples/arty/src/mnist/neural_network_fsm_basic.c"
//#include "examples/arty/src/mnist/neural_network_fsm_n_wide.c"
//#include "examples/arty/src/mnist/neural_network_fsm.c"
//#include "examples/fsm_style.c"
//#include "examples/arty/src/vga/mandelbrot.c"
//#include "examples/arty/src/eth/loopback_app.c"
//#include "examples/arty/src/eth/work_app.c"
#include "examples/arty/src/mnist/eth_app.c"


// Below is a bunch of recent scratch work - enjoy

/*
#include "uintN_t.h"
#include "intN_t.h"
#pragma MAIN_MHZ main 100.0
uint32_t main(uint32_t x, uint32_t y)
{
  uint32_t x_feedback;
  #pragma FEEDBACK x_feedback
  
  // This doesnt make sense/compile unless FEEDBACK pragma'd
  // x_feedback has not been assigned a value
  uint32_t x_looped_back = x_feedback;
  
  // This last assignment to x_feedback is what 
  // shows up as the first x_feedback read value
  x_feedback = x + 1;
  
  return x_looped_back + y;
}
*/

/*
#include "uintN_t.h"
#include "intN_t.h"
#pragma MAIN_MHZ pipelinetest 425.0
typedef struct outputs_t
{
  uint1_t gt;
  uint1_t lt;
  int8_t sub;
  int8_t add;
}outputs_t;
outputs_t pipelinetest(int8_t l, int8_t r)
{
  outputs_t o;
  o.gt = l > r;
  o.lt = l < r;
  o.sub = l - r;
  o.add = l + r;
  printf("l %d r %d: gt %d, lt %d, sub %d, add %d\n", l, r, o.gt, o.lt, o.sub, o.add);
  return o;
}
*/

/*
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"

int16_t mantissa_adj(uint1_t x_sign, uint15_t x_mantissa_w_hidden_bit)
{
  int16_t x_mantissa_w_hidden_bit_sign_adj;
  if(x_sign) //if(x_sign == 1)
  {
    x_mantissa_w_hidden_bit_sign_adj = uint15_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int16t
  }
  else
  {
    x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
  }
  return x_mantissa_w_hidden_bit_sign_adj;
}

int22_t manstissa_shift(int22_t y_mantissa_w_hidden_bit_sign_adj_rpad, uint8_t shift)
{
  return y_mantissa_w_hidden_bit_sign_adj_rpad >> shift;
}

// Float add
// Adds are complicated
#pragma MAIN fp_one_plus_x_test
float_8_14_t fp_one_plus_x_test(float_8_14_t right)
{
  float_8_14_t left = 1.0; // hard wire left to 1.0
  
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
  //  [sign][overflow][hidden][23 bit mantissa]
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
  x_mantissa_w_hidden_bit_sign_adj = mantissa_adj(x_sign, x_mantissa_w_hidden_bit);
  y_mantissa_w_hidden_bit_sign_adj = mantissa_adj(y_sign, y_mantissa_w_hidden_bit);
  
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
  //  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = y_mantissa_w_hidden_bit_sign_adj_rpad >> diff;
  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = manstissa_shift(y_mantissa_w_hidden_bit_sign_adj_rpad, diff);
  
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
     // Know bit25(sign) and bit24(overflow) are not set
     // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
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
*/

/*
#include "uintN_t.h"

typedef struct inner_struct_t
{
  uint8_t dummy0;
  uint8_t dummy1;
}inner_struct_t;

typedef struct outer_struct_t
{
  uint8_t u8;
  uint8_t u8_array[3];
  inner_struct_t a_struct;
  inner_struct_t struct_array[3];
}outer_struct_t;

inner_struct_t a_struct_func()
{
  static inner_struct_t a_struct = {4,5};
  return a_struct;
}

#pragma MAIN_MHZ test_wrapper 10.0
outer_struct_t test_wrapper()
{
  static outer_struct_t s = { 
    .u8 = 1,
    .u8_array = {[0]=1,2,3},
    .a_struct = {11, 22},
    .struct_array =
    {
      [2] = {.dummy0=6, .dummy1=7},
      [1] = {.dummy0=8, .dummy1=9},
      [0] = {.dummy0=10, .dummy1=11}
    }
  };
  
  return s;
}
*/


/*
#include "intN_t.h"
#pragma MAIN test1
int32_t test1(int32_t x)
{
  return x & 32768; // i32 & u16 sign ext issue
}
*/

/*
#include "uintN_t.h"
uint8_t my_modulo(uint1_t load_dividend, uint8_t dividend_in, uint8_t divisor)
{
  static uint8_t dividend;
  static uint1_t done;
  
  if(load_dividend)
  {
    dividend = dividend_in;
  }
  
  if(dividend > divisor)
  {
    dividend -= divisor;
  }
  else
  {
    done = 1;
  }

  return dividend;
}
#pragma MAIN my_tb
uint8_t my_tb()
{
  static uint1_t load_dividend = 1;
  uint8_t mm = my_modulo(load_dividend, 71, 13);
  load_dividend = 0; // Only ==1 for 1 clock cycle
  return mm;
}
*/

/*
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"


// Float GT/GTE std_logic_vector in C silly
#pragma MAIN main_test
MAIN_MHZ(main_test, 25.0)
uint32_t main_test(float activation)
{
  uint32_t max_act_label;
  float max_act = -99999.0;
  uint32_t i = 0;
  for (i = 0; i < 1; i += 1)
  {
    float act_i = activation;
    if (act_i > max_act)
    {
      max_act = act_i;
      max_act_label = 1;
    }
  }
  
  return max_act_label;
}
*/
/*
uint32_t test()
{
  static uint32_t i;
  static uint32_t j;
  static uint32_t count;
  count += 1;
  for(i = 0; i < 2; i+=1) 
  {
      count += 2;
      __clk();
      count += 3;
      for(j = 0; j < 4; j+=1)
      {
        count += 4;
        __clk();
        count += 5;
      }
      count += 6;
  }
  count += 7;
  return count;
}
*/
/*
uint32_t test()
{
  static uint32_t i;
  static uint32_t j;
  static uint32_t count;
  count += 1;
  for(i = 0; i < 2; i+=1) 
  {
    if(i==0)
    {
      count += 2;
      __clk();
    }
    else
    {
      count += 3;
      __clk();
    }
  }
  count += 7;
  return count;
}
*/
/*
#include "uintN_t.h"
uint32_t test()
{
  static uint32_t i;
  static uint32_t j;
  static uint32_t a;
  static uint32_t b;
  // Loop computing activation for each label
  for(i = 0; i < 10; i+=1) 
  {
      a += 1;
      //__clk(); // Combinatorial logic dividing marker
      for(j = 0; j < (28*28); j+=1)
      {
        b += 1;
        __clk(); // Combinatorial logic dividing marker
      }
  }
  return a + b;
}
*/
/*
// Derived fsm from inference func
#include "test_FSM.h"

#pragma MAIN_MHZ test_wrapper 10.0
uint32_t test_wrapper()
{
  test_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  test_OUTPUT_t o = test_FSM(i);
  return o.return_output;
}
*/


/*
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN_MHZ test_wrapper 10.0
uint1_t test_wrapper(float f)
{
  return f != 0.0;
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"


const uint32_t g = 1;
static const uint32_t sg = 2;

#pragma MAIN_MHZ test_wrapper1 10.0
uint32_t test_wrapper1(uint32_t x, uint1_t sel)
{
  static const uint32_t l1 = 1;
  uint32_t rv;
  if(sel)
  {
    uint32_t y = x + l1;
    uint32_t z = y + g;
    rv = z + sg;
  }
  return rv;
}
#pragma MAIN_MHZ test_wrapper2 10.0
uint32_t test_wrapper2(uint32_t x)
{
  static const uint32_t l2 = 2;
  uint32_t y = x + l2;
  uint32_t z = y + g;
  return z + sg;
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN_MHZ test_wrapper 10.0
float test_wrapper(float f, uint32_t u, uint1_t sel)
{
  float neg_f = -f;
  float const_f = 1.23;
  int32_t neg_u = -u;
  int32_t const_u = 123;
  
  float rv;
  if(sel)
  {
    rv = neg_f + -const_f;
  }
  else
  {
    rv = (float)(neg_u + -const_u);
  }
  return rv;
}
*/
/*
typedef struct inner_struct_t
{
  uint8_t dummy0;
  uint8_t dummy1;
}inner_struct_t;

typedef struct outer_struct_t
{
  uint8_t u8;
  uint8_t u8_array[3];
  inner_struct_t a_struct;
  inner_struct_t struct_array[3];
}outer_struct_t;

inner_struct_t a_struct_func()
{
  inner_struct_t a_struct = {4,5};
  return a_struct;
}

#pragma MAIN_MHZ test_wrapper 10.0
outer_struct_t test_wrapper()
{
  outer_struct_t s = { 
    .u8 = 1,
    .u8_array = {[0]=1,2,3},
    .a_struct = a_struct_func(),
    .struct_array =
    {
      [2] = {.dummy0=6, .dummy1=7},
      [1] = {.dummy0=8, .dummy1=9},
      [0] = {.dummy0=10, .dummy1=11}
    }
  };
  
  return s;
}
*/

/*
// An example user type
typedef struct complex
{
  float re;
  float im;
}complex;

// Override the '+' operator
complex BIN_OP_PLUS_complex_complex(complex left, complex right)
{
  complex rv;
  rv.re = left.re + right.re;
  rv.im = left.im + right.im;
  return rv;
}
complex BIN_OP_PLUS_complex_float(complex left, float right)
{
  complex rv;
  rv.re = left.re + right;
  rv.im = left.im + right;
  return rv;
}
// Override the '*' operator
// Implementation to use when inferred DSPs for multiplies are used
complex BIN_OP_INFERRED_MULT_complex_complex(complex left, complex right)
{
  complex rv;
  rv.re = left.re * right.re;
  rv.im = left.im * right.im;
  return rv;
}
// Implementation to use when multipliers are implemented in logic/FPGA fabric
complex BIN_OP_MULT_complex_complex(complex left, complex right)
{
  complex rv;
  rv.re = left.re * right.re;
  rv.im = left.im * right.im;
  return rv;
}
// Override the '!' operator
complex UNARY_OP_NOT_complex(complex expr)
{
  complex rv;
  rv.re = expr.re * -1.0;
  rv.im = expr.im * -1.0;
  return rv;
}
// Test main funcs
#pragma MAIN_MHZ overload0 1.0
complex overload0(complex x, complex y)
{
  return x + y;
}
#pragma MAIN_MHZ overload1 1.0
complex overload1(complex x, float f)
{
  return x + f;
}
#pragma MAIN_MHZ overload2 1.0
complex overload2(complex x, complex y)
{
  return x * y;
}
#pragma MAIN_MHZ overload3 1.0
complex overload3(complex x)
{
  return !x;
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
#pragma MAIN_MHZ the_add 1.0
//BIN_OP_INFERRED_MULT_float_8_16_t_float_8_16_t_float_8_16_t
float_8_16_t the_mul(float_8_16_t left, float_8_16_t right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  uint16_t x_mantissa;
  x_mantissa = float_8_16_t_15_0(left);
  uint9_t x_exponent_wide;
  x_exponent_wide = float_8_16_t_23_16(left);
  uint1_t x_sign;
  x_sign = float_8_16_t_24_24(left);
  // RIGHT
  uint16_t y_mantissa;
  y_mantissa = float_8_16_t_15_0(right);
  uint9_t y_exponent_wide;
  y_exponent_wide = float_8_16_t_23_16(right);
  uint1_t y_sign;
  y_sign = float_8_16_t_24_24(right);
  
  // Declare the output portions
  uint16_t z_mantissa;
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
    uint17_t aux2_x;
    uint17_t aux2_y;
    uint34_t aux2;
    uint7_t BIAS;
    BIAS = 127;
    
    aux2_x = uint1_uint16(1, x_mantissa);
    aux2_y = uint1_uint16(1, y_mantissa);
    aux2 =  aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = uint34_33_33(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = uint34_32_17(aux2); 
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = uint34_31_16(aux2); 
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
  return float_uint8_uint16(z_sign, z_exponent, z_mantissa);
}

//BIN_OP_PLUS_float_8_16_t_float_8_16_t_float_8_16_t
float_8_16_t the_add(float_8_16_t left, float_8_16_t right)
{
  // Get exponent for left and right
  uint8_t left_exponent;
  left_exponent = float_8_16_t_23_16(left);
  uint8_t right_exponent;
  right_exponent = float_8_16_t_23_16(right);
    
  float_8_16_t x;
  float_8_16_t y;
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
  uint16_t x_mantissa; 
  x_mantissa = float_8_16_t_15_0(x);
  uint8_t x_exponent;
  x_exponent = float_8_16_t_23_16(x);
  uint1_t x_sign;
  x_sign = float_8_16_t_24_24(x);
  // Y
  uint16_t y_mantissa;
  y_mantissa = float_8_16_t_15_0(y);
  uint8_t y_exponent;
  y_exponent = float_8_16_t_23_16(y);
  uint1_t y_sign;
  y_sign = float_8_16_t_24_24(y);
  
  // Mantissa needs +3b wider
  //  [sign][overflow][hidden][23 bit mantissa]
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
  uint17_t x_mantissa_w_hidden_bit; 
  x_mantissa_w_hidden_bit = uint1_uint16(x_hidden_bit, x_mantissa);
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
  uint17_t y_mantissa_w_hidden_bit; 
  y_mantissa_w_hidden_bit = uint1_uint16(y_hidden_bit, y_mantissa);

  // Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
  // STEP 2.B moved here
  // Make wider for twos comp/sign
  int18_t x_mantissa_w_hidden_bit_sign_adj;
  int18_t y_mantissa_w_hidden_bit_sign_adj;
  if(x_sign) //if(x_sign == 1)
  {
    x_mantissa_w_hidden_bit_sign_adj = uint17_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int18t
  }
  else
  {
    x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
  }
  if(y_sign) // if(y_sign == 1)
  {
    y_mantissa_w_hidden_bit_sign_adj = uint17_negate(y_mantissa_w_hidden_bit);
  }
  else
  {
    y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit;
  }
  
  // Padd both x and y on right with zeros (shift left) such that 
  // when y is shifted to the right it doesnt drop mantissa lsbs (as much)
  int24_t x_mantissa_w_hidden_bit_sign_adj_rpad = int18_uint6(x_mantissa_w_hidden_bit_sign_adj, 0);
  int24_t y_mantissa_w_hidden_bit_sign_adj_rpad = int18_uint6(y_mantissa_w_hidden_bit_sign_adj, 0);

  // Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
  // Already swapped left/right based on exponent
  // diff will be >= 0
  uint8_t diff;
  diff = x_exponent - y_exponent;
  // Shift y by diff (bit manip pipelined function)
  int24_t y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;
  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = y_mantissa_w_hidden_bit_sign_adj_rpad >> diff;
  
  // Step 5: Compute sum 
  int25_t sum_mantissa;
  sum_mantissa = x_mantissa_w_hidden_bit_sign_adj_rpad + y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;

  // Step 6: Save sign flag and take absolute value of sum.
  uint1_t sum_sign;
  sum_sign = int25_24_24(sum_mantissa);
  uint24_t sum_mantissa_unsigned;
  sum_mantissa_unsigned = int25_abs(sum_mantissa);

  // Step 7: Normalize sum and exponent. (Three cases.)
  uint1_t sum_overflow;
  sum_overflow = uint24_23_23(sum_mantissa_unsigned);
  uint8_t sum_exponent_normalized;
  uint16_t sum_mantissa_unsigned_normalized;
  if (sum_overflow) //if ( sum_overflow == 1 )
  {
     // Case 1: Sum overflow.
     //         Right shift significand by 1 and increment exponent.
     sum_exponent_normalized = x_exponent + 1;
     sum_mantissa_unsigned_normalized = uint24_22_7(sum_mantissa_unsigned);
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
     // Know bit25(sign) and bit24(overflow) are not set
     // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
     uint23_t sum_mantissa_unsigned_narrow;
     sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
     uint5_t leading_zeros; // width = ceil(log2(len(sumsig)))
     leading_zeros = count0s_uint23(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
     // NOT CHECKING xexp < adj
     // Case 2b: Adjust significand and exponent.
     sum_exponent_normalized = x_exponent - leading_zeros;
     uint23_t sum_mantissa_unsigned_normalized_rpad = sum_mantissa_unsigned_narrow << leading_zeros;
     sum_mantissa_unsigned_normalized = uint23_21_6(sum_mantissa_unsigned_normalized_rpad);
  }
  
  // Declare the output portions
  uint16_t z_mantissa;
  uint8_t z_exponent;
  uint1_t z_sign;
  z_sign = sum_sign;
  z_exponent = sum_exponent_normalized;
  z_mantissa = sum_mantissa_unsigned_normalized;
  // Assemble output  
  return float_uint8_uint16(z_sign, z_exponent, z_mantissa);
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"

#pragma MAIN my_cast
float_5_10_t my_cast(float_8_23_t fp32)
{
  float_5_10_t fp16 = fp32;
  return fp16;
}
*/
//https://github.com/fbrosser/DSP48E1-FP/blob/master/src/FPMult_DSP48E1/FPMult_ExecuteModule.v

/*#pragma MAIN_MHZ fp32_mul_orig 1.0
float_8_23_t fp32_mul_orig(float_8_23_t x, float_8_23_t y)
{
  return x*y;
}*/
/*
#pragma MAIN_MHZ fp32_add_orig 1.0
float_8_23_t fp32_add_orig(float_8_23_t x, float_8_23_t y)
{
  return x+y;
}
*/

/*
#pragma MAIN_MHZ new_count0s 1.0
uint6_t new_count0s(uint32_t a32)
{
  uint16_t a16;
  uint8_t   a8;
  uint4_t   a4;
  uint2_t   a2;
  uint2_t   a1;

  uint1_t b16 = (a32 >> 16) == 0; a16 = b16 ? a32 : a32 >> 16;
  uint1_t b8  = (a16 >>  8) == 0;  a8 =  b8 ? a16 : a16 >> 8;
  uint1_t b4  = ( a8 >>  4) == 0;  a4 =  b4 ?  a8 :  a8 >> 4;
  uint1_t b2  = ( a4 >>  2) == 0;  a2 =  b2 ?  a4 :  a4 >> 2;
  uint1_t b1  = ( a2 >>  1) == 0;  a1 =  b1 ?  a2 :  a2 >> 1;

  //uint5_t r = ((uint5_t)b16 << 4) | ((uint4_t)b8 << 3) | ((uint3_t)b4 << 2) | ((uint2_t)b2 << 1) | (uint1_t)b1;
  
  uint1_t r_bits[5];
  r_bits[0] = b1;
  r_bits[1] = b2;
  r_bits[2] = b4;
  r_bits[3] = b8;
  r_bits[4] = b16;
  uint5_t r = uint1_array5_le(r_bits);
  
  return ((r == 31) & (a1 == 0)) ? (uint6_t)32 : (uint6_t)r;
}*/
/*
#pragma MAIN_MHZ orig_count0s 1.0
uint6_t orig_count0s(uint32_t a32)
{
  return count0s_uint32(a32);
}
*/


/*
#define mul24x24_truncated mul24x24_truncated24 //function to test (8,9,12,24 bits mults)
//#define FP32MUL_HIGH_PRECISION //if disabled, 12 and 8 bit gives up to 3 and 5 LSB error (respectively)

//multiplier primitive
uint24_t mul12x12(uint12_t a, uint12_t b) { return a*b; }
//multiplier-add primitive
uint25_t mul12x12add(uint12_t a, uint12_t b, uint25_t c) { return mul12x12(a,b)+c; }

uint24_t mul24x24_truncated12(uint24_t a, uint24_t b)
{
   //(a1+a0)*(b1+b0) TRUNCATED: (a1*b1 + a1*b0+a0*b1)
   //fp32_t x = {.u = a };
   //fp32_t y = {.u = b };
   uint12_t x_11_00 = uint24_11_0(a);
   uint12_t x_23_12 = uint24_23_12(a);
   uint12_t y_11_00 = uint24_11_0(b);
   uint12_t y_23_12 = uint24_23_12(b);

   const uint12_t rounding = 1<<11;
#ifdef FP32MUL_HIGH_PRECISION
   uint25_t a0b0 = (mul12x12add(x_11_00>>9, y_11_00>>9, 0)<<6) & 0xF00; //3x3 mult, 4 bit MSB result
   uint25_t a0b1 = mul12x12add(x_11_00, y_23_12, a0b0 + (uint25_t)rounding);
#else                                   
   uint25_t a0b1 = mul12x12add(x_11_00, y_23_12, (uint25_t)rounding);
#endif                                  
   uint25_t a1b0 = mul12x12add(x_23_12, y_11_00, a0b1);
   uint25_t a1b1 = mul12x12add(x_23_12, y_23_12, a1b0>>12);
   return (uint24_t)a1b1;
}

//multiplier primitive
uint18_t mul9x9(uint9_t a, uint9_t b) { return a*b; }
//multiplier-add primitive
uint20_t mul9x9add(uint9_t a, uint9_t b, uint20_t c) { return mul9x9(a,b)+c; }

uint24_t mul24x24_truncated9(uint24_t a, uint24_t b)
{
   //(a2+a1+a0)*(b2+b1+b0) TRUNCATED: (a2*b2 + a2*b1+a1*b2 + a2*b0+a1*b1+a0*b2)
   //fp32_t x = {.u = a << 3 };
   //fp32_t y = {.u = b << 3 };
   uint9_t x_17_09 = uint27_17_9(a);
   uint9_t x_08_00 = uint27_8_0(a);
   uint9_t x_26_18 = uint27_26_18(a);
   uint9_t y_17_09 = uint27_17_9(b);
   uint9_t y_08_00 = uint27_8_0(b);
   uint9_t y_26_18 = uint27_26_18(b);
  
   const uint32_t rounding = (1<<8)<<3;

   uint20_t r11 = mul9x9add(x_17_09, y_17_09, (uint20_t)rounding);
   uint20_t r02 = mul9x9add(x_08_00, y_26_18, r11);
   uint20_t r20 = mul9x9add(x_26_18, y_08_00, r02);
   uint20_t r21 = mul9x9add(x_26_18, y_17_09, r20 >> 9);
   uint20_t r12 = mul9x9add(x_17_09, y_26_18, r21);
   uint18_t r2 = mul9x9(x_26_18, y_26_18);

   return ((r2 << 9) + r12) >> 3;
}

//multiplier primitive
uint16_t mul8x8(uint8_t a, uint8_t b) { return a*b; }
//multiplier-add primitive
uint18_t mul8x8add(uint8_t a, uint8_t b, uint18_t c) { return mul8x8(a,b)+c; }

uint24_t mul24x24_truncated8(uint24_t a, uint24_t b)
{
   //(a2+a1+a0)*(b2+b1+b0) TRUNCATED: (a2*b2 + a2*b1+a1*b2 + a2*b0+a1*b1+a0*b2)
   //fp32_t x = {.u = a };
   //fp32_t y = {.u = b };
   uint8_t x_07_00 = uint24_7_0(a);
   uint8_t x_15_08 = uint24_15_8(a);
   uint8_t x_23_16 = uint24_23_16(a);
   uint8_t y_07_00 = uint24_7_0(b);
   uint8_t y_15_08 = uint24_15_8(b);
   uint8_t y_23_16 = uint24_23_16(b);
    
   const uint8_t rounding = 1<<7;
#ifdef FP32MUL_HIGH_PRECISION
   uint8_t r0a = (x_15_08 >> 4)*(y_07_00 >> 4) & 0xF8; //mult4x4 to 5 msb
   uint8_t r0b = (x_07_00 >> 4)*(y_15_08 >> 4) & 0xF8; //mult4x4 to 5 msb
   uint18_t r11 = mul8x8add(x_15_08, y_15_08, r0a + r0b + rounding);
#else                                 
   uint18_t r11 = mul8x8add(x_15_08, y_15_08, rounding);
#endif                                
   uint18_t r02 = mul8x8add(x_07_00, y_23_16, r11);
   uint18_t r20 = mul8x8add(x_23_16, y_07_00, r02);
   uint16_t r21 = mul8x8add(x_23_16, y_15_08, r20 >> 8);
   uint18_t r12 = mul8x8add(x_15_08, y_23_16, r21);
   uint16_t r2 = mul8x8(x_23_16, y_23_16);

   return (r2 << 8) + r12;
}

uint24_t mul24x24_truncated24(uint24_t a, uint24_t b)
{ 
  //uint48_t mround = (uint48_t)a*(uint48_t)b + (1<<23);
  uint48_t mround = a*b + (1<<23);
  return mround >> 24;
}

uint25_t fixpoint_mul23x23(uint23_t a, uint23_t b)
{
  //(1+a)+(1+b) = 1+a+b+a*b, 0 <= inputs < 1
  uint24_t mul = mul24x24_truncated((uint24_t)a, (uint24_t)b);
  return (1<<23) + a + b + (mul<<1);
}

#pragma MAIN_MHZ fp32_mul 1000.0
float fp32_mul(float a, float b)
{
  uint23_t a_mantissa = float_22_0(a);
  uint23_t b_mantissa = float_22_0(b);
  uint8_t a_exp = float_30_23(a);
  uint8_t b_exp = float_30_23(b);
  uint1_t a_sign = float_31_31(a);
  uint1_t b_sign = float_31_31(b);

  uint25_t m = fixpoint_mul23x23(a_mantissa, b_mantissa);
  uint1_t expadj = m >> 24;
  if(expadj)
    m = m >> 1;
    
  uint10_t exp = a_exp + b_exp + expadj;
#if 1
  exp = exp - 127;
#else
  //denormal: NEEDS CHECKING
  //printf("exp %d, a=%d, b=%d, adj=%d\n", exp, a.exp, b.exp, expadj);
  if(exp >= 127)
  {
    if(exp < 127+127)
    {
      exp = exp - 127;
    }
    else
    {
      exp = 255;
      m = 0;
    }
  }
  else
  {
    exp = 0;
    m = 0;
  }
#endif
  uint1_t sign = a_sign ^ b_sign;
  uint23_t mantissa = m;

  return float_uint1_uint8_uint23(sign,exp,mantissa);
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN_MHZ count0s_uint32_shift_sub 1000.0
uint6_t count0s_uint32_shift_sub(uint32_t x)
{
  uint6_t rv;
  uint6_t n = 32;
  uint16_t y16 = x >>16; if (y16 != 0) {n = n -16; x = y16;}
  uint8_t y8 = x >> 8; if (y8 != 0) {n = n - 8; x = y8;}
  uint4_t y4 = x >> 4; if (y4 != 0) {n = n - 4; x = y4;}
  uint2_t y2 = x >> 2; if (y2 != 0) {n = n - 2; x = y2;}
  uint1_t y1 = x >> 1; if (y1 != 0) {rv = n - 2;} else {rv = n - x;}
  return rv;
}
*/
/*
#pragma MAIN_MHZ count0s_uint32_adding_loop 1000.0
uint6_t count0s_uint32_adding_loop(uint32_t x)
{
  uint6_t res;
  uint1_t all_zeros_so_far = 1;
  int32_t i;
  for(i=(32-1); i>=0; i-=1)
  {
    uint1_t left_bit_one = uint32_31_31(x);
    uint1_t left_bit_zero = !left_bit_one;
    // increment if left bit is zero and not found one yet
    res += (left_bit_zero & all_zeros_so_far);
    all_zeros_so_far &= left_bit_zero;
    x = x << 1;
  }
  return res;
}
*/

/*
#pragma MAIN_MHZ count0s_uint32_array_add 1000.0
uint6_t count0s_uint32_array_add(uint32_t x)
{
  uint1_t bits_to_sum[32];
  uint1_t all_zeros_so_far = 1;
  int32_t i;
  for(i=(32-1); i>=0; i-=1)
  {
    uint1_t left_bit_one = uint32_31_31(x);
    uint1_t left_bit_zero = !left_bit_one;
    // increment if left bit is zero and not found one yet
    bits_to_sum[i] = (left_bit_zero & all_zeros_so_far);
    all_zeros_so_far &= left_bit_zero;
    x = x << 1;
  }
  uint6_t res = uint1_array_sum32(bits_to_sum);
  return res;
}
*/
/*
#pragma MAIN_MHZ count0s_uint32_orig 1000.0
uint6_t count0s_uint32_orig(uint32_t x)
{
  // First do all the compares in parallel
  // All zeros has has many zeros as width
  uint1_t leading32 = (x==0);
  
  uint1_t leading1;
  leading1 = uint32_31_30(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading2;
  leading2 = uint32_31_29(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading3;
  leading3 = uint32_31_28(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading4;
  leading4 = uint32_31_27(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading5;
  leading5 = uint32_31_26(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading6;
  leading6 = uint32_31_25(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading7;
  leading7 = uint32_31_24(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading8;
  leading8 = uint32_31_23(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading9;
  leading9 = uint32_31_22(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading10;
  leading10 = uint32_31_21(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading11;
  leading11 = uint32_31_20(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading12;
  leading12 = uint32_31_19(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading13;
  leading13 = uint32_31_18(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading14;
  leading14 = uint32_31_17(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading15;
  leading15 = uint32_31_16(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading16;
  leading16 = uint32_31_15(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading17;
  leading17 = uint32_31_14(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading18;
  leading18 = uint32_31_13(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading19;
  leading19 = uint32_31_12(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading20;
  leading20 = uint32_31_11(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading21;
  leading21 = uint32_31_10(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading22;
  leading22 = uint32_31_9(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading23;
  leading23 = uint32_31_8(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading24;
  leading24 = uint32_31_7(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading25;
  leading25 = uint32_31_6(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading26;
  leading26 = uint32_31_5(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading27;
  leading27 = uint32_31_4(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading28;
  leading28 = uint32_31_3(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading29;
  leading29 = uint32_31_2(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading30;
  leading30 = uint32_31_1(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t leading31;
  leading31 = uint32_31_0(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?
  uint1_t sum1;
  if(leading1)
  {
    sum1 = 1;
  }
  else
  {
    sum1 = 0;
  }
  
  uint2_t sum2;
  if(leading2)
  {
    sum2 = 2;
  }
  else
  {
    sum2 = 0;
  }
  
  uint2_t sum3;
  if(leading3)
  {
    sum3 = 3;
  }
  else
  {
    sum3 = 0;
  }
  
  uint3_t sum4;
  if(leading4)
  {
    sum4 = 4;
  }
  else
  {
    sum4 = 0;
  }
  
  uint3_t sum5;
  if(leading5)
  {
    sum5 = 5;
  }
  else
  {
    sum5 = 0;
  }
  
  uint3_t sum6;
  if(leading6)
  {
    sum6 = 6;
  }
  else
  {
    sum6 = 0;
  }
  
  uint3_t sum7;
  if(leading7)
  {
    sum7 = 7;
  }
  else
  {
    sum7 = 0;
  }
  
  uint4_t sum8;
  if(leading8)
  {
    sum8 = 8;
  }
  else
  {
    sum8 = 0;
  }
  
  uint4_t sum9;
  if(leading9)
  {
    sum9 = 9;
  }
  else
  {
    sum9 = 0;
  }
  
  uint4_t sum10;
  if(leading10)
  {
    sum10 = 10;
  }
  else
  {
    sum10 = 0;
  }
  
  uint4_t sum11;
  if(leading11)
  {
    sum11 = 11;
  }
  else
  {
    sum11 = 0;
  }
  
  uint4_t sum12;
  if(leading12)
  {
    sum12 = 12;
  }
  else
  {
    sum12 = 0;
  }
  
  uint4_t sum13;
  if(leading13)
  {
    sum13 = 13;
  }
  else
  {
    sum13 = 0;
  }
  
  uint4_t sum14;
  if(leading14)
  {
    sum14 = 14;
  }
  else
  {
    sum14 = 0;
  }
  
  uint4_t sum15;
  if(leading15)
  {
    sum15 = 15;
  }
  else
  {
    sum15 = 0;
  }
  
  uint5_t sum16;
  if(leading16)
  {
    sum16 = 16;
  }
  else
  {
    sum16 = 0;
  }
  
  uint5_t sum17;
  if(leading17)
  {
    sum17 = 17;
  }
  else
  {
    sum17 = 0;
  }
  
  uint5_t sum18;
  if(leading18)
  {
    sum18 = 18;
  }
  else
  {
    sum18 = 0;
  }
  
  uint5_t sum19;
  if(leading19)
  {
    sum19 = 19;
  }
  else
  {
    sum19 = 0;
  }
  
  uint5_t sum20;
  if(leading20)
  {
    sum20 = 20;
  }
  else
  {
    sum20 = 0;
  }
  
  uint5_t sum21;
  if(leading21)
  {
    sum21 = 21;
  }
  else
  {
    sum21 = 0;
  }
  
  uint5_t sum22;
  if(leading22)
  {
    sum22 = 22;
  }
  else
  {
    sum22 = 0;
  }
  
  uint5_t sum23;
  if(leading23)
  {
    sum23 = 23;
  }
  else
  {
    sum23 = 0;
  }
  
  uint5_t sum24;
  if(leading24)
  {
    sum24 = 24;
  }
  else
  {
    sum24 = 0;
  }
  
  uint5_t sum25;
  if(leading25)
  {
    sum25 = 25;
  }
  else
  {
    sum25 = 0;
  }
  
  uint5_t sum26;
  if(leading26)
  {
    sum26 = 26;
  }
  else
  {
    sum26 = 0;
  }
  
  uint5_t sum27;
  if(leading27)
  {
    sum27 = 27;
  }
  else
  {
    sum27 = 0;
  }
  
  uint5_t sum28;
  if(leading28)
  {
    sum28 = 28;
  }
  else
  {
    sum28 = 0;
  }
  
  uint5_t sum29;
  if(leading29)
  {
    sum29 = 29;
  }
  else
  {
    sum29 = 0;
  }
  
  uint5_t sum30;
  if(leading30)
  {
    sum30 = 30;
  }
  else
  {
    sum30 = 0;
  }
  
  uint5_t sum31;
  if(leading31)
  {
    sum31 = 31;
  }
  else
  {
    sum31 = 0;
  }
  
  uint6_t sum32;
  if(leading32)
  {
    sum32 = 32;
  }
  else
  {
    sum32 = 0;
  }
  
  // Binary tree OR of "sums", can sine only one will be set

  // Layer 0
 uint2_t sum_layer0_node0;
  sum_layer0_node0 = sum1 | sum2;
 uint3_t sum_layer0_node1;
  sum_layer0_node1 = sum3 | sum4;
 uint3_t sum_layer0_node2;
  sum_layer0_node2 = sum5 | sum6;
 uint4_t sum_layer0_node3;
  sum_layer0_node3 = sum7 | sum8;
 uint4_t sum_layer0_node4;
  sum_layer0_node4 = sum9 | sum10;
 uint4_t sum_layer0_node5;
  sum_layer0_node5 = sum11 | sum12;
 uint4_t sum_layer0_node6;
  sum_layer0_node6 = sum13 | sum14;
 uint5_t sum_layer0_node7;
  sum_layer0_node7 = sum15 | sum16;
 uint5_t sum_layer0_node8;
  sum_layer0_node8 = sum17 | sum18;
 uint5_t sum_layer0_node9;
  sum_layer0_node9 = sum19 | sum20;
 uint5_t sum_layer0_node10;
  sum_layer0_node10 = sum21 | sum22;
 uint5_t sum_layer0_node11;
  sum_layer0_node11 = sum23 | sum24;
 uint5_t sum_layer0_node12;
  sum_layer0_node12 = sum25 | sum26;
 uint5_t sum_layer0_node13;
  sum_layer0_node13 = sum27 | sum28;
 uint5_t sum_layer0_node14;
  sum_layer0_node14 = sum29 | sum30;
 uint6_t sum_layer0_node15;
  sum_layer0_node15 = sum31 | sum32;

  // Layer 1
 uint3_t sum_layer1_node0;
  sum_layer1_node0 = sum_layer0_node0 | sum_layer0_node1;
 uint4_t sum_layer1_node1;
  sum_layer1_node1 = sum_layer0_node2 | sum_layer0_node3;
 uint4_t sum_layer1_node2;
  sum_layer1_node2 = sum_layer0_node4 | sum_layer0_node5;
 uint5_t sum_layer1_node3;
  sum_layer1_node3 = sum_layer0_node6 | sum_layer0_node7;
 uint5_t sum_layer1_node4;
  sum_layer1_node4 = sum_layer0_node8 | sum_layer0_node9;
 uint5_t sum_layer1_node5;
  sum_layer1_node5 = sum_layer0_node10 | sum_layer0_node11;
 uint5_t sum_layer1_node6;
  sum_layer1_node6 = sum_layer0_node12 | sum_layer0_node13;
 uint6_t sum_layer1_node7;
  sum_layer1_node7 = sum_layer0_node14 | sum_layer0_node15;

  // Layer 2
 uint4_t sum_layer2_node0;
  sum_layer2_node0 = sum_layer1_node0 | sum_layer1_node1;
 uint5_t sum_layer2_node1;
  sum_layer2_node1 = sum_layer1_node2 | sum_layer1_node3;
 uint5_t sum_layer2_node2;
  sum_layer2_node2 = sum_layer1_node4 | sum_layer1_node5;
 uint6_t sum_layer2_node3;
  sum_layer2_node3 = sum_layer1_node6 | sum_layer1_node7;

  // Layer 3
 uint5_t sum_layer3_node0;
  sum_layer3_node0 = sum_layer2_node0 | sum_layer2_node1;
 uint6_t sum_layer3_node1;
  sum_layer3_node1 = sum_layer2_node2 | sum_layer2_node3;

  // Layer 4
 uint6_t sum_layer4_node0;
  sum_layer4_node0 = sum_layer3_node0 | sum_layer3_node1;

  // Return
  uint6_t rv;
  rv = sum_layer4_node0;
  return rv;
}
*/
/*
#include "uintN_t.h
#pragma MAIN_MHZ bin_op_sl 1000.0
uint32_t bin_op_sl(uint32_t left, uint5_t right)
{
  // Use N mux
  return uint32_mux32(right,
      left,
      uint32_uint1(left, 0),
      uint32_uint2(left, 0),
      uint32_uint3(left, 0),
      uint32_uint4(left, 0),
      uint32_uint5(left, 0),
      uint32_uint6(left, 0),
      uint32_uint7(left, 0),
      uint32_uint8(left, 0),
      uint32_uint9(left, 0),
      uint32_uint10(left, 0),
      uint32_uint11(left, 0),
      uint32_uint12(left, 0),
      uint32_uint13(left, 0),
      uint32_uint14(left, 0),
      uint32_uint15(left, 0),
      uint32_uint16(left, 0),
      uint32_uint17(left, 0),
      uint32_uint18(left, 0),
      uint32_uint19(left, 0),
      uint32_uint20(left, 0),
      uint32_uint21(left, 0),
      uint32_uint22(left, 0),
      uint32_uint23(left, 0),
      uint32_uint24(left, 0),
      uint32_uint25(left, 0),
      uint32_uint26(left, 0),
      uint32_uint27(left, 0),
      uint32_uint28(left, 0),
      uint32_uint29(left, 0),
      uint32_uint30(left, 0),
      uint32_uint31(left, 0)
  );
}
*/
/*
//#pragma MAIN_MHZ barrel_shl 1000.0
#pragma MAIN barrel_shl
uint32_t barrel_shl(uint32_t v0, uint5_t n)
{
  uint32_t v1 = n &  1 ? (v0 << 1) : v0;
  uint32_t v2 = n &  2 ? (v1 << 2) : v1;
  uint32_t v3 = n &  4 ? (v2 << 4) : v2;
  uint32_t v4 = n &  8 ? (v3 << 8) : v3;
  uint32_t v5 = n & 16 ? (v4 <<16) : v4;
  return v5;
}*/
/*
#pragma MAIN_MHZ barrel_shl_fixed 1000.0
uint32_t barrel_shl_fixed(uint32_t v0, uint5_t n)
{
  uint32_t v1 = uint32_0_0(n) ? (v0 << 1) : v0;
  uint32_t v2 = uint32_1_1(n) ? (v1 << 2) : v1;
  uint32_t v3 = uint32_2_2(n) ? (v2 << 4) : v2;
  uint32_t v4 = uint32_3_3(n) ? (v3 << 8) : v3;
  uint32_t v5 = uint32_4_4(n) ? (v4 << 16) : v4;
  return v5;
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN i_to_f
float i_to_f(int32_t i)
{
  return (float)i;
}
#pragma MAIN f_to_i
int32_t f_to_i(float f)
{
  return (int32_t)f;
}
*/


//#include "uintN_t.h"
/*#pragma MAIN_MHZ my_add 1000.0
uint64_t my_add(uint64_t a, uint64_t b)
{
  return a + b;
}*/
/*#pragma MAIN_MHZ my_mux 1000.0
uint1_t my_mux(uint1_t a[512], uint32_t i)
{
  return a[i];
}*/


/*
#include "uintN_t.h"

uint8_t shared_region(uint8_t val, uint8_t wr_en)
{
  static uint8_t the_reg;
  uint8_t rd_data = the_reg;
  if(wr_en)
  {
    the_reg = val;
  }
  return rd_data;
}
// A single instance region, ex. only one 8b the_reg
#include "shared_region_SINGLE_INST.h"

void incrementer_thread()
{
  static uint8_t local_reg;
  while(1)
  {
    local_reg = shared_region(local_reg, 1);
    local_reg += 1;
  }
}
#include "incrementer_thread_FSM.h"

// First instance of thread
#pragma MAIN_MHZ main_0 100.0
incrementer_thread_OUTPUT_t main_0(incrementer_thread_INPUT_t i)
{
  incrementer_thread_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  incrementer_thread_OUTPUT_t o = incrementer_thread_FSM(i);
  return o;
}
// Second instance of thread
#pragma MAIN_MHZ main_1 100.0
incrementer_thread_OUTPUT_t main_1(incrementer_thread_INPUT_t i)
{
  incrementer_thread_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  incrementer_thread_OUTPUT_t o = incrementer_thread_FSM(i);
  return o;
}
*/

/*
#include "uintN_t.h"

// Include Arty modules
// with globally visible port/wires like
// 'leds' and 'switches'
#include "examples/arty/src/leds/leds.c"
#include "examples/arty/src/switches/switches.c"

// Since multiple 'main' instances w/ WIRE_WRITE
// Identify which instance drives the LEDsfi
// Just need any part of hierarchical path
// that can uniquely idenitify an inst
#pragma ID_INST leds main_1/my_inst[1]

// Full path from main instance on would work too

// A func driving global 'leds' wire
// and reading global 'switches' wire
void duplicated_read_write_func()
{
  static uint4_t leds_reg;
  // leds = leds_reg;
  WIRE_WRITE(uint4_t, leds, leds_reg)
  // leds_reg = switches;
  WIRE_READ(uint4_t, leds_reg, switches)
}

#pragma MAIN_MHZ main_0 100.0
void main_0()
{
  #pragma INST_NAME my_inst[0]
  duplicated_read_write_func();
}

#pragma MAIN_MHZ main_1 100.0
void main_1()
{
  #pragma INST_NAME my_inst[1]
  duplicated_read_write_func();
}
*/

/*
// N instances of the func
#define N 2
#pragma MAIN_MHZ rw_n_times 100.0
void rw_n_times(uint4_t x[N])
{
  uint32_t i;
  for(i=0;i<N;i+=1)
  {
    #pragma INST_NAME my_inst i
    read_write_func(x[i]);
  }
}*/


/*
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN func_a
uint8_t func_a(uint8_t x)
{
  // Two instances of func b
  for(i=0;i<2;i+=1)
  {
    #pragma INST_NAME func_b i
    .. func_b(x) ...
  }
}

// A globally visible port/wire
uint8_t global_wire_b_to_c;
#pragma WIRE global_wire_b_to_c func_a.func_b[0]

uint8_t func_b(uint8_t x)
{

  // Driver side of wire
  WRITE(global_wire_b_to_c, some_value);

}
uint8_t func_c(...)
{

  // Reading side of wire
  some_value = READ(global_wire_b_to_c);

}
*/

/*
#pragma PART "LFE5U-45F-8BG256I"

#include "uintN_t.h"

#pragma MAIN_MHZ popcount 440.0
uint8_t popcount(uint1_t bits[64*12])
{
  // Built in binary tree operators on arrays
  uint8_t result = uint1_array_sum768(bits);
  return result;
}
*/


/*
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN_MHZ main2 100.0

int32_t main2(uint1_t sel0)
{
  int32_t temp;
  
  if(sel0)
  {
    int32_t unused;
    unused = sel0 + 1;
    temp = unused + 1;
  }
  else
  {
    int32_t unused;
    unused = 2;
  }
  return temp;
}


int32_t main(uint2_t sel,int32_t in0,int32_t in1,int32_t in2,int32_t in3)
{
  // Layer 0
    
  // Get sel bit
  uint1_t sel0;
  sel0 = uint2_0_0(sel);

  int32_t layer0_node0;
  // Do regular mux
  if(sel0)
  {
    layer0_node0 = in1;
  }
  else
  {
    layer0_node0 = in0;
  }
  
  int32_t layer0_node1;
  // Do regular mux
  if(sel0)
  {
    layer0_node1 = in3;
  }
  else
  {
    layer0_node1 = in2;
  }
  
  // Layer 1
    
  // Get sel bit
  uint1_t sel1;
  sel1 = uint2_1_1(sel);

  int32_t layer1_node0;
  // Do regular mux
  if(sel1)
  {
    layer1_node0 = layer0_node1;
  }
  else
  {
    layer1_node0 = layer0_node0;
  }
   
  return layer1_node0;
}
*/

/*
#include "uintN_t.h"
typedef struct point_t
{
  uint8_t x;
  uint8_t y;
}point_t;
typedef struct square_t
{
  point_t tl;
  point_t bl;
}square_t;
//#include "uint8_t_array_N_t.h"
//#include "uint8_t_bytes_t.h"
//#include "uint32_t_bytes_t.h"
#include "square_t_bytes_t.h"

#pragma MAIN_MHZ main 100.0
square_t main(square_t s)
{
  return s;
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 100.0
uint8_t main(uint8_t inc_val, uint1_t inc)
{
  static uint8_t accum = 0;
  if(inc)
  {
    uint8_t accum = accum + inc_val;
  }
  return accum; 
}
*/
/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 100.0
typedef struct point_t
{
  uint8_t dims[3];
}point_t;
typedef struct point_2_t
{
  point_t a;
  point_t b;
}point_2_t;
point_2_t main()
{
  point_2_t rv = {0};
  return rv;
}
*/

/*
#include "uintN_t.h"
uint8_t bar_comb(uint8_t f, uint8_t x)
{
  return f + x;
}
uint8_t foo_clk_fsm(uint8_t x)
{
  static uint8_t accum = 0;
  accum += x;
  x = accum;
  while(x > 0)
  {
    x -= 1;
    __clk();
  }
  __clk();
  return accum;
}
uint8_t main(uint8_t x)
{
  // An FSM that uses __clk() and
  // takes multiple cycles
  uint8_t f1 = foo_clk_fsm(x); 
  // A function without __clk() that
  // is same cycle comb logic
  uint8_t b = bar_comb(f1, x);
  // Second instance is going back to same state
  uint8_t f2 = foo_clk_fsm(b);
  return f2;
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main_clk_fsm
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
main_OUTPUT_t main_wrapper(main_INPUT_t i)
{
  return main_FSM(i);
}
*/

/*
//#pragma MAIN_MHZ main_FSM 100.0
#pragma MAIN_MHZ tb 100.0
void tb()
{
  static uint8_t x;
  
  main_INPUT_t i;
  i.input_valid = 1;
  i.x = x;
  i.output_ready = 1;
  
  main_OUTPUT_t o = main_FSM(i);
  
  if(o.input_ready)
  {
    // Next input
    x += 1;
  }  
}
*/

/*
#include "uintN_t.h"

// Include Arty leds module
// with globally visible port/wire 'leds'
#include "examples/arty/src/leds/leds.c"

void main()
{
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  while (1) {
    // LEDs updated every clock
    // with the 4 most significant bits
    uint4_t led = uint28_27_24(counter);
    // Drive the 'leds' global wire
    WIRE_WRITE(uint4_t, leds, led) // leds = led;
    counter = counter + 1;
    __clk();
  }
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}
*/

/*
// Output 4b wired to LEDs
// Regular HDL style
uint4_t main()
{
  // a 28 bits unsigned integer register
  static uint28_t counter = 0;
  // LEDs updated every clock
  // with the 4 most significant bits
  uint4_t led = uint28_27_24(counter);
  counter = counter + 1;
  return led;
}
*/

/*
#include "uintN_t.h"
// Output 4b wired to LEDs
// Derived FSM style
uint4_t main()
{
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  while (1) {
    // LEDs updated every clock
    // with the 4 most significant bits
    uint4_t led = uint28_27_24(counter);
    counter = counter + 1;
    __out(led);
  }
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
uint4_t main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
  return o.return_output;
}
*/

/*
#include "uintN_t.h"

uint8_t worker_thread(uint8_t wait_cycles)
{
  // Wait some number of cycles then return
  while(wait_cycles > 0)
  {
    wait_cycles -= 1;
    __clk();
  }
  return wait_cycles;
}
// Including this header auto generates a derived
// finite state machine (in PipelineC)
#include "worker_thread_FSM.h"

// The top level 'main' instantiation
#pragma MAIN_MHZ main 400.0
#define NUM_THREADS 10
uint32_t main()
{
  static uint32_t cycle_counter;
  static uint1_t thread_stopped[NUM_THREADS];
  uint1_t rv = uint1_array_or10(thread_stopped);
  // N parallel instances of worker_thread FSM
  uint32_t i;
  for(i=0; i <NUM_THREADS; i+=1)
  {
    if(!thread_stopped[i])
    {
      worker_thread_INPUT_t inputs;
      inputs.wait_cycles = i;
      inputs.input_valid = 1;
      inputs.output_ready = 1;
      worker_thread_OUTPUT_t outputs = worker_thread_FSM(inputs);
      if(outputs.input_ready)
      {
        printf("Thread %d started in cycle %d\n", i, cycle_counter);
      }
      if(outputs.output_valid)
      {
        printf("Thread %d ended in cycle %d\n", i, cycle_counter);
        thread_stopped[i] = 1;
      }
    }
  }
  cycle_counter += 1;
  return rv;
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 400.0
uint32_t main(uint32_t x)
{
  uint32_t rv = {0};
  if(x > 0)
  {
    uint32_t temp;
    temp = temp + 1;
    rv = temp + 1;
  }
  else
  {
    uint32_t temp;
    temp = temp + 2;
    rv = temp + 2;
  }
  
  if(x > 1)
  {
    uint32_t temp = x + 3;
    rv = temp + 3;
  }
  else
  {
    uint32_t temp = x + 4;
    rv = temp + 4;
  }
  
  if(x > 2)
  {
    uint32_t temp = x + 5;
    rv = temp + 5;
  }
  else
  {
    uint32_t temp = x + 6;
    rv = temp + 6;
  }
  
  return rv;
}
*/

/*
// How to un-re-roll differently in time? Aetherling style
// N ratio faster and slower clocks
// Like double pumping dsps?
// 2x faster clock = as low as half resources(iter resource sharing) used iteratively 
//                   OR double throughput
// 2x slower clock = 2x resources 
//                   OR half throughput
uint8_t accum;
uint8_t main(uint1_t en)
{
  if(en) accum += 1;
  return accum;
}
*/

/*
uint8_t the_ram[128];
 main()
{
  
  // A variable latency globally visible memory access
  
  // Async style send and wait two func and fsm?
  
  // IMplemented as pipeline c func replacing this?  
  the_ram[i] = x
  // How to put a state machine into a user design?
    
}
*/


/*
// Tag main func as being compiled as C code and run on RISCV cpu
// What does interaction with PipelineC main func look like?
#pragma MAIN_MHZ cpu_main 100.0
#pragma MAIN_THREAD cpu_main // Run this as a CPU style thread
void cpu_main()
{
  // CPU style control loop
  while(1)
  {
    // Running around sequentially reading and writing memory
    // / Memory mapped registers to interact with hardware
    // The key being in hardware the registers are at 100MHz as specified
    mem[i] = foo
  
  }
  
}

#pragma MAIN_MHZ fpga_main 100.0
void fpga_main()
{
  // Every ten nanoseconds a value from
  // the RISCV CPU registers can be read/write ~like a variable somehow?
  
  
}
*/
