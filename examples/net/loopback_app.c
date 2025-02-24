// Configure FPGA part
#pragma PART "xc7a35ticsg324-1l" 
// and pull in board specific top level IO wires
#define JD_0_IN
#define JD_1_IN
#define JD_2_OUT
#define JD_3_OUT
#define JD_4_IN
#define JD_5_IN
#define JD_6_OUT
//
#define LED0_B_OUT
#define LED0_G_OUT
#define LED0_R_OUT
#include "board/arty.h"
// Use RMII phy wires attached to Arty PMOD D
//  LAN8720 board is not a real standard PMOD
//  so is inserted offset in the PMOD connector
//  Only the required RMII signals are connected
// (VCC and GND pins connected with extra jumper wires)
// Note requires Xilinx tcl:
//  to ignore that the PMOD input clock signal is not high speed clock pin:
//    create_clock -add -name rmii_clk -period 20.0 -waveform {0 10.0} [get_nets {jd_IBUF[0]}]
//    set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets {jd_IBUF[0]}]
//  A=top/inner row, pin1-6
//    IO1 = rmii_clk
//    IO2 = rmii_rx0
//    IO3 = rmii_tx_en
//    IO4 = rmii_tx1
#define RMII_CLK_WIRE pmod_jd_a_i1
#define RMII_RX0_WIRE pmod_jd_a_i2
#define RMII_TX_EN_WIRE pmod_jd_a_o3
#define RMII_TX1_WIRE pmod_jd_a_o4
//  B=bottom/outter row, pin7-12
//    IO1 = rmii_crs
//    IO2 = rmii_rx1
//    IO3 = rmii_tx0
//    IO4 = NO CONNECT
#define RMII_CRS_DV_WIRE pmod_jd_b_i1
#define RMII_RX1_WIRE pmod_jd_b_i2
#define RMII_TX0_WIRE pmod_jd_b_o3
#include "net/rmii_wires.c"

// Include ethernet media access controller configured to use RMII wires and 8b AXIS
#include "net/rmii_eth_mac.c"

// Include logic for parsing/building ethernet frames (8b AXIS)
#include "net/eth_8.h"

// MAC address info we want the fpga to have (shared with software)
#include "fpga_mac.h"

// Loopback structured as separate RX and TX MAINs
// since typical to have different clocks for RX and TX
// (only one clock in this RMII example though, could write as one MAIN)
// Loopback RX to TX with fifos
//  the FIFOs have valid,ready streaming handshake interfaces
#include "global_fifo.h"
GLOBAL_STREAM_FIFO(axis8_t, loopback_payload_fifo, 128) // One to hold the payload data
GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

#pragma MAIN rx_main
void rx_main()
{  
	// Receive the ETH frame
  // Eth rx ready if payload fifo+header fifo ready
  uint1_t eth_rx_out_ready = loopback_payload_fifo_in_ready & loopback_headers_fifo_in_ready;
  
  // The rx module
	eth_8_rx_t eth_rx = eth_8_rx(eth_rx_mac_axis_out, eth_rx_out_ready);
  stream(eth8_frame_t) frame = eth_rx.frame;
  // Filter out all but matching destination mac frames
  uint1_t mac_match = frame.data.header.dst_mac == FPGA_MAC;

  // Write DVR handshake into fifos if mac match
  uint1_t valid_and_ready = frame.valid & eth_rx_out_ready & mac_match;
  // Frame payload and headers go into separate fifos
  loopback_payload_fifo_in.data = frame.data.payload;
  loopback_payload_fifo_in.valid = valid_and_ready;
  // Header only written once at the start of data packet
  loopback_headers_fifo_in.data = frame.data.header;
  loopback_headers_fifo_in.valid = frame.data.start_of_payload & valid_and_ready;
}

#pragma MAIN tx_main
void tx_main()
{  
	// Wire up the ETH frame to send by reading fifos
  stream(eth8_frame_t) frame;
  // Header matches what was sent other than SRC+DST macs
  frame.data.header = loopback_headers_fifo_out.data;
  frame.data.header.dst_mac = frame.data.header.src_mac; // Send back to where came from
  frame.data.header.src_mac = FPGA_MAC; // From FPGA
  // Header and payload need to be valid to send
  frame.data.payload = loopback_payload_fifo_out.data;
  frame.valid = loopback_payload_fifo_out.valid & loopback_headers_fifo_out.valid;
  
  // The tx module
  eth_8_tx_t eth_tx = eth_8_tx(frame, eth_tx_mac_input_ready);
  eth_tx_mac_axis_in = eth_tx.mac_axis;
  
  // Read DVR handshake from fifos
  uint1_t valid_and_ready = frame.valid & eth_tx.frame_ready;
  // Read payload if was ready
  loopback_payload_fifo_out_ready = valid_and_ready;
  // Ready header if was ready at end of packet
  loopback_headers_fifo_out_ready = frame.data.payload.tlast & valid_and_ready;
}

// Santy check clock is working with blinking LED
MAIN_MHZ(blinky_main, RMII_CLK_MHZ)
void blinky_main(){
  static uint25_t counter;
  led_r = 0;
  led_g = 0;
  led_b = counter >> 24;
  counter += 1;
}