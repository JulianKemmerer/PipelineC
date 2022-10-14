// Lowest latency, most resource usage
// Resource usage grows O(N^3)

#include "uintN_t.h"
#define N 2
#define float_array_sumN float_array_sum2
#define iter_t uint1_t

typedef struct an_array_t
{
	float a[N][N];
} an_array_t;


#pragma MAIN main
an_array_t main(float mat1[N][N], float mat2[N][N])
{
    an_array_t res;
    
    iter_t i;
    iter_t j;
    iter_t k;
    for (i = 0; i < N; i = i + 1) 
    { 
        for (j = 0; j < N; j = j + 1) 
        { 
            float res_k[N];
            for (k = 0; k < N; k = k + 1)
            {
                res_k[k] = mat1[i][k] * mat2[k][j]; 
			}
			res.a[i][j] =  float_array_sumN(res_k);
		} 
    }
    
    return res;
}
