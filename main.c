
#include "examples/memcached/receive.c"

memcached_packet_s main(axis32_t mac_axis_rx)
{
	return receive(mac_axis_rx);
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
