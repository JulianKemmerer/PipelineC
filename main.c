
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


/*
float main(float x, float y)
{
	return x + y;
}
*/
