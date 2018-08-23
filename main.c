#include "eth_32.c"
#include "ip_32.c"
#include "udp_32.c"

typedef struct the_array_t
{
	uint16_t a[3][3];
} the_array_t;

// Increment everything by z
the_array_t main(uint16_t x[3][3], uint16_t z)
{
	the_array_t rv;
	uint16_t y[3][3];

	uint3_t i;
	uint3_t j;
	
	for(i=0; i < 3; i = i+1)
	{
		for(j=0; j < 3; j = j+1)
		{
			y[i][j] = x[i][j] + z;
		}
	}
	
	rv.a = y; 
	
	return rv;
}
