
// Hacked up version of https://www.geeksforgeeks.org/c-program-multiply-two-matrices/

#include "uintN_t.h"


#define N 2
#define float_array_sumN float_array_sum2
#define iter_t uint1_t

typedef struct an_array_t
{
	float a[N][N];
} an_array_t;


an_array_t main(float mat1[N][N], float mat2[N][N])
{
	float res[N][N];
    iter_t i;
    iter_t j;
    iter_t k;
    
    float k_res[N];
    for (i = 0; i < N; i = i + 1)
    {
        for (j = 0; j < N; j = j + 1)
        {
            for (k = 0; k < N; k = k + 1)
            {
                 k_res[k] = mat1[i][k]*mat2[k][j];
			}
			// Accumulate k_res into res[i][j]
			res[i][j] = float_array_sumN(k_res);
        }
    }
    
    an_array_t rv;
    rv.a = res;
    return rv;
}


