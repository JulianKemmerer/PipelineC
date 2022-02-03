#pragma once
#include "uintN_t.h"
#include "bit_manip.h"
#include "axis.h"

typedef struct ip_header_t
{
	uint4_t ver;
	uint4_t ihl;
	uint6_t dscp;
	uint2_t ecn;
	uint16_t total_length;
	uint16_t iden;
	uint3_t flags;
	uint13_t frag;
	uint8_t ttl;
	uint8_t protocol;
	uint16_t checksum;
	uint32_t src_ip;
	uint32_t dst_ip;
} ip_header_t;

typedef struct ip32_frame_t
{
	ip_header_t header;
	axis32_t payload;
} ip32_frame_t;

// States
typedef enum ip32_rx_state_t {
	LEN,
	FLAGS,
	CHKSUM,
	SRC_IP,
	DST_IP,
	PAYLOAD,
	WAIT_AXIS_TLAST
} ip32_rx_state_t;

ip32_rx_state_t ip32_rx_state;
ip32_frame_t ip32_rx_output;
uint16_t ip32_remaining_length;

ip32_frame_t ip_32_rx(axis32_t axis)
{
	// Get keep bytes before endianess change
	uint3_t keep_bytes;
	keep_bytes = axis32_keep_bytes(axis.keep);	
	
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	axis.data = bswap_32(axis.data);
	axis.keep = uint4_0_3(axis.keep);
	
	// Default no payload
	ip32_rx_output.payload.valid = 0;

	// Wait for valid data
	if(axis.valid == 1)
	{
		if(ip32_rx_state==LEN)
		{
			ip32_rx_output.header.ver = uint32_31_28(axis.data);
			ip32_rx_output.header.ihl = uint32_27_24(axis.data);
			ip32_rx_output.header.dscp = uint32_23_18(axis.data);
			ip32_rx_output.header.ecn = uint32_17_16(axis.data);
			ip32_rx_output.header.total_length = uint32_15_0(axis.data);
			ip32_remaining_length = ip32_rx_output.header.total_length;
			ip32_rx_state = FLAGS;
		}
		else if(ip32_rx_state==FLAGS)
		{   
			// ip32_remaining_length = 16 + payload
			ip32_rx_output.header.iden = uint32_31_16(axis.data);
			ip32_rx_output.header.flags = uint32_15_13(axis.data);
			ip32_rx_output.header.frag = uint32_12_0(axis.data);
			ip32_rx_state = CHKSUM;	
		}
		else if(ip32_rx_state==CHKSUM)
		{
			// ip32_remaining_length = 12 + payload
			ip32_rx_output.header.ttl = uint32_31_24(axis.data);
			ip32_rx_output.header.protocol = uint32_23_16(axis.data);
			ip32_rx_output.header.checksum = uint32_15_0(axis.data);
			ip32_rx_state = SRC_IP;
		}
		else if(ip32_rx_state==SRC_IP)
		{
			// ip32_remaining_length = 8 + payload
			ip32_rx_output.header.src_ip = uint32_31_0(axis.data);
			ip32_rx_state = DST_IP;
		}
		else if(ip32_rx_state==DST_IP)
		{
			// ip32_remaining_length = 4 + payload
			ip32_rx_output.header.dst_ip = uint32_31_0(axis.data);
			// Assuming no option for now so
			ip32_rx_state = PAYLOAD;
		}
		else if(ip32_rx_state==PAYLOAD)
		{
			// ip32_remaining_length = payload 
			
			// YAY simple 32b aligned
			ip32_rx_output.payload = axis;
			
			// More bytes after these max 4?
			if(5 > ip32_remaining_length)
			{
				// These are last bytes
				ip32_rx_output.payload.last = 1;
				// Get proper keep
				uint4_t keep;
				keep = axis32_bytes_keep(ip32_remaining_length);
				ip32_rx_output.payload.keep = uint4_0_3(keep); // This was written for big endian 
				
				// Does axis agree?
				if (axis.last == 1)
				{
					// Yes, back to initial state
					ip32_rx_state = LEN;
				}	
				else
				{
					// Oversized frame
					// Wait for padding bytes to be received
					ip32_rx_state = WAIT_AXIS_TLAST;
				}
			}
			
			// Regardless of IP length, undersize frames will return to LEN
			if (axis.last == 1)
			{
				ip32_rx_state = LEN;
			}
		}
		else if(ip32_rx_state==WAIT_AXIS_TLAST)
		{
			// Wait for axis tlast
			if (axis.last == 1)
			{
				ip32_rx_state = LEN;
			}
		}
		
		// Decrement remaining length
		ip32_remaining_length = ip32_remaining_length - keep_bytes;	
	}
	
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	ip32_rx_output.payload.data = bswap_32(ip32_rx_output.payload.data);
	ip32_rx_output.payload.keep = uint4_0_3(ip32_rx_output.payload.keep);
	
	return ip32_rx_output;
}



