// These are pipeline C modules I have already written
#include "eth_32.c"
#include "ip_32.c"
#include "udp_32.c"

// I'm going to define some structs so swapping out 
// what is in the udp payload is a less annoying.
// I should code generate much of this.

// The struct we intended to receive via UDP
#define RX_SIZE 8 // No sizeof() right now
#define RX_UDP_LENGTH 16 // 8 + 8 byte header
#define RX_IP_LENGTH 36 // 16 + 20 byte header
// (^ did not nest definitions since cant have 
// multiple add operations on a single line right now, dumb I know)
typedef struct rx_data_t
{
	float x0;
	float x1;
} rx_data_t;

// Add a valid signal to the RX data so we know when its ready
typedef struct udp_rx_payload_t
{
	rx_data_t data;
	uint1_t valid;
} udp_rx_payload_t;

// The struct we intended to send via UDP
#define TX_SIZE 4 // No sizeof() right now
#define TX_UDP_LENGTH 12 // 4 + 8 byte header
#define TX_IP_LENGTH 32 // 12 + 20 byte header
// (^ did not nest definitions since cant have 
// multiple add operations on a single line right now, dumb I know)
typedef struct tx_data_t
{
	float x0;
} tx_data_t;

// Add a valid signal to the data so we know when its ready
typedef struct udp_tx_payload_t
{
	tx_data_t data;
	uint1_t valid;
} udp_tx_payload_t;

// Logic to get RX data from AXIS UDP payload 4 bytes at a time
// (TOTALY could benefit from code generation)
typedef enum deserialize_state_t {
	X0,
	X1
} deserialize_state_t;
deserialize_state_t deserialize_state;
udp_rx_payload_t deserialize_rv;
udp_rx_payload_t deserialize(axis32_t axis)
{
	// Dont have all the data to return yet
	deserialize_rv.valid = 0;

	// Likely need to swap endianess
	axis.data = bswap_32(axis.data);
	axis.keep = uint4_0_3(axis.keep);
	
	if (axis.valid == 1)
	{
		if(deserialize_state==X0)
		{
			deserialize_rv.data.x0 = float_uint32(axis.data);
			deserialize_state = X1;
		}
		else // X1
		{
			deserialize_rv.data.x1 = float_uint32(axis.data);
			// Got all the data  now
			deserialize_rv.valid = 1;
			// Back to start
			deserialize_state = X0;
		}
		
		// Always reset if last
		if(axis.last == 1)
		{
			deserialize_state = X0;
		}
	}
	
	return deserialize_rv;
}

// Logic to put TX data into AXIS 4 bytes at a time for UDP payload
// (TOTALY could benefit from code generation)
typedef enum serialize_state_t {
	X0
} serialize_state_t;
serialize_state_t serialize_state;
tx_data_t serialize_data;
axis32_t serialize_rv;
axis32_t serialize(udp_tx_payload_t payload)
{
	// No output data yet
	serialize_rv.valid = 0;
	serialize_rv.last = 0;
	serialize_rv.keep = 15;
	
	/*
	if(serialize_state==X0)
	{*/
		// Wait for valid to get started
		if(payload.valid)
		{
			// Save copy of input data
			serialize_data = payload.data;
			
			// Output data
			serialize_rv.data = float_31_0(serialize_data.x0);
			serialize_rv.valid = 1;
			serialize_rv.last = 1;
			serialize_state = X0;
		}
	/*
	}
	else //X0_LSB
	{
		// data = x0[31:0]
		serialize_rv.data = uint64_31_0(serialize_data.x0);
		serialize_rv.valid = 1;
		serialize_rv.last = 1;
		serialize_state = X0_MSB;
	}*/
	
	// Likely need to swap endianess
	serialize_rv.data = bswap_32(serialize_rv.data);
	serialize_rv.keep = uint4_0_3(serialize_rv.keep);
	
	return serialize_rv;
}

// Receive UDP payload data from the ethernet port
udp_rx_payload_t receive(axis32_t mac_axis_rx)
{
	// Receive the ETH frame
	eth32_frame_t eth_rx;
	eth_rx = eth_32_rx(mac_axis_rx);
	
	// Receive IP packet
	ip32_frame_t ip_rx;
	ip_rx = ip_32_rx(eth_rx.payload);
	
	// Receive UDP packet
	udp32_frame_t udp_rx;
	udp_rx = udp_32_rx(ip_rx.payload);
	
	// Deserialize the rx data from the UDP AXIS
	udp_rx_payload_t rv;
	rv = deserialize(udp_rx.payload);
	return rv;
}

// Transmit UDP payload data out the ethernet port
axis32_t transmit(udp_tx_payload_t payload)
{
	// Serialize the tx data into AXIS for UDP payload
	axis32_t tx_data;
	tx_data = serialize(payload);
	
	// Send the data inside a udp packet
	udp32_frame_t udp_tx;
	udp_tx.header.src_port = 1234;
	udp_tx.header.dst_port = 5678;
	udp_tx.header.length = TX_UDP_LENGTH;
	udp_tx.payload = tx_data;
	
	// Form Tx IP packet with UDP packet as payload
	ip32_frame_t ip_tx;
	// MUST fully initialize local variables for now
	ip_tx.header.ver = 4;
	ip_tx.header.ihl = 5;
	ip_tx.header.dscp = 0;
	ip_tx.header.ecn = 0;
	ip_tx.header.total_length = TX_IP_LENGTH;
	ip_tx.header.iden = 0;
	ip_tx.header.flags = 0;
	ip_tx.header.frag = 0;
	ip_tx.header.ttl = 1;
	ip_tx.header.protocol = 17; // UDP
	ip_tx.header.checksum = 0; // Calculated for you
	ip_tx.header.src_ip = 16909060; //0x01020304
	ip_tx.header.dst_ip = 84281096; //0x05060708
	ip_tx.payload = udp_32_tx(udp_tx);
	
	// Form Tx ETH frame with ip packet as payload
	eth32_frame_t eth_tx;
	eth_tx.header.dst_mac = uint24_uint24(66051, 263430); // 0x010203 040506
	eth_tx.header.src_mac = uint24_uint24(658188, 920847); // 0x0A0B0C 0E0D0F
	eth_tx.header.ethertype = 2048; // IP
	eth_tx.payload = ip_32_tx(ip_tx); // Payload is IP tx packet
	
	// Transmit the ETH frame
	axis32_t mac_axis_tx;
	mac_axis_tx = eth_32_tx(eth_tx);
	
	return mac_axis_tx;
}

// Do something with RX data to form TX data
tx_data_t foo(rx_data_t rx_data)
{
	tx_data_t tx_data;
	// Like add two numbers! Rock on!
	tx_data.x0 = rx_data.x0 + rx_data.x1;
	return tx_data;
}

// Input: AXIS from TEMAC
// Output: AXIS to TEMAC
axis32_t main(axis32_t mac_axis_rx)
{
	// Receive data from the ethernet port
	udp_rx_payload_t rx_payload;
	rx_payload = receive(mac_axis_rx);
	
	// Do some work to form transmit data
	udp_tx_payload_t tx_payload;
	tx_payload.data = foo(rx_payload.data);
	tx_payload.valid = rx_payload.valid;
	
	// Transmit data out the ethernet port
	axis32_t mac_axis_tx;
	mac_axis_tx = transmit(tx_payload);
	return mac_axis_tx;
}
