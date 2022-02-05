// Include board media access controller (8b AXIS)
#include "xil_temac.c"

// Include logic for parsing ethernet frames from 32b AXIS
#include "net/eth_32.c"

// Include the mac address info we want the fpga to have
#include "fpga_mac.h"

// Loopback RX to TX with two clock crossing async fifos
axis32_t loopback_payload_fifo[16]; // One to hold the payload data
eth_header_t loopback_headers_fifo[2]; // another one to hold the headers
#include "clock_crossing/loopback_payload_fifo.h"
#include "clock_crossing/loopback_headers_fifo.h"

// Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
#pragma MAIN_GROUP rx_main xil_temac_rx 
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
  axis32_t axis_rx = to_axis32.axis_out;
  
	// Receive the ETH frame
  // Feedback inputs from later modules
  uint1_t eth_rx_out_ready;
  #pragma FEEDBACK eth_rx_out_ready
  // The rx module
	eth_32_rx_t eth_rx = eth_32_rx(axis_rx, eth_rx_out_ready);
  eth32_frame_t frame = eth_rx.frame;
  
  // Filter out all but matching destination mac frames
  uint8_t FPGA_MAC_BYTES[6];
  FPGA_MAC_BYTES[0] = FPGA_MAC0;
  FPGA_MAC_BYTES[1] = FPGA_MAC1;
  FPGA_MAC_BYTES[2] = FPGA_MAC2;
  FPGA_MAC_BYTES[3] = FPGA_MAC3;
  FPGA_MAC_BYTES[4] = FPGA_MAC4;
  FPGA_MAC_BYTES[5] = FPGA_MAC5;
  uint48_t FPGA_MAC = uint8_array6_be(FPGA_MAC_BYTES); // Network, big endian, byte order
  uint1_t mac_match = frame.header.dst_mac == FPGA_MAC;

  // Write into fifos if mac match
  uint1_t payload_wr_en = frame.payload.valid & eth_rx_out_ready & mac_match;
  // Only write into headers fifo if starting a packet
  uint1_t header_wr_en = eth_rx.start_of_packet & eth_rx_out_ready & mac_match;
  axis32_t payload_wr_data[1];
  payload_wr_data[0] = frame.payload;
  eth_header_t header_wr_data[1];
  header_wr_data[0] = frame.header;
  // Frame payload and headers go into separate fifos
  loopback_payload_fifo_write_t payload_write = loopback_payload_fifo_WRITE_1(payload_wr_data, payload_wr_en);
  loopback_headers_fifo_write_t header_write = loopback_headers_fifo_WRITE_1(header_wr_data, header_wr_en);
  
  // Eth rx was ready if payload fifo+header fifo was ready
  eth_rx_out_ready = payload_write.ready & header_write.ready; // FEEDBACK
  
  // TODO CONNECT OVERFLOW TO LED
  
  // Write wires back into RX MAC
  xil_rx_to_temac_t to_mac;
  // Config bits
  to_mac.pause_req = 0;
  to_mac.pause_val = 0;
  to_mac.rx_configuration_vector = 0;
  to_mac.rx_configuration_vector |= ((uint32_t)1<<1); // RX enable
  to_mac.rx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s
  WIRE_WRITE(xil_rx_to_temac_t, xil_rx_to_temac, to_mac)  
}

// Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
#pragma MAIN_GROUP tx_main xil_temac_tx 
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
  uint1_t eth_tx_out_ready;
  #pragma FEEDBACK eth_tx_out_ready
  eth32_frame_t frame;
  // Header matches what was sent other than SRC+DST macs
  frame.header = header_read.data[0];
  uint8_t FPGA_MAC_BYTES[6];
  FPGA_MAC_BYTES[0] = FPGA_MAC0;
  FPGA_MAC_BYTES[1] = FPGA_MAC1;
  FPGA_MAC_BYTES[2] = FPGA_MAC2;
  FPGA_MAC_BYTES[3] = FPGA_MAC3;
  FPGA_MAC_BYTES[4] = FPGA_MAC4;
  FPGA_MAC_BYTES[5] = FPGA_MAC5;
  uint48_t FPGA_MAC = uint8_array6_be(FPGA_MAC_BYTES); // Network, big endian, byte order
  frame.header.dst_mac = frame.header.src_mac; // Send back to where came from
  frame.header.src_mac = FPGA_MAC; // From FPGA
  // Header and payload need to be valid to send
  frame.payload = payload_read.data[0];
  frame.payload.valid = payload_read.valid & header_read.valid;
  
  // The tx module
  eth_32_tx_t eth_tx = eth_32_tx(frame, eth_tx_out_ready);
  axis32_t axis_tx = eth_tx.mac_axis;
  // Read payload if was ready
  payload_read_en = eth_tx.frame_ready & frame.payload.valid; // FEEDBACK
  // Ready header if was ready at end of packet
  header_read_en = eth_tx.frame_ready & frame.payload.last & frame.payload.valid; // FEEDBACK
    
	// Convert axis32 to axis8
  axis32_to_axis8_t to_axis8 = axis32_to_axis8(axis_tx, mac_ready);
  axis8_t mac_axis_tx = to_axis8.axis_out;
  eth_tx_out_ready = to_axis8.axis_in_ready; // FEEDBACK
  
  // Write wires back into TX MAC 
  xil_tx_to_temac_t to_mac;
  to_mac.tx_axis_mac = mac_axis_tx;
  // Config bits
  to_mac.tx_ifg_delay = 0;
  to_mac.tx_configuration_vector = 0;
  to_mac.tx_configuration_vector |= ((uint32_t)1<<1); // TX enable
  to_mac.tx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s
  WIRE_WRITE(xil_tx_to_temac_t, xil_tx_to_temac, to_mac)
}
