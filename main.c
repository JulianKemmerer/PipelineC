
#include "examples/memcached/hash.c"

hash_map_result_s main(hash_map_request_s incoming_request, uint1_t read_result)
{	
	return do_hash_map(incoming_request,read_result);
}

/*
#include "uintN_t.h"

typedef struct struct_t
{
	uint8_t x;
} struct_t;

uint2_t main(struct_t s)
{
	uint2_t rv;
	rv = s.x;
	return rv;
}
*/
