// High latency, low resource usage matrix multiply
#include "uintN_t.h"

// Array dimension
#define N 2
#define N_MINUS_1 1 // To not need an extra bit in iter_t
#define iter_t uint1_t

// Type holding result array
typedef struct result_array_t
{
	float a[N][N];
	uint1_t done;
} result_array_t;

// Indicates if volatile globals are valid
volatile uint1_t volatiles_valid;
// Volatile globals
// i,j,k iterators
volatile iter_t i;
volatile iter_t j;
volatile iter_t k;
// Result array
volatile result_array_t result;

// An unrolled version of the i,j,k matrix multiply nested loops
/*
for (i = 0; i < N; i++) 
{ 
	for (j = 0; j < N; j++) 
	{  
		for (k = 0; k < N; k++) 
			res[i][j] += mat1[i][k] * mat2[k][j]; 
	} 
}
*/
// Signal the start of the operation with 'start'
// return value '.done' signals the completion of the operation
// Both input matrices are assumed to have data from start->done
// ~N^3 iterations after 'start' the result 'done'
result_array_t main(
	 uint1_t start,
	 float mat1[N][N], float mat2[N][N])
{       
    // Reset everything if this is the start
    if(start)
    {
		// Validate the volatiles as being reset to 0
		volatiles_valid = 1;
		// Clear the result array
		i = 0;
		j = 0;
		k = 0;
		for (i = 0; i < N; i = i + 1) 
		{ 
			for (j = 0; j < N; j = j + 1) 
			{ 
				result.a[i][j] = 0;
			}
		}
	}
	
	// Default return accumulated result
	result_array_t rv;
	rv = result;

    // Accumulate into volatile global result
    // (only if the volatile globals have valid data)
    if(volatiles_valid)
    {		
		// Do the math for this iteration
		// Two separate floating point operatations
		// Multiply
		float product;
		product = mat1[i][k] * mat2[k][j];
		// Accumulate
		result.a[i][j] = result.a[i][j] + product;
		
		// This is like unrolling to a 
		// single iteration of the inner most loop
		
		// i
		if(i == N_MINUS_1)
		{
			// End of i loop, reset
			i = 0;
			// Multiply is done now
			rv = result;
			rv.done = 1;
			// Clear done flag to start over
			result.done = 0;
			// Invalidate state, wait for start again
			volatiles_valid = 0;
		}
		// j
		if(j == N_MINUS_1)
		{
			// End of j loop, reset
			j = 0;
			// Increment i
			i = i + 1;
		}
		// k
		if(k == N_MINUS_1)
		{
			// End of k loop, reset
			k = 0;
			// Increment j
			j = j + 1;
		}
		else
		{
			// Increment k
			k = k + 1;
		}			
	}

    return result;
}
