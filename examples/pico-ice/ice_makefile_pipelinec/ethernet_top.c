#include "uintN_t.h"
#include "compiler.h"
#include "fifo.h"
#include "global_fifo.h"

// See pico-ice-sdk/rtl/pico_ice.pcf
#pragma PART "ICE40UP5K-SG48"
// Get clock rate constant PLL_CLK_MHZ from header written by make flow
#include "pll_clk_mhz.h"
// By default PipelineC names clock ports with the rate included
// ex. clk_12p0
// Override this behavior by creating an input with a constant name
// and telling the tool that input signal is a clock of specific rate
DECL_INPUT(uint1_t, pll_clk)
CLK_MHZ(pll_clk, PLL_CLK_MHZ)
// Configure IO direction for each pin used
// Use RMII phy wires attached to pico ice PMOD 0
//  LAN8720 board is not a real standard PMOD
//  so is inserted offset in the PMOD connector
//  Only the required RMII signals are connected
// (VCC and GND pins connected with extra jumper wires)
//  A=top/inner row, pin1-6
//    IO1 = rmii_clk
//    IO2 = rmii_rx0
//    IO3 = rmii_tx_en
//    IO4 = rmii_tx1
#define PMOD_0A_I1
#define RMII_CLK_WIRE pmod_0a_i1
#define PMOD_0A_I2
#define RMII_RX0_WIRE pmod_0a_i2
#define PMOD_0A_O3
#define RMII_TX_EN_WIRE pmod_0a_o3
#define PMOD_0A_O4
#define RMII_TX1_WIRE pmod_0a_o4
//  B=bottom/outter row, pin7-12
//    IO1 = rmii_crs
//    IO2 = rmii_rx1
//    IO3 = rmii_tx0
//    IO4 = NO CONNECT
#define PMOD_0B_I1
#define RMII_CRS_DV_WIRE pmod_0b_i1
#define PMOD_0B_I2
#define RMII_RX1_WIRE pmod_0b_i2
#define PMOD_0B_O3
#define RMII_TX0_WIRE pmod_0b_o3
#include "board/pico_ice.h"

#include "net/rmii_wires.c"

// Include ethernet media access controller configured to use RMII wires and 8b AXIS
#include "net/rmii_eth_mac.c"

// Include logic for parsing/building ethernet frames (8b AXIS)
//#include "net/eth_8.h"
// MAC address info we want the fpga to have
//#define FPGA_MAC 0xA0B1C2D3E4F5

// Loopback structured as separate RX and TX MAINs
// since typical to have different clocks for RX and TX
// (only one clock in this RMII example though, could write as one MAIN)
// Loopback RX to TX with fifos
//  the FIFOs have valid,ready streaming handshake interfaces

//GLOBAL_STREAM_FIFO(axis8_t, loopback_payload_fifo, 64) // One to hold the payload data
//GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

// Skid buffer in path from
// RX MAC OUT -> RX FIFO WR IN
GLOBAL_STREAM_FIFO_SKID_IN_BUFF(axis8_t, rx_fifo, 8)
// Skid buffer in path from
// TX FIFO RD OUT -> TX MAC IN
GLOBAL_STREAM_FIFO_SKID_OUT_BUFF(axis8_t, tx_fifo, 8)

// TODO MOVE SKID BUFFERS INTO FIFOs as DECLARED GLOBAL_STREAM_FIFO_SKID_BUFF
// THEN MAKE GLOBAL_STREAM_FIFO_SKID_BUFF CDC FIFOS A rmii_eth_mac.c OPTION
// REORG INTO separate rx/tx mains like original loopback demo? or use one MAIN with local fifo?

// Write into RX FIFO at 50M, Read from TX FIFO
MAIN_MHZ(rx_fifo_write_tx_fifo_read, RMII_CLK_MHZ)
void rx_fifo_write_tx_fifo_read(){
  rx_fifo_in = eth_rx_mac_axis_out;
  // no rx ready eth_rx_mac_axis_out_ready = rx_fifo_in_ready;

  eth_tx_mac_axis_in = tx_fifo_out;
  tx_fifo_out_ready = eth_tx_mac_input_ready;
}

