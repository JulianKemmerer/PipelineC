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
//#include "uintN_t.h"
//#define PI_DIV_2 1.57079632679
float main(float theta)
{	
	return x % y;
}
*/

#include "uintN_t.h"
#include "intN_t.h"
//#include "math.h"
// 8x8 DCT
// https://www.geeksforgeeks.org/discrete-cosine-transform-algorithm-program/
#define DCT_PI 3.14159265359 // Scoo
#define DCT_M 5
#define DCT_N 5
#define dct_iter_t uint3_t // 0-7
#define DCT_ONE_DIV_SQRT_M 0.353553391
#define DCT_ONE_DIV_SQRT_N 353553391
#define DCT_SQRT2_DIV_SQRTM 0.5
#define DCT_SQRT2_DIV_SQRTN 0.5
#define dct_pixel_t uint8_t // 0-255
float main(float bias)
{ 
	float sum;
    sum = 0.0; 
	
    dct_iter_t i;
    dct_iter_t j;
    dct_iter_t k;
    dct_iter_t l;
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
            for (k = 0; k < DCT_M; k=k+1) { 
                for (l = 0; l < DCT_N; l=l+1) {        
                    sum = sum + (
							((float)((2 * k + 1) * i) * DCT_PI / (float)(2 * DCT_M)) *  
                            ((float)((2 * l + 1) * j) * DCT_PI / (float)(2 * DCT_N)) 
                           );
                } 
            }  
        } 
    }
    
    sum = sum + bias;
    
    return sum; 
}

/*
entry_set_t main(addr_t addr, entry_set_t wd, uint1_t we)
{
	return entry_sets_RAM_SP_RF_2(addr, wd, we);
}
*/
