// Heys its math and more!
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


// Cordic limited to float -pi/2 -- pi/2 per cordic implementation
typedef struct cordic_float_t
{
	float s;
	float c;
} cordic_float_t;
cordic_float_t cordic_float_n32(float theta)
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

// TODO implement cordic with modulo pi 


// Cosine implemented with 32bit fixed point
//float cos(float x)
//{
//}
