#pragma once
#include "eth_32.c"
#include "ip_32.c"
#include "udp_32.c"

typedef struct udp32_mac_packet_t
{
	eth_header_t eth_header;
	ip_header_t ip_header;
	udp_header_t udp_header;	
	axis32_t payload;
} udp32_mac_packet_t;


udp32_mac_packet_t udp32_mac_rx(axis32_t mac_axis_rx)
{
	udp32_mac_packet_t rx_packet;

	// Receive the ETH frame
	eth32_frame_t eth_rx;
	eth_rx = eth_32_rx(mac_axis_rx);
	rx_packet.eth_header = eth_rx.header;
		
	// Receive IP packet
	ip32_frame_t ip_rx;
	ip_rx = ip_32_rx(eth_rx.payload);
	rx_packet.ip_header = ip_rx.header;
	
	// Receive UDP packet
	udp32_frame_t udp_rx;
	udp_rx = udp_32_rx(ip_rx.payload);
	rx_packet.udp_header = udp_rx.header;
	rx_packet.payload = udp_rx.payload;

	return rx_packet;
}


axis32_t udp32_mac_tx(udp32_mac_packet_t tx_packet)
{
	// Send the data inside a udp packet
	udp32_frame_t udp_tx;
	udp_tx.header = tx_packet.udp_header;
	udp_tx.payload = tx_packet.payload;
	
	// Form Tx IP packet with UDP packet as payload
	ip32_frame_t ip_tx;
	// MUST fully initialize local variables for now
	ip_tx.header = tx_packet.ip_header;
	ip_tx.payload = udp_32_tx(udp_tx);
	
	// Form Tx ETH frame with ip packet as payload
	eth32_frame_t eth_tx;
	eth_tx.header = tx_packet.eth_header;
	eth_tx.payload = ip_32_tx(ip_tx); // Payload is IP tx packet
	
	// Transmit the ETH frame
	axis32_t mac_axis_tx;
	mac_axis_tx = eth_32_tx(eth_tx);
	
	return mac_axis_tx;
}
