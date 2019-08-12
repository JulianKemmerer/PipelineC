// Heys its math and more!
#include "uintN_t.h"
#include "intN_t.h"

//TODO fake some of math.h #define M_PI 

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

cordic_fixed32_t cordic_fixed32_n32(int32_t theta)//, int32_t *s, int32_t *c, int32_t n)
{
    int32_t cordic_ctab[CORDIC_NTAB];
    cordic_ctab[0] = 0x3243F6A8;
    cordic_ctab[1] = 0x1DAC6705;
    cordic_ctab[2] = 0x0FADBAFC;
    cordic_ctab[3] = 0x07F56EA6;
    cordic_ctab[4] = 0x03FEAB76;
    cordic_ctab[5] = 0x01FFD55B;
    cordic_ctab[6] = 0x00FFFAAA;
    cordic_ctab[7] = 0x007FFF55; 
    cordic_ctab[8] = 0x003FFFEA; 
    cordic_ctab[9] = 0x001FFFFD; 
    cordic_ctab[10] = 0x000FFFFF; 
    cordic_ctab[11] = 0x0007FFFF; 
    cordic_ctab[12] = 0x0003FFFF; 
	cordic_ctab[13] = 0x0001FFFF; 
	cordic_ctab[14] = 0x0000FFFF; 
	cordic_ctab[15] = 0x00007FFF; 
	cordic_ctab[16] = 0x00003FFF; 
	cordic_ctab[17] = 0x00001FFF; 
	cordic_ctab[18] = 0x00000FFF; 
	cordic_ctab[19] = 0x000007FF; 
	cordic_ctab[20] = 0x000003FF; 
	cordic_ctab[21] = 0x000001FF; 
	cordic_ctab[22] = 0x000000FF; 
	cordic_ctab[23] = 0x0000007F; 
	cordic_ctab[24] = 0x0000003F; 
	cordic_ctab[25] = 0x0000001F; 
	cordic_ctab[26] = 0x0000000F; 
	cordic_ctab[27] = 0x00000008; 
	cordic_ctab[28] = 0x00000004; 
	cordic_ctab[29] = 0x00000002; 
	cordic_ctab[30] = 0x00000001; 
	cordic_ctab[31] = 0x00000000;
  
  int32_t k;
  int32_t d;
  int32_t tx;
  int32_t ty;
  int32_t tz;
  int32_t x;
  x = CORDIC_1K;
  int32_t y;
  y = 0;
  int32_t z;
  z = theta;
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
	int32_t theta_fixed;
	theta_fixed = theta*CORDIC_MUL;
	
	// Do fixed math
	cordic_fixed32_t fixed_result;
	fixed_result = cordic_fixed32_n32(theta_fixed);

	// Convert fixed to float
	cordic_float_t rv;
	rv.s = ((float)fixed_result.s)/CORDIC_MUL;
	rv.c = ((float)fixed_result.c)/CORDIC_MUL;
	return rv;
}

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

// Placeholder for compile
float sqrt(float x)
{
	return 0.0;
}

// 8x8 DCT
// https://www.geeksforgeeks.org/discrete-cosine-transform-algorithm-program/
#define DCT_PI 3.14159265359
#define DCT_M 8
#define DCT_N 8
#define dct_iter_t uint3_t // 0-7
#define dct_pixel_t uint8_t // 0-255
typedef struct dct_t
{
	float matrix[DCT_M][DCT_N];
} dct_t;
  
// Function to find discrete cosine transform and return it 
dct_t dctTransform(dct_pixel_t matrix[DCT_M][DCT_N]) 
{ 
    dct_iter_t i;
    dct_iter_t j;
    dct_iter_t k;
    dct_iter_t l;
  
    // dct will store the discrete cosine transform 
    dct_t dct;
  
    float ci;
    float cj;
    float dct1;
    float sum; 
  
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
  
            // ci and cj depends on frequency as well as 
            // number of row and columns of specified matrix 
            if (i == 0) 
                ci = 1.0 / sqrt(DCT_M); 
            else
                ci = sqrt(2) / sqrt(DCT_M);
            if (j == 0) 
                cj = 1.0 / sqrt(DCT_N);
            else
                cj = sqrt(2) / sqrt(DCT_N); 
  
            // sum will temporarily store the sum of  
            // cosine signals 
            sum = 0.0; 
            for (k = 0; k < DCT_M; k=k+1) { 
                for (l = 0; l < DCT_N; l=l+1) { 
                    dct1 = (float)matrix[k][l] *  // Float * constant       
                             ( cos((float)((2 * k + 1) * i) * DCT_PI / (float)(2 * DCT_M)) *  
                               cos((float)((2 * l + 1) * j) * DCT_PI / (float)(2 * DCT_N))
                             );
                    sum = sum + dct1;
                }
            } 
            dct.matrix[i][j] = (ci * cj) * sum;
        } 
    }
    
    return dct; 
}


// Cosine multiplier lookup table for unrolled version of above algorithm 
// (as opposed to actually doing cosine operation)
float dctCosLookup(dct_iter_t i_in, dct_iter_t j_in, dct_iter_t k_in, dct_iter_t l_in)
{
	// table evaluates to a constant
    float table[DCT_M][DCT_N][DCT_M][DCT_N];
    dct_iter_t i;
    dct_iter_t j;
    dct_iter_t k;
    dct_iter_t l;
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
			 for (k = 0; k < DCT_M; k=k+1) { 
                for (l = 0; l < DCT_N; l=l+1) { 
                    table[i][j][k][l] = ( cos((float)((2 * k + 1) * i) * DCT_PI / (float)(2 * DCT_M)) *  
										  cos((float)((2 * l + 1) * j) * DCT_PI / (float)(2 * DCT_N))
										);
                }
            } 
        } 
    }
    
    // Lookup into that table
    return table[i_in][j_in][k_in][l_in]; 
}

