#include "uintN_t.h"

typedef enum an_enum_t 
{
	ZERO,
	ONE,
	TWO,
} an_enum_t;

typedef struct a_struct_t
{
	uint8_t data;
	uint1_t valid;
} a_struct_t;

uint8_t a_global = 1;

uint8_t main(uint8_t x)
{
	a_global = a_global + x;
		
	return a_global;
}
