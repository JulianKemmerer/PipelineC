// Include board media access controller
#include "xil_temac.c"

// Include logic for parsing eth/ip/udp frames
#include "eth_32.c"

// Loopback RX to TX with two async fifos
axis32_t loopback_payload_fifo[16]; // One to hold the payload data
eth_header_t loopback_headers_fifo[2]; // another one to hold the headers
#include "loopback_payload_fifo_clock_crossing.h"
#include "loopback_headers_fifo_clock_crossing.h"

#pragma MAIN_GROUP rx_main xil_temac_rx // Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
void rx_main()
{
  // Read wire from RX MAC
  xil_temac_to_rx_t from_mac;
  WIRE_READ(xil_temac_to_rx_t, from_mac, xil_temac_to_rx)
  // The stream of data from the RX MAC
  axis8_t mac_axis_rx = from_mac.rx_axis_mac;
  
  // TODO stats+reset+enable

  // Convert axis8 to axis32
  // Signal always ready, overflow occurs in eth_32_rx 
  //(TEMAC doesnt have mac axis ready flow control)
  axis8_to_axis32_t to_axis32 = axis8_to_axis32(mac_axis_rx, 1);
  axis32_t axis32_rx = to_axis32.axis_out;
  
	// Receive the ETH frame
  // Feedback inputs from later modules
  uint1_t eth_32_rx_out_ready;
  #pragma FEEDBACK eth_32_rx_out_ready
  // The module
	eth_32_rx_t eth_rx = eth_32_rx(axis32_rx, eth_32_rx_out_ready);
  eth32_frame_t frame = eth_rx.frame;

  // Write into fifos
  axis32_t payload_wr_data[1];
  payload_wr_data[0] = frame.payload;
  eth_header_t header_wr_data[1];
  header_wr_data[0] = frame.header;
  // Frame payload and headers go into separate fifos
  // Only write into headers fifo if starting a packet
  loopback_payload_fifo_write_t payload_write = loopback_payload_fifo_WRITE_1(payload_wr_data, frame.payload.valid);
  loopback_headers_fifo_write_t header_write = loopback_headers_fifo_WRITE_1(header_wr_data, eth_rx.start_of_packet);
  
  // Frame was ready if payload fifo+header fifo was ready
  eth_32_rx_out_ready = payload_write.ready & header_write.ready; // FEEDBACK
  
  // TODO CONNECT OVERFLOW TO LED
  
  // Write wires back into RX MAC
  xil_rx_to_temac_t to_mac;
  // Config bits
  to_mac.pause_req = 0;
  to_mac.pause_val = 0;
  to_mac.rx_configuration_vector = 0;
  to_mac.rx_configuration_vector |= (1<<1); // RX enable
  to_mac.rx_configuration_vector |= (1<<12); // 100Mb/s 
  WIRE_WRITE(xil_rx_to_temac_t, xil_rx_to_temac, to_mac)  
}

#pragma MAIN_GROUP tx_main xil_temac_tx // Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
void tx_main()
{
  // Read wires from TX MAC
  xil_temac_to_tx_t from_mac;
  WIRE_READ(xil_temac_to_tx_t, from_mac, xil_temac_to_tx)
  uint1_t mac_ready = from_mac.tx_axis_mac_ready;
  
  // TODO stats+reset+enable
  
  // Try to read from fifos if ready to tx eth frame
  // Only read header out of fifo, dropping on floor, at end of packet
  uint1_t payload_read_en;
  #pragma FEEDBACK payload_read_en
  uint1_t header_read_en;
  #pragma FEEDBACK header_read_en
  loopback_payload_fifo_read_t payload_read = loopback_payload_fifo_READ_1(payload_read_en);
  loopback_headers_fifo_read_t header_read = loopback_headers_fifo_READ_1(header_read_en);  
  
	// Wire up the ETH frame to send
  uint1_t eth_32_tx_out_ready;
  #pragma FEEDBACK eth_32_tx_out_ready
  eth32_frame_t eth_tx;
  eth_tx.header = header_read.data[0];
  eth_tx.payload = payload_read.data[0];
  // Header and payload need to be valid to send
  eth_tx.payload.valid = payload_read.valid & header_read.valid;
  // The tx module
  eth_32_tx_t eth_32_tx = eth_32_tx(eth_tx, eth_32_tx_out_ready);
  axis32_t axis_tx = eth_32_tx.mac_axis;
  // Read payload if was ready
  payload_read_en = eth_32_tx.frame_ready; // FEEDBACK
  // Ready header if was ready at end of packet
  header_read_en = eth_32_tx.frame_ready & eth_32_tx.mac_axis.last & eth_32_tx.mac_axis.valid; // FEEDBACK
    
	// Convert axis32 to axis8
  axis32_to_axis8_t to_axis8 = axis32_to_axis8(axis_tx, mac_ready);
  axis8_t mac_axis_tx = to_axis8.axis_out;
  eth_32_tx_out_ready = to_axis8.axis_in_ready; // FEEDBACK
  
  // Write wires back into TX MAC 
  xil_tx_to_temac_t to_mac;
  to_mac.tx_axis_mac = mac_axis_tx;
  // Config bits
  to_mac.tx_ifg_delay = 0;
  to_mac.tx_configuration_vector = 0;
  to_mac.tx_configuration_vector |= (1<<1); // TX enable
  to_mac.tx_configuration_vector |= (1<<12); // 100Mb/s
  WIRE_WRITE(xil_tx_to_temac_t, xil_tx_to_temac, to_mac)
}


 /*
#include "ip_32.c"
#include "udp_32.c"

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
	
	eth_tx.header = eth_rx.header; // Copy header fields from RX
	eth_tx.payload = ip_32_tx(ip_tx); // Payload is IP tx packet
  */
