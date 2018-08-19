#include "uintN_t.h"

// No generic sizes for now... :(
// Woah wtf, AXIS spec is little endian because of ARM or somthing?

typedef struct axis32_t
{
	uint32_t data;
	uint1_t valid;
	uint1_t last;
	uint4_t keep;
} axis32_t;

typedef struct axis16_t
{
	uint16_t data;
	uint1_t valid;
	uint1_t last;
	uint2_t keep;
} axis16_t;

uint2_t axis16_keep_bytes(uint2_t keep)
{
	uint2_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(keep == 1) // 01
	{
		rv = 1;
	}
	else if(keep == 3) // 11
	{
		rv = 2;
	}
	return rv;
}

uint3_t axis32_keep_bytes(uint4_t keep)
{
	uint3_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(keep == 1) // 0001
	{
		rv = 1;
	}
	else if(keep == 3) // 0011
	{
		rv = 2;
	}
	else if(keep == 7) // 0111
	{
		rv = 3;
	}
	else if(keep == 15) // 1111
	{
		rv = 4;
	}
	return rv;
}


uint2_t axis16_bytes_keep(uint2_t num_bytes)
{
	uint2_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(num_bytes == 1)
	{
		rv = 1; // 01
	}
	else if(num_bytes == 2)
	{
		rv = 3; // 11
	}
	return rv;	
}

uint4_t axis32_bytes_keep(uint3_t num_bytes)
{
	uint4_t rv;
	// Default invalid keep / zero
	rv = 0;
	if(num_bytes == 1)
	{
		rv = 1; // 0001
	}
	else if(num_bytes == 2)
	{
		rv = 3; // 0011
	}
	else if(num_bytes == 3)
	{
		rv = 7; // 0111
	}
	else if(num_bytes == 4)
	{
		rv = 15; // 1111
	}
	return rv;	
}