// (ci * cj) lookup table for unrolled version of above algorithm 
float dctConstLookup(dct_iter_t i_in, dct_iter_t j_in)
{
	// table evaluates to a constant
    float table[DCT_M][DCT_N];
    dct_iter_t i;
    dct_iter_t j;
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
			float ci;
			float cj;
			if (i == 0) 
                ci = 1.0 / sqrt(DCT_M); 
            else
                ci = sqrt(2) / sqrt(DCT_M);
            if (j == 0) 
                cj = 1.0 / sqrt(DCT_N);
            else
                cj = sqrt(2) / sqrt(DCT_N);
			table[i][j] = (ci*cj);
        } 
    }
    
    // Lookup into that table
    return table[i_in][j_in];
}


// This is the unrolled version of the above algorithm
// Each PipelineC iteration of dctTransformUnrolled 
// increments i,j,k,l to do the same O(n^4) serially over time
typedef struct dct_done_t
{
	float matrix[DCT_M][DCT_N];
	uint1_t done;
} dct_done_t;
// Lookup table in BRAM takes N clocks
//		(deterministic N always =2 in this case)
// So keep track of doing lookup v.s. doing calculation
typedef enum dct_state_t {
	IDLE,
	LOOKUP,
	CALC
} dct_state_t;
// Instead of local variables holding the iterators and result
// they are now volatile global variables
// Volatiles can only read+write when valid,
volatile uint1_t dct_volatiles_valid;
volatile dct_state_t dct_state;
volatile dct_iter_t dct_i;
volatile dct_iter_t dct_j;
volatile dct_iter_t dct_k;
volatile dct_iter_t dct_l;
// sum will temporarily store the sum of cosine signals 
volatile float dct_sum;
// dct_result will store the discrete cosine transform 
volatile dct_done_t dct_result;
// dctTransformUnrolled gets new inputs each clock cycle / "is called repeatedly"
// Supply a matrix and start=1 to get going
// Assume that we keep getting the same 'matrix' between start and done
dct_done_t dctTransformUnrolled(dct_pixel_t matrix[DCT_M][DCT_N], uint1_t start)
{
	// Start bit validates the volatiles 
	// and gets the calculation started
	if(start)
	{
		dct_volatiles_valid = 1;
		// Reset iters
		dct_i = 0;
		dct_j = 0;
		dct_k = 0;
		dct_l = 0;
		// Lookup constants before calculating
		dct_state = LOOKUP;
	}
	
	// This part repeats as i,j,k,l iterate
	
	// Do lookup
	if((dct_state == LOOKUP) & dct_volatiles_valid)
	{
		// Input i,j,k,l
		// N clocks later get back constants
		
		
		
		
	}
	
	
	// Assume not yet
	dct_result.done = 0;
	
	// N clock delayed memory
	dct_lookup_t dct_lookup;
	dct_lookup = dctLookupTable(
	
	// Do the calculation using these delayed iterator values
	scoo
	
	
	// Do calculation
	if(dct_volatiles_valid)
	{		
		// Which iterators should increment/reset this iteration?
		// l
		uint1_t increment_l;
		increment_l = 1; // Inner most loop - always
		uint1_t reset_l;
		reset_l = (dct_l==(DCT_N-1)) & increment_l;
		// k
		uint1_t increment_k;
		increment_k = reset_l;
		uint1_t reset_k;
		reset_k = (dct_k==(DCT_M-1)) & increment_k;
		// j
		uint1_t increment_j;
		increment_j = reset_k;
		uint1_t reset_j;
		reset_j = (dct_j==(DCT_N-1)) & increment_j;
		// i
		uint1_t increment_i;
		increment_i = reset_j;
		uint1_t reset_i;
		reset_i = (dct_i==(DCT_M-1)) & increment_i;
				
		// ~~~ The primary calculation ~~~:
		// 1) Float * constant from lookup table  
		float dct1;
		dct1 = (float)matrix[dct_k][dct_l] * dctCosLookup(dct_i, dct_j, dct_k, dct_l);
		dct_sum = dct_sum + dct1;
		// 2) constant * Float and assign into the matrix
		dct_result.matrix[dct_i][dct_j] = dctConstLookup(dct_i, dct_j) * dct_sum;
		
		// Sum accumulates during the k and l loops
		// So reset when they are rolling over
		if(reset_k & reset_l)
		{
			dct_sum = 0.0;
		}
		
		// Increment iterators as needed
		if(increment_i)
		{
			dct_i = dct_i + 1;
		}
		if(increment_j)
		{
			dct_j = dct_j + 1;
		}
		if(increment_k)
		{
			dct_k = dct_k + 1;
		}
		if(increment_l)
		{
			dct_l = dct_l + 1;
		}		
		
		// Reset iterators as needed
		if(reset_i)
		{
			dct_i = 0;
		}
		if(reset_j)
		{
			dct_j = 0;
		}
		if(reset_k)
		{
			dct_k = 0;
		}
		if(reset_l)
		{
			dct_l = 0;
		}	
		
		// Signal done as all iterators roll over
		dct_result.done = reset_i & reset_j & reset_k & reset_l;
	}
	
	return dct_result;
}

