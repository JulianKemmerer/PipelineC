#pragma once
#include "uintN_t.h"
#include "bit_manip.h"
#include "axis.h"

typedef struct udp_header_t
{
	uint16_t src_port;
	uint16_t dst_port;
	uint16_t length;
} udp_header_t;

typedef struct udp32_frame_t
{
	udp_header_t header;
	axis32_t payload;
} udp32_frame_t;

// States
typedef enum udp32_rx_state_t {
	PORTS,
	LEN_CHK,
	PAYLOAD
} udp32_rx_state_t;

udp32_rx_state_t udp32_rx_state; // Parser udp32_rx_state
udp32_frame_t udp32_rx_output; // Data to udp32_rx_output

udp32_frame_t udp_32_rx(axis32_t axis)
{
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	axis.data = bswap_32(axis.data);
	axis.keep = uint4_0_3(axis.keep);
	
	// Default no payload
	udp32_rx_output.payload.valid = 0;
	
	// Wait for valid data
	if(axis.valid == 1)
	{
		if(udp32_rx_state==PORTS)
		{
			// Yay easy
			udp32_rx_output.header.src_port = uint32_31_16(axis.data);
			udp32_rx_output.header.dst_port = uint32_15_0(axis.data);
			udp32_rx_state = LEN_CHK;	
		}
		else if(udp32_rx_state==LEN_CHK)
		{
			// Dont care about checksum
			// Store length
			udp32_rx_output.header.length = uint32_31_16(axis.data);
			udp32_rx_state = PAYLOAD;	
		}
		else if(udp32_rx_state==PAYLOAD)
		{
			// YAY simple 32b aligned
			udp32_rx_output.payload = axis;
			
			if (axis.last == 1)
			{
				udp32_rx_state = PORTS;
			}
		}
	}
	
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	udp32_rx_output.payload.data = bswap_32(udp32_rx_output.payload.data);
	udp32_rx_output.payload.keep = uint4_0_3(udp32_rx_output.payload.keep);
	
	return udp32_rx_output;
}

// States
typedef enum udp32_tx_state_t {
	PORTS,
	LEN_CHK,
	PAYLOAD
} udp32_tx_state_t;

udp32_tx_state_t udp32_tx_state;
axis32_t udp32_tx_output;
axis32_t udp32_tx_payload0;
axis32_t udp32_tx_payload1;

axis32_t udp_32_tx(udp32_frame_t udp)
{
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	udp.payload.data = bswap_32(udp.payload.data);
	udp.payload.keep = uint4_0_3(udp.payload.keep);
	
	// Default no output
	udp32_tx_output.valid = 0;
	
	if(udp32_tx_state == PORTS)
	{
		// Output UDP header ports
		udp32_tx_output.data = uint16_uint16(udp.header.src_port, udp.header.dst_port);
		udp32_tx_output.keep = 15;
		udp32_tx_output.last = 0;
		
		// and save payload data for after header
		udp32_tx_payload0 = udp.payload;
		
		// Next state
		// Wait for valid incoming data
		if(udp.payload.valid == 1)
		{
			udp32_tx_output.valid = 1;
			udp32_tx_state = LEN_CHK;
		}
	}
	else if(udp32_tx_state == LEN_CHK)
	{
		// Output UDP len + chksum
		udp32_tx_output.valid = 1;
		udp32_tx_output.data = uint16_uint16(udp.header.length, 0);
		udp32_tx_output.keep = 15;
		udp32_tx_output.last = 0;
		
		// and save payload data for after header
		udp32_tx_payload1 = udp.payload;
		
		// Next state
		udp32_tx_state = PAYLOAD;
	} 
	else if(udp32_tx_state == PAYLOAD)
	{
		// Yay 32b aligned
		// Wait for valid data in window
		if(udp32_tx_payload0.valid == 1)
		{
			// Output payload word
			udp32_tx_output = udp32_tx_payload0;
			
			// Was this the last payload word?
			if(udp32_tx_payload0.last == 1)
			{
				udp32_tx_state = PORTS;
			}
		}
		
		// Move payload1 into payload0 to be output next
		udp32_tx_payload0 = udp32_tx_payload1;
		// And put the new data in payload1
		udp32_tx_payload1 = udp.payload;
	}
	
	// This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
	udp32_tx_output.data = bswap_32(udp32_tx_output.data);
	udp32_tx_output.keep = uint4_0_3(udp32_tx_output.keep);
	
	return udp32_tx_output;
}
