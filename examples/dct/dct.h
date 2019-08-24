#include "../../math.h"
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
