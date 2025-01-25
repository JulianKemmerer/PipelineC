#pragma PART "xc7a35ticsg324-1l" 

// AXIS types and datawidth converters
#include "axi/axis.h"

// Include board media access controller (8b AXIS)
#include "xil_temac.c"

// Include logic for parsing/building ethernet frames (32b AXIS)
#include "net/eth_32.c"

// Include the mac address info we want the fpga to have
#include "fpga_mac.h"

// Loopback RX to TX with two clock crossing async fifos
//  the FIFOs have valid,ready streaming handshake interfaces
#include "stream/stream.h"

#include "global_fifo.h"
GLOBAL_STREAM_FIFO(axis32_t, loopback_payload_fifo, 16) // One to hold the payload data
GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

// Same clock group as Xilinx TEMAC
MAIN_MHZ_GROUP(rx_main, XIL_TEMAC_RX_MHZ, xil_temac_rx) 
void rx_main()
{
  // Config bits for RX MAC
  xil_rx_to_temac.pause_req = 0; // not pausing data
  xil_rx_to_temac.pause_val = 0;
  xil_rx_to_temac.rx_configuration_vector = 0;
  xil_rx_to_temac.rx_configuration_vector |= ((uint32_t)1<<1); // RX enable
  xil_rx_to_temac.rx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s
  // TODO stats+reset+enable and overflow indicator

  // The stream of data from the RX MAC
  stream(axis8_t) mac_axis_rx = xil_temac_to_rx.rx_axis_mac;
  
  // Convert axis8 to axis32
  // Signal always ready, overflow occurs in eth_32_rx 
  //(TEMAC doesnt have mac axis ready flow control)
  axis8_to_axis32_t to_axis32 = axis8_to_axis32(mac_axis_rx, 1);
  stream(axis32_t) axis_rx = to_axis32.axis_out;
  
	// Receive the ETH frame
  // Eth rx ready if payload fifo+header fifo ready
  uint1_t eth_rx_out_ready = loopback_payload_fifo_in_ready & loopback_headers_fifo_in_ready;
  // The rx module
	eth_32_rx_t eth_rx = eth_32_rx(axis_rx, eth_rx_out_ready);
  eth32_frame_t frame = eth_rx.frame;
  
  // Filter out all but matching destination mac frames
  uint1_t mac_match = frame.header.dst_mac == FPGA_MAC;

  // Write into fifos if mac match
  // Frame payload and headers go into separate fifos
  loopback_payload_fifo_in.data = frame.payload.data;
  loopback_payload_fifo_in.valid = frame.payload.valid & eth_rx_out_ready & mac_match;
  // Header only written once at the start of data packet
  loopback_headers_fifo_in.data = frame.header;
  loopback_headers_fifo_in.valid = eth_rx.start_of_packet & eth_rx_out_ready & mac_match;
}

// Same clock group as Xilinx TEMAC
MAIN_MHZ_GROUP(tx_main, XIL_TEMAC_TX_MHZ, xil_temac_tx)
void tx_main()
{
  // Config bits for TX MAC
  xil_tx_to_temac.tx_ifg_delay = 0; // no gap between frames
  xil_tx_to_temac.tx_configuration_vector = 0;
  xil_tx_to_temac.tx_configuration_vector |= ((uint32_t)1<<1); // TX enable
  xil_tx_to_temac.tx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s  
  // TODO stats+reset+enable
  
	// Wire up the ETH frame to send by reading fifos
  eth32_frame_t frame;
  // Header matches what was sent other than SRC+DST macs
  frame.header = loopback_headers_fifo_out.data;
  frame.header.dst_mac = frame.header.src_mac; // Send back to where came from
  frame.header.src_mac = FPGA_MAC; // From FPGA
  // Header and payload need to be valid to send
  frame.payload.data = loopback_payload_fifo_out.data;
  frame.payload.valid = loopback_payload_fifo_out.valid & loopback_headers_fifo_out.valid;
  
  // The tx module
  uint1_t eth_tx_out_ready;
  #pragma FEEDBACK eth_tx_out_ready
  eth_32_tx_t eth_tx = eth_32_tx(frame, eth_tx_out_ready);
  stream(axis32_t) axis_tx = eth_tx.mac_axis;
  // Read payload if was ready
  loopback_payload_fifo_out_ready = eth_tx.frame_ready & frame.payload.valid;
  // Ready header if was ready at end of packet
  loopback_headers_fifo_out_ready = eth_tx.frame_ready & frame.payload.data.tlast & frame.payload.valid;
    
	// Convert axis32 to axis8
  axis32_to_axis8_t to_axis8 = axis32_to_axis8(axis_tx, xil_temac_to_tx.tx_axis_mac_ready);
  xil_tx_to_temac.tx_axis_mac = to_axis8.axis_out;
  eth_tx_out_ready = to_axis8.axis_in_ready; // FEEDBACK  
}
