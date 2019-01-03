/*
#include "uintN_t.h"


#define int_t uint8_t

int_t add(int_t x, int_t y)
{
		return x + y;
}

int_t mult(int_t x, int_t y)
{
		return x * y;
}


int_t main(uint1_t sel, int_t x, int_t y)
{
	int_t rv;
	if(sel)
	{
		rv = add(x,y);
	}
	else
	{
		rv = mult(x,y);
	}
	return rv;
}
*/

/*
float main(float x, float y)
{
	return x + y;
}
*/


#include "uintN_t.h"

#define elem_t uint8_t
#define DEPTH 128
#define addr_t uint7_t

elem_t ram[DEPTH];
elem_t main(addr_t addr, elem_t wd, uint1_t we)
{
	// One less place to change things if RAM specifier is in func name only?
	// How hard would it be to change? Alot of code would be the same
	// Justify justify 
	return ram_RAM_SP_RF(addr, wd, we);
}
