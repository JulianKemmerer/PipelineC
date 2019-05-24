
#include "axis.h"
#include "examples/memcached/receive.c"
#include "examples/memcached/do_requests.c"
#include "examples/memcached/send.c"


// Memcached in PipelineC
/*
Very similar to Xilinx pdf:
 receive(p);
 k = parse(p);
 a = hashKey(k);
 v = readValue(a);
 new_p = format(v);
 send(new_p);
*/

// Input is ethernet data from the Xilinx TEMAC
// Output is ethernet data back to the Xilinx TEMAC
axis32_t main(axis32_t mac_axis_rx)
{
	// Receive the request packet
	memcached_packet_s request;
	request = receive(mac_axis_rx);
		
	// Do requests
	// (put in new request, maybe receive some past request's result)
	memcached_command_result_s result;
	result = do_requests(request);
	
	// Send a response packet
	return send(result);
}

/*
#include "uintN_t.h"


uint16_t main(uint16_t x, uint16_t y)
{	
	uint16_t z;
	z = x * y; //Long branch
	
	// Short branch
	uint16_t a;
	a = x + y;
	uint16_t b;
	b = x - y;
	uint16_t c;
	c = a + b;
	uint16_t d;
	d = a - b;
	
	// join up
	uint16_t e;
	e = z | d;
	
	return e;
	
}
*/

/*
uint32_t main(uint8_t k[KEY_MAX_LEN], key_len_t length)
{
	return hash(k, length);
}
*/