uint16_t ip_checksum(ip_header_t header)
{	
	// Build 16b words
	uint8_t ver_ihl;
	ver_ihl = uint4_uint4(header.ver, header.ihl);
	uint8_t dscp_ecn;
	dscp_ecn = uint6_uint2(header.dscp, header.ecn);
	uint16_t ver_ihl_dscp_ecn;
	ver_ihl_dscp_ecn = uint8_uint8(ver_ihl,dscp_ecn);
	uint16_t total_length;
	total_length = header.total_length;
	uint16_t flags_frag;
	flags_frag = uint3_uint13(header.flags, header.frag);
	uint16_t ttl_pro;
	ttl_pro = uint8_uint8(header.ttl,header.protocol);
	uint16_t src_ip_msb;
	src_ip_msb = uint32_31_16(header.src_ip);
	uint16_t src_ip_lsb;
	src_ip_lsb = uint32_15_0(header.src_ip);
	uint16_t dst_ip_msb;
	dst_ip_msb = uint32_31_16(header.dst_ip);
	uint16_t dst_ip_lsb;
	dst_ip_lsb = uint32_15_0(header.dst_ip);
	
	// Implement tree sum as generic
	uint20_t sum;
	sum = uint16_sum9(ver_ihl_dscp_ecn, 
				total_length, 
				header.iden, 
				flags_frag,
				ttl_pro, 
				src_ip_msb,  
				src_ip_lsb,
				dst_ip_msb,
				dst_ip_lsb );
				
	
	// Take top 4 bits as carry
	uint4_t carry1;
	carry1 = uint20_19_16(sum);
	uint16_t sum_no_carry1;
	sum_no_carry1 = uint20_15_0(sum);
	
	// Add the sum back in to lower bits
	uint17_t sum_w_carry1;
	sum_w_carry1 = sum_no_carry1 + carry1;
	
	// Have carry bit again?
	uint1_t carry2;
	carry2 = uint17_16_16(sum_w_carry1);
	uint16_t sum_w_carry2;
	sum_w_carry2 = sum_w_carry1 + carry2;
	
	// Invert
	uint16_t rv;
	rv = !sum_w_carry2;
	
	return rv;
}


typedef enum ip32_tx_state_t {
	VER_IDL_DSCP_ECN_LEN,
	IDEN_FLGS_FRAG,
	TTL_PRO_CHK,
	SRC_IP,
	DST_IP,
	PAYLOAD
} ip32_tx_state_t;

ip32_tx_state_t ip32_tx_state;
axis32_t ip32_tx_output;

axis32_t ip32_tx_payload0;
axis32_t ip32_tx_payload1;
axis32_t ip32_tx_payload2;
axis32_t ip32_tx_payload3;
axis32_t ip32_tx_payload4;


