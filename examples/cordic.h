#include "uintN_t.h"
#include "intN_t.h"

// http://www.dcs.gla.ac.uk/~jhw/cordic/     **Slightly modified
//Cordic in 32 bit signed fixed point math
//Function is valid for arguments in range -pi/2 -- pi/2
//for values pi/2--pi: value = half_pi-(theta-half_pi) and similarly for values -pi---pi/2
//
// 1.0 = 1073741824
// 1/k = 0.6072529350088812561694
// pi = 3.1415926535897932384626
//Constants
#define CORDIC_1K 0x26DD3B6A
#define CORDIC_MUL 1073741824.000000
#define CORDIC_NTAB 32
#define CORDIC_N_ITER 32

// Cordic limited to int32 fixed point -pi/2 -- pi/2
typedef struct cordic_fixed32_t
{
	int32_t s;
	int32_t c;
} cordic_fixed32_t;

int32_t cordic_ctab[CORDIC_NTAB] = {0x3243F6A8, 0x1DAC6705, 0x0FADBAFC, 0x07F56EA6, 0x03FEAB76, 0x01FFD55B, 
0x00FFFAAA, 0x007FFF55, 0x003FFFEA, 0x001FFFFD, 0x000FFFFF, 0x0007FFFF, 0x0003FFFF, 
0x0001FFFF, 0x0000FFFF, 0x00007FFF, 0x00003FFF, 0x00001FFF, 0x00000FFF, 0x000007FF, 
0x000003FF, 0x000001FF, 0x000000FF, 0x0000007F, 0x0000003F, 0x0000001F, 0x0000000F, 
0x00000008, 0x00000004, 0x00000002, 0x00000001, 0x00000000};

cordic_fixed32_t cordic_fixed32_n32(int32_t theta)//, int32_t *s, int32_t *c, int32_t n)
{
  int32_t k, d, tx, ty, tz;
  int32_t x = CORDIC_1K;
  int32_t y = 0;
  int32_t z = theta;
  for (k=0; k<CORDIC_N_ITER; k=k+1)
  {
    d = z>>31;
    //get sign. for other architectures, you might want to use the more portable version
    //d = z>=0 ? 0 : -1;
    tx = x - (((y>>k) ^ d) - d);
    ty = y + (((x>>k) ^ d) - d);
    tz = z - ((cordic_ctab[k] ^ d) - d);
    x = tx; y = ty; z = tz;
  }  
  
  cordic_fixed32_t rv;
  rv.c = x;
  rv.s = y;
  return rv;
}


// Cordic limited to float -pi/2 -- pi/2 per fixed point cordic implementation
typedef struct cordic_float_t
{
	float s;
	float c;
} cordic_float_t;
cordic_float_t cordic_float_fixed32_n32(float theta)
{
	// Convert float to fixed
	int32_t theta_fixed = theta*CORDIC_MUL;
	
	// Do fixed math
	cordic_fixed32_t fixed_result = cordic_fixed32_n32(theta_fixed);

	// Convert fixed to float
	cordic_float_t rv;
	rv.s = ((float)fixed_result.s)*(1.0/CORDIC_MUL);
	rv.c = ((float)fixed_result.c)*(1.0/CORDIC_MUL);
	return rv;
}

//#pragma MAIN_MHZ cordic_fixed32_n32 166.0
//#pragma MAIN_MHZ cordic_float_fixed32_n32 166.0
/*#pragma MAIN tb
void tb()
{
  float rads = 1.0471975512; //~pi/3;
  cordic_float_t result = cordic_float_fixed32_n32(rads);
  printf("sin(%f)=%f, cos(%f)=%f\n", rads, result.s, rads, result.c);
}*/

/*
// Cordic float -inf - inf
// TODO: Move modulo and adjustment for fixed point stuff into fixed point math
//	via modulo 2PI then adjsut into range -pi/2 -- pi/2
//  	per fixed point cordic implementation
#define CORDIC_PI_X_2 6.28318530718
#define CORDIC_PI 3.14159265359
#define CORDIC_PI_DIV_2 1.57079632679
#define CORDIC_3PI_DIV2 4.71238898038
cordic_float_t cordic_float_mod_fixed32_n32(float theta)
{
	// Only need to know value mod 2pi
	float theta_neg2pi_2pi;
	theta_neg2pi_2pi = theta % CORDIC_PI_X_2;
	
	// I'm near certain this could be optimized
	// An add/sub and/or a else-if case could be removed being crafty with radians
	
	// Convert -2pi -> 2pi range into 0->2pi
	// Only need to check quadrants in terms of their positive values
	float theta_0_2pi;
	theta_0_2pi = theta_neg2pi_2pi;
	if(theta < 0.0)
	{
		// theta_neg2pi_2pi known negative  -2pi -> 0
		theta_0_2pi = CORDIC_PI_X_2  + theta_neg2pi_2pi;
	}
	
	// Adjust to -pi/2 -- pi/2 for fixed point
	float fixed_range_theta;
	fixed_range_theta = theta_0_2pi;
	// Might need to negate x/cosine
	uint1_t neg_x;
	neg_x = 0;
	
	// QI
	if( (theta_0_2pi >= 0.0) & (theta_0_2pi <= CORDIC_PI_DIV_2) )
	{
		// Oh yay, use as is
		fixed_range_theta = theta_0_2pi;
	}
	// Q2
	else if( (theta_0_2pi >= CORDIC_PI_DIV_2) & (theta_0_2pi <= CORDIC_PI) )
	{
		// Minus pi/2 to flip into QI, negate x
		fixed_range_theta = theta_0_2pi - CORDIC_PI_DIV_2;
		neg_x = 1;
	}
	// Q3
	else if( (theta_0_2pi >= CORDIC_PI) & (theta_0_2pi <= CORDIC_3PI_DIV2) )
	{
		// Add pi/2 to flip into Q4, negate x
		// But then is too far positive so subtract 2pi for negative equivalent
		// pi/2 - 2pi = - 3pi/2
		fixed_range_theta = theta_0_2pi - CORDIC_3PI_DIV2;
		neg_x = 1;
	}
	// Q4
	else
	{
		// Too far positive
		// Just use negative equivalent that is <= -pi/2
		fixed_range_theta = theta_0_2pi - CORDIC_PI_X_2;
	}
	
	// Do operation in the fixed range
	cordic_float_t cordic_result;
	cordic_result = cordic_float_fixed32_n32(fixed_range_theta);
	
	// Adjust result as needed
	cordic_float_t adjusted_result;
	adjusted_result = cordic_result;
	if(neg_x)
	{
		adjusted_result.c = adjusted_result.c * -1.0;
	}
	
	return adjusted_result;	
}

// Cosine implemented with 32bit fixed point
// TODO: Verify this works (and all of cordic implementation)
float cos(float theta)
{
	cordic_float_t cordic_result;
	cordic_result = cordic_float_mod_fixed32_n32(theta);
	return cordic_result.c;
}

// Sine implemented with 32bit fixed point
// TODO: Verify this works (and all of cordic implementation)
float sin(float theta)
{
	cordic_float_t cordic_result;
	cordic_result = cordic_float_mod_fixed32_n32(theta);
	return cordic_result.s;
}
*/
