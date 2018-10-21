#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "bit_math.h"

// Float adds std_logic_vector in VHDL
// Adds are complicated
float main(float left, float right)
{
	// Get exponent for left and right
	uint8_t left_exponent;
	left_exponent = float_30_23(left);
	uint8_t right_exponent;
	right_exponent = float_30_23(right);
		
	float x;
	float y;
	// Step 1: Copy inputs so that left's exponent >= than right's.
	// ?????????MAYBE TODO: 
	//		Is this only needed for shift operation that takes unsigned only?
	// 		ALLOW SHIFT BY NEGATIVE?????
	//		OR NO since that looses upper MSBs of mantissa which not acceptable? IDK too many drinks
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
	uint23_t x_mantissa;	
	x_mantissa = float_22_0(x);
	uint8_t x_exponent;
	x_exponent = float_30_23(x);
	uint1_t x_sign;
	x_sign = float_31_31(x);
	// Y
	uint23_t y_mantissa;
	y_mantissa = float_22_0(y);
	uint8_t y_exponent;
	y_exponent = float_30_23(y);
	uint1_t y_sign;
	y_sign = float_31_31(y);
	
	// Mantissa needs +3b wider
	// 	[sign][overflow][hidden][23 bit mantissa]
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
	uint24_t x_mantissa_w_hidden_bit; 
	x_mantissa_w_hidden_bit = uint1_uint23(x_hidden_bit, x_mantissa);
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
	uint24_t y_mantissa_w_hidden_bit; 
	y_mantissa_w_hidden_bit = uint1_uint23(y_hidden_bit, y_mantissa);

	// Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
	// Already swapped left/right based on exponent
	// diff will be >= 0
	uint8_t diff;
	diff = x_exponent - y_exponent;
	// Shift y by diff (bit manip pipelined function)
	uint24_t y_mantissa_w_hidden_bit_unnormalized;
	y_mantissa_w_hidden_bit_unnormalized = y_mantissa_w_hidden_bit >> diff;
	
	// Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
	// STEP 2.B moved here
	// Make wider for twos comp/sign
	int25_t x_mantissa_w_hidden_bit_sign_adj;
	int25_t y_mantissa_w_hidden_bit_sign_adj;
	if(x_sign) //if(x_sign == 1)
	{
		x_mantissa_w_hidden_bit_sign_adj = uint24_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int25t
	}
	else
	{
		x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
	}
	if(y_sign) // if(y_sign == 1)
	{
		y_mantissa_w_hidden_bit_sign_adj = uint24_negate(y_mantissa_w_hidden_bit_unnormalized);
	}
	else
	{
		y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit_unnormalized;
	}
	
	// Step 5: Compute sum 
	int26_t sum_mantissa;
	sum_mantissa = x_mantissa_w_hidden_bit_sign_adj + y_mantissa_w_hidden_bit_sign_adj;

	// Step 6: Save sign flag and take absolute value of sum.
	uint1_t sum_sign;
	sum_sign = int26_25_25(sum_mantissa);
	uint26_t sum_mantissa_unsigned;
	sum_mantissa_unsigned = int26_abs(sum_mantissa);

	// Step 7: Normalize sum and exponent. (Three cases.)
	uint1_t sum_overflow;
	sum_overflow = uint26_24_24(sum_mantissa_unsigned);
	uint8_t sum_exponent_normalized;
	uint23_t sum_mantissa_unsigned_normalized;
	if (sum_overflow) //if ( sum_overflow == 1 )
	{
	   // Case 1: Sum overflow.
	   //         Right shift significand by 1 and increment exponent.
	   sum_exponent_normalized = x_exponent + 1;
	   sum_mantissa_unsigned_normalized = uint26_23_1(sum_mantissa_unsigned);
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
	   uint24_t sum_mantissa_unsigned_narrow;
	   sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
	   uint5_t leading_zeros; // width = ceil(log2(len(sumsig)))
	   leading_zeros = count0s_uint24(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
	   // NOT CHECKING xexp < adj
	   // Case 2b: Adjust significand and exponent.
	   sum_exponent_normalized = x_exponent - leading_zeros;
	   sum_mantissa_unsigned_normalized = sum_mantissa_unsigned_narrow << leading_zeros;
    }
	
	// Declare the output portions
	uint23_t z_mantissa;
	uint8_t z_exponent;
	uint1_t z_sign;
	z_sign = sum_sign;
	z_exponent = sum_exponent_normalized;
	z_mantissa = sum_mantissa_unsigned_normalized;
	// Assemble output	
	return float_uint1_uint8_uint23(z_sign, z_exponent, z_mantissa);
}


/*
int25_t main(int25_t x_mantissa_w_hidden_bit_sign_adj,
	int25_t y_mantissa_w_hidden_bit_sign_adj)
{
	int25_t sum_mantissa;
	sum_mantissa = x_mantissa_w_hidden_bit_sign_adj + y_mantissa_w_hidden_bit_sign_adj;
	
	return sum_mantissa;
}*/
