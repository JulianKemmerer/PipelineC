/*
#include "axis.h"
#include "examples/memcached/receive.c"
#include "examples/memcached/do_requests.c"
#include "examples/memcached/send.c"
*/

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
/*
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
*/
/*
#include "uintN_t.h"
#define CORDIC_MUL 1073741824.000000
float main(int32_t x)
{	
	return x;
}
*/

#include "math.h"
cordic_float_t main(float theta)
{	
	return cordic_float_n32(theta);
}

/*
entry_set_t main(addr_t addr, entry_set_t wd, uint1_t we)
{
	return entry_sets_RAM_SP_RF_2(addr, wd, we);
}
*/
