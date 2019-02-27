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
#include "examples/memcached/do_requests.c"

memcached_command_result_s main(memcached_packet_s incoming_request)
{	
	return do_requests(incoming_request);
}
*/
/*
#include "examples/memcached/send.c"

axis32_t main(memcached_command_result_s incoming_result)
{	
	return send(incoming_result);
}
*/
/*
#include "uintN_t.h"

typedef struct struct_t
{
	uint8_t x[4];
} struct_t;

uint8_t main(struct_t s)
{
	uint2_t i;
	uint8_t sum;
	sum = 0;
	for(i=3; i > 0; i = i - 1)
	{
		sum = sum + s.x[i-1];
	}
	return sum;
}
*/


/*
#include "examples/memcached/protocol.h"

entry_set_t main(entry_set_t set, key_pos_t existing_key_pos)
{
	// If in set then need to move to front of LRU
	if(existing_key_pos != -1)
	{
		entry_t write_back_data;
		write_back_data = set.entries[existing_key_pos];
		// Everything more recent moves back
		set_iter_t i;
		set_iter_t key_pos;
		key_pos = existing_key_pos; // Know existing_key_pos is >=0 
		for(i=SET_SIZE_MINUS1; i > 0; i = i - 1)
		{
			if(i <= key_pos)
			{
				set.entries[i] = set.entries[i-1];
			}
		}
		set.entries[0] = write_back_data;
	}
	return set;
}
*/
