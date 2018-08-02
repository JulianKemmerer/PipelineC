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
