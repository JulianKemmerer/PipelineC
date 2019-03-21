#pragma once
#include "protocol.h"
// Receive/send udp data from ethernet ports
#include "../../udp_32_mac.c"

// Big endian byte muxing helper function
uint8_t be_byte_mux(uint32_t data, uint2_t sel)
{
	return uint8_mux4(sel, 
		uint32_31_24(data), //0
		uint32_23_16(data), //1
		uint32_15_8(data), //2
		uint32_7_0(data) //3
	);
}

// Parse the incoming 32b of UDP payload
// Which 32b of the packet are we talking about?
typedef enum parse_state_t 
{
	IDLE_HEADER0,
	HEADER1,
	HEADER2,
	HEADER3,
	HEADER4,
	HEADER5,
	EXTRAS,
	KEY,
	VALUE	
} parse_state_t;
parse_state_t parse_state;
// The result of the parsing
memcached_packet_t parsed_packet;
// Extra state for variable length data
packet_iter_t parse_pos;
memcached_packet_s parse(axis32_t udp_payload)
{
	// No output yet
	memcached_packet_s rv;
	rv.valid = 0;
	
	// How many bytes do we have this cycle?
	uint3_t keep_bytes;
	keep_bytes = axis32_keep_bytes(udp_payload.keep);
	
	// AXIS is little endian, parsing is easier when big, so swap
	udp_payload.data = bswap_32(udp_payload.data);
	udp_payload.keep = uint4_0_3(udp_payload.keep);
	
	// Default keep same state
	parse_state_t next_state;
	next_state = parse_state;
	packet_iter_t next_pos;
	next_pos = parse_pos;
	
	// Do stuff per state
	if(parse_state==IDLE_HEADER0)
	{
		parsed_packet.header.magic = uint32_31_24(udp_payload.data);
		parsed_packet.header.opcode = uint32_23_16(udp_payload.data);
		parsed_packet.header.key_len = uint32_15_0(udp_payload.data);
		next_state = HEADER1;
	}
	else if(parse_state==HEADER1)
	{
		parsed_packet.header.extras_len = uint32_31_24(udp_payload.data);
		parsed_packet.header.data_type = uint32_23_16(udp_payload.data);
		parsed_packet.header.vbucket_status = uint32_15_0(udp_payload.data);
		next_state = HEADER2;
	}
	else if(parse_state==HEADER2)
	{
		parsed_packet.header.total_body_len = uint32_31_0(udp_payload.data);
		next_state = HEADER3;
	}
	else if(parse_state==HEADER3)
	{
		parsed_packet.header.opaque = uint32_31_0(udp_payload.data);
		next_state = HEADER4;
	}
	else if(parse_state==HEADER4)
	{
		uint32_t msb;
		msb = uint32_31_0(udp_payload.data);
		parsed_packet.header.cas = uint64_uint32_32(parsed_packet.header.cas, msb);
		next_state = HEADER5;
	}
	else if(parse_state==HEADER5)
	{
		uint32_t lsb;
		lsb = uint32_31_0(udp_payload.data);
		parsed_packet.header.cas = uint64_uint32_0(parsed_packet.header.cas, lsb);
		
		// Variable length data is next
		// Need to calculate length of variable length value
		parsed_packet.value_len = parsed_packet.header.total_body_len - parsed_packet.header.extras_len - parsed_packet.header.key_len; 
		
		// Starting at byte 0 of whatever variable length data comes next
		next_pos = 0;
		
		// Extras next if present
		if(parsed_packet.header.extras_len > 0)
		{
			next_state = EXTRAS;
		}
		// Next is key
		else if(parsed_packet.header.key_len > 0)
		{
			next_state = KEY;
		}
		// Value
		else if(parsed_packet.value_len > 0)
		{
			next_state = VALUE;
		}
		else
		{
			// End of packet?
			rv.valid = udp_payload.valid & udp_payload.last;
			next_state = IDLE_HEADER0;
		}
	}
	// Variable length data
	else //if( (parse_state == EXTRAS) | (parse_state == KEY) | (parse_state == VALUE) )
	{
		// Get payload bytes
		uint8_t b0;
		b0 = uint32_31_24(udp_payload.data);
		uint8_t b1;
		b1 = uint32_23_16(udp_payload.data);
		uint8_t b2;
		b2 = uint32_15_8(udp_payload.data);
		uint8_t b3;
		b3 = uint32_7_0(udp_payload.data);
		// And put them at certain positions in the packet
		packet_iter_t p0;
		p0 = parse_pos+0;
		packet_iter_t p1;
		p1 = parse_pos+1;
		packet_iter_t p2;
		p2 = parse_pos+2;
		packet_iter_t p3;
		p3 = parse_pos+3;
		
		// What kind of bytes?
		// Where is end pos for variable length data?
		packet_iter_t end_pos;
		if(parse_state == EXTRAS)
		{
			parsed_packet.extras[p0] = b0;
			parsed_packet.extras[p1] = b1;
			parsed_packet.extras[p2] = b2;
			parsed_packet.extras[p3] = b3;
			end_pos = parsed_packet.header.extras_len - 1;
		}
		else if(parse_state == KEY)
		{
			parsed_packet.key[p0] = b0;
			parsed_packet.key[p1] = b1;
			parsed_packet.key[p2] = b2;
			parsed_packet.key[p3] = b3;
			end_pos = parsed_packet.header.key_len - 1;
		}
		else // VALUE
		{
			parsed_packet.value[p0] = b0;
			parsed_packet.value[p1] = b1;
			parsed_packet.value[p2] = b2;
			parsed_packet.value[p3] = b3;
			end_pos = parsed_packet.value_len - 1;
		}
		
		// Does this cycle contain the end of the current variable length data?
		packet_iter_t cycle_end_pos;
		cycle_end_pos = parse_pos+keep_bytes-1;
		if(cycle_end_pos >= end_pos)
		{
			// Yes got last bytes of variable length data
			// How many bytes for current field?
			uint3_t curr_fields_bytes;
			curr_fields_bytes = end_pos - parse_pos + 1;
			// How many of those bytes are for the next fields? (max 3)
			uint2_t next_fields_bytes;
			next_fields_bytes = cycle_end_pos-end_pos;
			// Split field bytes into remianing key|value
			uint2_t remaining_field_bytes;
			remaining_field_bytes = next_fields_bytes;
			
			// Key only possibly next if in EXTRAS
			uint2_t key_bytes;
			key_bytes = 0;
			if(parse_state == EXTRAS)
			{
				// How many key bytes
				if(parsed_packet.header.key_len > remaining_field_bytes)
				{
					key_bytes = remaining_field_bytes;
				}
				else
				{
					key_bytes = parsed_packet.header.key_len;
				}
				// Adjust remaining bytes for value
				remaining_field_bytes = remaining_field_bytes - key_bytes;
			}
			
			// Value only possible in EXTRAS and KEY
			uint2_t value_bytes;
			value_bytes = 0;
			if((parse_state == EXTRAS) | (parse_state == KEY))
			{
				// How many value bytes?
				if(parsed_packet.value_len > remaining_field_bytes)
				{
					value_bytes = remaining_field_bytes;
				}
				else
				{
					value_bytes = parsed_packet.value_len;
				}
			}
			
			// Handle key+value fields in current cycle
			// Which axis byte pos has next field data?
			uint2_t axis_pos;
			axis_pos = curr_fields_bytes;
			
			// Key and value data is few few bytes if any
			
			// Key only possibly next if in EXTRAS
			if(parse_state == EXTRAS)
			{
				// Do loop for up to 3 bytes of key data
				uint2_t key_pos;
				for(key_pos = 0; key_pos < 3; key_pos = key_pos + 1)
				{
					if(key_pos < key_bytes)
					{
						parsed_packet.key[key_pos] = be_byte_mux(udp_payload.data, axis_pos+key_pos);
					}
				}
			}
		
			// Value only possible in EXTRAS and KEY
			if((parse_state == EXTRAS) | (parse_state == KEY))
			{
				// Do loop for up to 3 bytes of value data
				// Starting at axis pos after key
				axis_pos = axis_pos + key_bytes;
				uint2_t value_pos;
				for(value_pos = 0; value_pos < 3; value_pos = value_pos + 1)
				{
					if(value_pos < value_bytes)
					{
						parsed_packet.value[value_pos] = be_byte_mux(udp_payload.data, axis_pos+value_pos);
					}
				}
			}
				
			// Next stage, more key or more value?
			// Key only possibly next if in EXTRAS
			if( (parsed_packet.header.key_len > key_bytes) & (parse_state == EXTRAS) )
			{
				next_state = KEY;
				next_pos = key_bytes;
			}
			// Value only possible in EXTRAS and KEY
			else if( (parsed_packet.value_len > value_bytes) & ((parse_state == EXTRAS) | (parse_state == KEY)) )
			{
				next_state = VALUE;
				next_pos = value_bytes;
			}
			else
			{
				// End of packet?
				// Output is ready
				rv.valid = udp_payload.valid;
				next_state = IDLE_HEADER0;
			}		
		}
		else
		{
			// Still more variable length data, increment pos
			next_pos = parse_pos + 4;
		}
	}
	
	// Go to next state if got valid data
	if(udp_payload.valid)
	{
		parse_state = next_state;
		parse_pos = next_pos;
		// Sanity, if last then back to idle
		if(udp_payload.last)
		{
			parse_state = IDLE_HEADER0;
		}
	}
	
	// Output data is parsed data
	rv.data = parsed_packet;
	
	return rv;
}

memcached_packet_s receive(axis32_t mac_axis_rx)
{
	// Receive the UDP packet
	udp32_mac_packet_t udp_rx;
	udp_rx = udp32_mac_rx(mac_axis_rx);
	
	// Do ETH/IP/UDP filtering here if needed
	
	// Parse udp payload bytes to memcached
	memcached_packet_s request;
	request = parse(udp_rx.payload);

	return request;
}
