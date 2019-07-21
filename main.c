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
//#define PI_DIV_2 1.57079632679
float main(float theta)
{	
	uint8_t i;
	i = 0;
	float rv;
	if(i==0)
	{
		rv = 1.57079632679;
	}
	else
	{
		rv = 0.0;
	}
	return rv;
}
*/


#include "math.h"
dct_t main(dct_pixel_t matrix[DCT_M][DCT_N])
{ 
	return dctTransform(matrix);
}

/*
entry_set_t main(addr_t addr, entry_set_t wd, uint1_t we)
{
	return entry_sets_RAM_SP_RF_2(addr, wd, we);
}
*/
