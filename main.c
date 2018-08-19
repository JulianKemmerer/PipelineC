#include "uintN_t.h"

uint64_t main(uint64_t x, uint64_t y)
{
	uint64_t rv;
	if(x <= y)
	{
		rv = x;
	}
	else
	{
		rv = y;
	}
	
	return rv;
}

// Do hacky for loop unroll via unrolling C code text?
// As opposed to unrolling in C_TO_LOGIC