// Loopback uses small fifo to to connect RX to TX

#define ETH_FIFO_DEPTH 16
FIFO_FWFT(eth_fifo, axis8_t, ETH_FIFO_DEPTH)

// Read from RX FIFO at 12.5M, Write into TX FIFO
MAIN_MHZ(rx_fifo_read_tx_fifo_write, PLL_CLK_MHZ)
void rx_fifo_read_tx_fifo_write(){

  eth_fifo_t eth_read = eth_fifo(tx_fifo_in_ready, rx_fifo_out.data, rx_fifo_out.valid);
  tx_fifo_in.data = eth_read.data_out;
  tx_fifo_in.valid = eth_read.data_out_valid;
  rx_fifo_out_ready = eth_read.data_in_ready;

  //tx_fifo_in = rx_fifo_out;
  //rx_fifo_out_ready = tx_fifo_in_ready;
}


/*
#pragma MAIN rx_main
void rx_main()
{  
	// Receive the ETH frame
  // Eth rx ready if payload fifo+header fifo ready
  uint1_t skid_buf_out_ready = loopback_payload_fifo_in_ready & loopback_headers_fifo_in_ready;
  
  #warning "TEMP FAKE MAC MATCH REG"
  static uint1_t mac_match_reg;

  // The rx module
  uint1_t eth_rx_out_ready;
  #pragma FEEDBACK eth_rx_out_ready
	eth_8_rx_t eth_rx = eth_8_rx(eth_rx_mac_axis_out, eth_rx_out_ready);

  // Skid buffer between RX module and fifo
  skid_buf_t skid = skid_buf(eth_rx.frame, skid_buf_out_ready);
  eth_rx_out_ready = skid.ready_for_axis_in; // FEEDBACK
  
  stream(eth8_frame_t) frame = skid.axis_out;

  // Filter out all but matching destination mac frames
  uint1_t mac_match = frame.data.header.dst_mac == FPGA_MAC;

  // Write DVR handshake into fifos if mac match
  uint1_t valid_and_ready = frame.valid & skid_buf_out_ready & mac_match_reg;
  // Frame payload and headers go into separate fifos
  loopback_payload_fifo_in.data = frame.data.payload;
  loopback_payload_fifo_in.valid = valid_and_ready;
  // Header only written once at the start of data packet
  loopback_headers_fifo_in.data = frame.data.header;
  loopback_headers_fifo_in.valid = frame.data.start_of_payload & valid_and_ready;

  mac_match_reg = mac_match;
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


  // SKID buffer between FIFOs and TX module
  uint1_t skid_buf_out_ready;
  #pragma FEEDBACK skid_buf_out_ready
  skid_buf_t skid = skid_buf(frame, skid_buf_out_ready);

  
  // The tx module
  eth_8_tx_t eth_tx = eth_8_tx(skid.axis_out, eth_tx_mac_input_ready);
  eth_tx_mac_axis_in = eth_tx.mac_axis;
  skid_buf_out_ready = eth_tx.frame_ready; // FEEDBACK
  
  // Read DVR handshake from fifos
  uint1_t valid_and_ready = skid.axis_out.valid & skid.ready_for_axis_in;
  // Read payload if was ready
  loopback_payload_fifo_out_ready = valid_and_ready;
  // Ready header if was ready at end of packet
  loopback_headers_fifo_out_ready = skid.axis_out.data.payload.tlast & valid_and_ready;
}
*/

// Santy check clock is working with blinking LED
MAIN_MHZ(blinky_main, RMII_CLK_MHZ)
void blinky_main(){
  static uint25_t counter;
  led_r = 1;
  led_g = counter >> 24;
  led_b = 1;
  counter += 1;
}
