
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


uint128_t main(uint128_t x, uint128_t y)
{	
	return x * y;
}
*/

/*
axis32_t main(ip32_frame_t ip, uint16_t checksum)
{
	return ip_32_tx_globals(ip, checksum);
}
*/
