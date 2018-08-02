#include "eth_32.c"
#include "ip_32.c"
#include "udp_32.c"

axis32_t main(axis32_t mac_axis_rx)
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
	
	// Form Tx IP packet with UDP packet as payload
	ip32_frame_t ip_tx;
	ip_tx.header = ip_rx.header; // Copy header fields from RX
	ip_tx.payload = udp_32_tx(udp_rx);
	
	// Form Tx ETH frame with ip packet as payload
	eth32_frame_t eth_tx;
	eth_tx.header = eth_rx.header; // Copy header fields from RX
	eth_tx.payload = ip_32_tx(ip_tx); // Payload is IP tx packet
	
	// Transmit the ETH frame
	axis32_t mac_axis_tx;
	mac_axis_tx = eth_32_tx(eth_tx);
	
	return mac_axis_tx;
}
