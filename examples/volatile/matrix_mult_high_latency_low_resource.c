// High latency, low resource usage matrix multiply
#include "uintN_t.h"

// Matrix dimension
#define N 2
#define N_MINUS_1 1 // To not need an extra bit in iter_t
#define iter_t uint1_t

// Type holding result matrix
typedef struct result_matrix_t
{
	float mat[N][N];
	uint1_t done;
} result_matrix_t;

// WARNING: volatile variables are highly experimental
// Indicates if volatile globals are valid
volatile uint1_t volatiles_valid;
// Volatile globals
// i,j,k iterators
volatile iter_t i;
volatile iter_t j;
volatile iter_t k;
// Result matrix
volatile float mat[N][N];

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
#pragma MAIN main
result_matrix_t main(
	 uint1_t start,
	 float mat1[N][N], float mat2[N][N])
{       
	// Reset everything if this is the start
	if(start)
	{
		// Validate the volatiles as being reset to 0
		volatiles_valid = 1;
		// Clear the matrix and iterators
		i = 0;
		j = 0;
		k = 0;
		for (i = 0; i < N; i = i + 1) 
		{ 
			for (j = 0; j < N; j = j + 1) 
			{ 
				mat[i][j] = 0;
			}
		}
	}
	
	// Default return accumulated result and not done yet
	result_matrix_t rv;
	rv.mat = mat;
	rv.done = 0;

	// Accumulate into volatile global mat
	// (only if the volatile globals have valid data)
	if(volatiles_valid)
	{		
		// This is like unrolling to a 
		// single iteration of the inner most loop
		
		// Do the math for this iteration
		// Two separate floating point operatations
		// Multiply
		float product;
		product = mat1[i][k] * mat2[k][j];
		// Accumulate
		mat[i][j] = mat[i][j] + product;

		// Done?
		if(
			(i == N_MINUS_1) &
			(j == N_MINUS_1) &
			(k == N_MINUS_1)
		)
		{
			// Multiply is done now
			rv.mat = mat;
			rv.done = 1;
			// Invalidate state, wait for start again
			volatiles_valid = 0;
		}
		
		// Increment iterators unless going back to start
		// Increment k every time
		// k
		if(k == N_MINUS_1)
		{
			// End of k loop, reset
			k = 0;
		}
		else
		{
			// Increment k
			k = k + 1;
		}
		
		// j
		// Increment j when k is done
		if(k == 0) // Was N-1
		{
			if(j == N_MINUS_1) 
			{
				// End of j loop, reset
				j = 0;
			}
			else
			{
				// Increment j
				j = j + 1;
			}
		}
		
		// i
		// Increment i when j and k are done
		if(
			(j == 0) & // Was N-1
			(k == 0) // Was N-1
		)
		{
			if (i == N_MINUS_1)
			{
				// End of i loop, reset
				i = 0;
			}
			else
			{
				// Increment i
				i = i + 1;
			}
		}		
			
	}

    return rv;
}