axis32_t ip_32_tx_globals(ip32_frame_t ip, uint16_t checksum)
{
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	ip.payload.data = bswap_32(ip.payload.data);
	ip.payload.keep = uint4_0_3(ip.payload.keep);
	
	// Default no payload
	ip32_tx_output.valid = 0;
	
	if(ip32_tx_state==VER_IDL_DSCP_ECN_LEN)
	{
		// Build fields
		uint8_t ver_ihl;
		ver_ihl = uint4_uint4(4, ip.header.ihl); // @_@ . Always IPv4
		uint8_t dscp_ecn;
		dscp_ecn = uint6_uint2(ip.header.dscp, ip.header.ecn);
		uint16_t ver_ihl_dscp_ecn;
		ver_ihl_dscp_ecn = uint8_uint8(ver_ihl,dscp_ecn);
		uint16_t total_length;
		total_length = ip.header.total_length;
		
		// Output
		ip32_tx_output.data = uint16_uint16(ver_ihl_dscp_ecn, total_length);
		ip32_tx_output.keep = 15;
		ip32_tx_output.last = 0;
		
		// Wait for valid data
		if(ip.payload.valid == 1)
		{
			ip32_tx_state = IDEN_FLGS_FRAG;
			ip32_tx_output.valid = 1;
		}	
		// Save payload for later
		ip32_tx_payload0 = ip.payload;			
	}
	else if(ip32_tx_state==IDEN_FLGS_FRAG)
	{
		// Build fields
		uint16_t flags_frag;
		flags_frag = uint3_uint13(ip.header.flags, ip.header.frag);
		
		// Output
		ip32_tx_output.valid = 1;
		ip32_tx_output.keep = 15;
		ip32_tx_output.last = 0;
		ip32_tx_output.data = uint16_uint16(ip.header.iden, flags_frag);
		ip32_tx_state = TTL_PRO_CHK;
		
		// Save payload for later
		ip32_tx_payload1 = ip.payload;
	}
	else if(ip32_tx_state==TTL_PRO_CHK)
	{
		// Build fields
		uint16_t ttl_pro;
		// haha ttl was originally for seconds?
		// UDP
		ttl_pro = uint8_uint8(ip.header.ttl,ip.header.protocol);

		// Output
		ip32_tx_output.valid = 1;
		ip32_tx_output.keep = 15;
		ip32_tx_output.last = 0;
		ip32_tx_output.data = uint16_uint16(ttl_pro, checksum);
		ip32_tx_state = SRC_IP;
		
		// Save payload for later
		ip32_tx_payload2 = ip.payload;		
	}
	else if(ip32_tx_state==SRC_IP)
	{
		ip32_tx_output.valid = 1;
		ip32_tx_output.keep = 15;
		ip32_tx_output.last = 0;
		ip32_tx_output.data = ip.header.src_ip;
		ip32_tx_state = DST_IP;
		
		// Save payload for later
		ip32_tx_payload3 = ip.payload;	
	}
	else if(ip32_tx_state==DST_IP)
	{
		ip32_tx_output.valid = 1;
		ip32_tx_output.keep = 15;
		ip32_tx_output.last = 0;
		ip32_tx_output.data = ip.header.dst_ip;
		// Assuming no option for now so
		ip32_tx_state = PAYLOAD;
		
		// Save payload for later
		ip32_tx_payload4 = ip.payload;	
	}
	else if(ip32_tx_state==PAYLOAD)
	{
		// Only change state / output payload if we have data 
		if(ip32_tx_payload0.valid)
		{
			// Output is valid
			ip32_tx_output = ip32_tx_payload0;
			
			// Back to idle if this was last
			if(ip32_tx_payload0.last)
			{
				ip32_tx_state = VER_IDL_DSCP_ECN_LEN;
			}
		}
		
		// Shift out payload 0
		// ALWAYS NEED TO SHIFT BY 1
		// Either invalid, and can get rid of or was valid and output already
		// Move ip32_tx_payload1 into ip32_tx_payload0 to be output next, etc.
		ip32_tx_payload0 = ip32_tx_payload1;
		ip32_tx_payload1 = ip32_tx_payload2;
		ip32_tx_payload2 = ip32_tx_payload3;
		ip32_tx_payload3 = ip32_tx_payload4;				
		
		// And put the new data in end slot
		ip32_tx_payload4 = ip.payload;		
	}
	
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	ip32_tx_output.data = bswap_32(ip32_tx_output.data);
	ip32_tx_output.keep = uint4_0_3(ip32_tx_output.keep);
	
	return ip32_tx_output;
}


axis32_t ip_32_tx(ip32_frame_t ip)
{
	// Keep checksum (slow) out of global function
	uint16_t checksum;
	checksum = ip_checksum(ip.header);
	
	return ip_32_tx_globals(ip, checksum);
}

