#include "protocol.h"
#include "do_requests.c"
// Receive/send udp data from ethernet ports
#include "../../udp_32_mac.c"

// Send response packet 32b at a time
typedef enum serialize_state_t 
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
} serialize_state_t;
memcached_command_result_t serialize_command_result;
serialize_state_t serialize_state;
packet_iter_t serialize_pos;		
axis32_sized16_t serialize(memcached_command_result_s incoming_result)
{
	// This is written to output big endian
	// but is swapped at the end to return correct little endian axis
	
	// Replace global var buffer when new data comes in
	if(incoming_result.valid)
	{
		serialize_command_result = incoming_result.data;
		// Sanity force into IDLE state?
		serialize_state = IDLE_HEADER0;
	}
	
	// What are the result, extras, key, value for this packet?
	// Set defaults
	packet_iter_t i;
	uint16_t status;
	status = 0; // No error
	// Extras
	uint8_t extras_len;
	extras_len = 0;
	uint8_t extras[EXTRAS_MAX_LEN];
	for(i = 0; i < EXTRAS_MAX_LEN; i = i + 1)
	{
		extras[i] = 0;
	}
	// Key
	key_len_t key_len;
	key_len = 0;
	uint8_t key[KEY_MAX_LEN];
	for(i = 0; i < KEY_MAX_LEN; i = i + 1)
	{
		key[i] = 0;
	}
	// Value
	value_len_t value_len;
	value_len = 0;
	uint8_t value[VALUE_MAX_LEN]; 
	for(i = 0; i < VALUE_MAX_LEN; i = i + 1)
	{
		value[i] = 0;
	}	
	
	// What command are we responding to?
	if(serialize_command_result.request.header.opcode == GET)
	{
		// Get response has has extras = 0xdeadbeef if found cache entry
		if(serialize_command_result.hash_map_result.read_valid)
		{
			extras_len = 4; //0xDEADBEEF
			extras[0] = 222; //0xde
			extras[1] = 173; //0xad
			extras[2] = 190; //0xbe
			extras[3] = 239; //0xef	
			value_len = serialize_command_result.hash_map_result.read_data.value_len;
			value = serialize_command_result.hash_map_result.read_data.value;
			status = 0; // No error
		}
		else
		{
			// Did not find
			value_len = 9; // "Not found"
			value[0] = 78; //0x4e ('N')  
			value[1] = 111; //0x6f ('o')  
			value[2] = 116; //0x74 ('t')   
			value[3] = 32; //0x20 (' ')  
			value[4] = 102; //0x66 ('f')  
			value[5] = 111; //0x6f ('o') 
			value[6] = 117; //0x75 ('u')   
			value[7] = 110; //0x6e ('n')  
			value[8] = 100; //0x64 ('d')			
			status = 1; // Key not found
		}			
	}
	// SET MUST not have extras,key,value
	
	// How big is the body after the header?
	uint32_t total_body_len;
	total_body_len = extras_len + key_len + value_len;	
	
	// No output udp payload axis yet
	axis32_sized16_t rv;
	rv.axis.valid = 0;
	rv.axis.data = 0;
	rv.axis.keep = 15;
	rv.axis.last = 0;
	rv.length = 24 + total_body_len;
	
	// Do stuff per state
	if(serialize_state==IDLE_HEADER0)
	{
		rv.axis.data = uint32_uint8_24(rv.axis.data, 129); // 0x81 response packet magic byte
		rv.axis.data = uint32_uint8_16(rv.axis.data, serialize_command_result.request.header.opcode);
		rv.axis.data = uint32_uint16_0(rv.axis.data, key_len);
		
		// Wait for incoming request
		if(incoming_result.valid)
		{
			rv.axis.valid = 1;
			serialize_state = HEADER1;
		}
	}
	else if(serialize_state==HEADER1)
	{
		rv.axis.data = uint32_uint8_24(rv.axis.data, extras_len);
		rv.axis.data = uint32_uint8_16(rv.axis.data, 0); //0x00 Raw bytes data type
		rv.axis.data = uint32_uint16_0(rv.axis.data, status);
		rv.axis.valid = 1;
		serialize_state = HEADER2;
	}
	else if(serialize_state==HEADER2)
	{
		rv.axis.data = total_body_len;
		rv.axis.valid = 1;
		serialize_state = HEADER3;
	}
	else if(serialize_state==HEADER3)
	{
		rv.axis.data = serialize_command_result.request.header.opaque;
		rv.axis.valid = 1;
		serialize_state = HEADER4;
	}
	else if(serialize_state==HEADER4)
	{
		// No CAS for now
		rv.axis.data = uint64_63_32(0);
		rv.axis.valid = 1;
		serialize_state = HEADER5;
	}
	else if(serialize_state==HEADER5)
	{
		// No CAS for now
		rv.axis.data = uint64_31_0(0);
		rv.axis.valid = 1;
		
		// Starting at byte 0 of whatever variable length data comes next
		serialize_pos = 0;
		
		// Extras next if present
		if(extras_len > 0)
		{
			serialize_state = EXTRAS;
		}
		/* Right now no responses include key
		// Next is key
		else if(key_len > 0)
		{
			serialize_state = KEY;
		}*/
		// Then value
		else if(value_len > 0)
		{
			serialize_state = VALUE;
		}
		else
		{
			// End of packet?
			rv.axis.last = 1;
			serialize_state = IDLE_HEADER0;
		}
	}
	// Variable length data
	else //if( (serialize_state == EXTRAS) | (serialize_state == KEY) | (serialize_state == VALUE) )
	{
		// Pull bytes from positions in variable length data
		packet_iter_t p0;
		p0 = serialize_pos+0;
		packet_iter_t p1;
		p1 = serialize_pos+1;
		packet_iter_t p2;
		p2 = serialize_pos+2;
		packet_iter_t p3;
		p3 = serialize_pos+3;
		
		// By default the payload bytes are just whatever is next for this state
		// Other fields might come after
		uint8_t axis_bytes[4];
		uint1_t axis_keep[4];
		// Where is end pos for current variable length data?
		packet_iter_t end_pos;
		if(serialize_state == EXTRAS)
		{
			axis_bytes[0] = extras[p0];
			axis_bytes[1] = extras[p1];
			axis_bytes[2] = extras[p2];
			axis_bytes[3] = extras[p3];
			end_pos = extras_len - 1;
		}
		/* Right now no responses include key
		else if(serialize_state == KEY)
		{
			axis_bytes[0] = key[p0];
			axis_bytes[1] = key[p1];
			axis_bytes[2] = key[p2];
			axis_bytes[3] = key[p3];
			end_pos = key_len - 1;
		}*/
		else // VALUE
		{
			axis_bytes[0] = value[p0];
			axis_bytes[1] = value[p1];
			axis_bytes[2] = value[p2];
			axis_bytes[3] = value[p3];
			end_pos = value_len - 1;
		}
		// Default keep value
		axis_keep[0] = p0 <= end_pos;
		axis_keep[1] = p1 <= end_pos;
		axis_keep[2] = p2 <= end_pos;
		axis_keep[3] = p3 <= end_pos;
	
		// End of current variable length data this cycle?
		packet_iter_t cycle_end_pos;
		cycle_end_pos = p3; //4-1;
		// Does this cycle contain the end of this fields variable length data?
		if(cycle_end_pos >= end_pos)
		{
			// Yes, will send last bytes of variable length data
			// How many bytes for current field?
			uint3_t curr_fields_bytes;
			curr_fields_bytes = end_pos - serialize_pos + 1;
			// How many of those bytes are for the next fields? (max 3)
			uint2_t next_fields_bytes;
			next_fields_bytes = cycle_end_pos-end_pos;
			// Split field bytes into remaining key|value
			uint2_t remaining_field_bytes;
			remaining_field_bytes = next_fields_bytes;
			
			// Key only possibly next if in EXTRAS
			uint2_t key_bytes;
			key_bytes = 0;
			if(serialize_state == EXTRAS)
			{
				// How many key bytes (max == remaining_field_bytes)
				if(key_len > remaining_field_bytes)
				{
					key_bytes = remaining_field_bytes;
				}
				else
				{
					key_bytes = key_len;
				}
				// Adjust remaining bytes for value
				remaining_field_bytes = remaining_field_bytes - key_bytes;
			}
			
			// Value only possible in EXTRAS and KEY
			uint2_t value_bytes;
			value_bytes = 0;
			if((serialize_state == EXTRAS) | (serialize_state == KEY))
			{
				// How many value bytes? (max == remaining_field_bytes)
				if(value_len > remaining_field_bytes)
				{
					value_bytes = remaining_field_bytes;
				}
				else
				{
					value_bytes = value_len;
				}
			}
			
			// Handle key+value fields in current cycle
			// Which axis byte pos has next field data?
			uint2_t axis_pos;
			axis_pos = curr_fields_bytes;
			
			// Key only possibly next if in EXTRAS
			if(serialize_state == EXTRAS)
			{
				// Do loop for up to 3 bytes of key data
				uint2_t key_pos;
				for(key_pos = 0; key_pos < 3; key_pos = key_pos + 1)
				{
					if(key_pos < key_bytes)
					{
						axis_bytes[axis_pos+key_pos] = key[key_pos];
						axis_keep[axis_pos+key_pos] = 1;
					}
				}
			}
		
			// Value only possible in EXTRAS and KEY
			if((serialize_state == EXTRAS) | (serialize_state == KEY))
			{
				// Do loop for up to 3 bytes of value data
				// Starting at axis pos after key
				axis_pos = axis_pos + key_bytes;
				uint2_t value_pos;
				for(value_pos = 0; value_pos < 3; value_pos = value_pos + 1)
				{
					if(value_pos < value_bytes)
					{
						axis_bytes[axis_pos+value_pos] = value[value_pos];
						axis_keep[axis_pos+value_pos] = 1;
					}
				}
			}
				
			// Next stage, more key or more value bytes?
			// Key only possibly next if in EXTRAS
			if( (key_len > key_bytes) & (serialize_state == EXTRAS) )
			{
				serialize_state = KEY;
				serialize_pos = key_bytes;
			}
			// Value only possible in EXTRAS and KEY
			else if( (value_len > value_bytes) & ((serialize_state == EXTRAS) | (serialize_state == KEY)) )
			{
				serialize_state = VALUE;
				serialize_pos = value_bytes;
			}
			else
			{
				// End of packet?
				rv.axis.last = 1;
				serialize_state = IDLE_HEADER0;
			}		
		}
		else
		{
			// Still more variable length data, increment pos
			serialize_pos = serialize_pos + 4;
		}
		
		// Assign payload bytes
		rv.axis.valid = 1;
		rv.axis.data = uint32_uint8_0(rv.axis.data, axis_bytes[3]);
		rv.axis.data = uint32_uint8_8(rv.axis.data, axis_bytes[2]);
		rv.axis.data = uint32_uint8_16(rv.axis.data, axis_bytes[1]);
		rv.axis.data = uint32_uint8_24(rv.axis.data, axis_bytes[0]);
		//
		rv.axis.keep = uint4_uint1_0(rv.axis.keep, axis_keep[3]);
		rv.axis.keep = uint4_uint1_1(rv.axis.keep, axis_keep[2]);
		rv.axis.keep = uint4_uint1_2(rv.axis.keep, axis_keep[1]);
		rv.axis.keep = uint4_uint1_3(rv.axis.keep, axis_keep[0]);		
	}

	// Reverse re verse???
	// ENDIANESS MAKES ME SAD
	rv.axis.data = bswap_32(rv.axis.data);
	rv.axis.keep = uint4_0_3(rv.axis.keep);

	return rv;
}




