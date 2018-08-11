#include "uintN_t.h"

/*
typedef struct x_struct_t
{
	uint64_t x[2][2];
} x_struct_t;


uint64_t main(x_struct_t x_structs[2])
{
	uint64_t sum;
	sum =       x_structs[0].x[0][0];
	sum = sum + x_structs[0].x[0][1];
	sum = sum + x_structs[0].x[1][0];
	sum = sum + x_structs[0].x[1][1];
	sum = sum + x_structs[1].x[0][0];
	sum = sum + x_structs[1].x[0][1];
	sum = sum + x_structs[1].x[1][0];
	sum = sum + x_structs[1].x[1][1];
	return sum;
}
*/

/*
BOOOO need code for parsing arbitrary deep chains of references
build original wire name recursively, or maybe loop? using children[] array?
Should kinda have already for struct ref?

a.x[0].b.y[0]
*/


uint64_t main(uint64_t x[2][2])
{
	uint64_t sum;
	sum =       x[0][0];
	sum = sum + x[0][1];
	sum = sum + x[1][0];
	sum = sum + x[1][1];
	return sum;
}
