
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


////////////////////////////// CHIPSCOPE THE STATE WTF


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
#include "eth_32.c"
#include "ip_32.c"
#include "udp_32.c"
*/

/*
axis32_t main(axis32_t mac_axis_rx)
{
	// Receive the request packet
	memcached_packet_s request;
	request = receive(mac_axis_rx);
		
	// Form a fake command result
	hash_map_result_t hash_map_result;
	hash_map_result.read_data.key = request.data.key;
	hash_map_result.read_data.key_len = request.data.header.key_len;
	hash_map_result.read_data.value = request.data.value;
	hash_map_result.read_data.value_len = request.data.value_len;
	hash_map_result.read_valid = 1;
	memcached_command_result_s result;
	result.data.request = request.data;
	result.data.request.header.opcode = GET;
	result.data.hash_map_result = hash_map_result;
	result.valid = request.valid;
		
	// Send a response packet
	return send(result);
}*/

/*
hash_map_result_s main(hash_map_request_s incoming_request, uint1_t read_result)
{
	return do_hash_map(incoming_request, read_result);
}
*/
/*
#include "uintN_t.h"

volatile uint1_t valid = 1;
volatile uint8_t accum;
uint8_t main(uint8_t x, uint8_t y)
{	
	if(valid)
	{
		uint8_t sum;
		sum = x + y;
		accum = accum + sum;
	}
	
	return accum;
}
*/