axis32_t send(memcached_command_result_s incoming_result)
{	
	// Serialize result to udp payload bytes (serialize has input buffer)
	axis32_sized16_t bytes;
	bytes = serialize(incoming_result);
	
	// Form the udp32_mac_packet_t
	udp32_mac_packet_t udp_tx;
	udp_tx.payload = bytes.axis;
	// UDP // By default memcached listens on TCP and UDP ports, both 11211.
	udp_tx.udp_header.src_port = 11211;
	udp_tx.udp_header.dst_port = 11211;
	udp_tx.udp_header.length = 8 + bytes.length;
	// IP
	udp_tx.ip_header.ver = 4;
	udp_tx.ip_header.ihl = 5;
	udp_tx.ip_header.dscp = 0;
	udp_tx.ip_header.ecn = 0;
	udp_tx.ip_header.total_length = 20 + udp_tx.udp_header.length;
	udp_tx.ip_header.iden = 0;
	udp_tx.ip_header.flags = 0;
	udp_tx.ip_header.frag = 0;
	udp_tx.ip_header.ttl = 1;
	udp_tx.ip_header.protocol = 17; // UDP
	udp_tx.ip_header.checksum = 0; // Calculated for you
	udp_tx.ip_header.src_ip = 16909060; //0x01020304
	udp_tx.ip_header.dst_ip = 84281096; //0x05060708
	// ETH
	udp_tx.eth_header.dst_mac = uint24_uint24(66051, 263430); // 0x010203 040506
	udp_tx.eth_header.src_mac = uint24_uint24(658188, 920847); // 0x0A0B0C 0E0D0F
	udp_tx.eth_header.ethertype = 2048; // IP
	
	// Transmit the udp32_mac_packet_t
	axis32_t mac_axis_tx;
	mac_axis_tx = udp32_mac_tx(udp_tx);	
	return mac_axis_tx;
}
