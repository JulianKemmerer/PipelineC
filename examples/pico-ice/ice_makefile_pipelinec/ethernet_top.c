#include "uintN_t.h"
#include "compiler.h"

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

/*
// ARTY TEST
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
*/

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
#include "global_fifo.h"
//GLOBAL_STREAM_FIFO(axis8_t, loopback_payload_fifo, 64) // One to hold the payload data
//GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

GLOBAL_STREAM_FIFO(axis8_t, rx_fifo, 8) // TODO what is min? 16 doesnt always meet timing? (Xilinx min is 16)
GLOBAL_STREAM_FIFO(axis8_t, tx_fifo, 8) // TODO what is min? 16 doesnt always meet timing? (Xilinx min is 16)

// Skid buffer for registering DVR handshake in and out of FIFOs
typedef struct skid_buf_t{
  // Outputs from module
  //  Output .data and .valid stream
  stream(axis8_t) axis_out;
  //  Output ready for input axis stream
  uint1_t ready_for_axis_in;
}skid_buf_t;
skid_buf_t skid_buf(
  // Inputs to module
  //  Input .data and .valid stream
  stream(axis8_t) axis_in,
  //  Input ready for output axis stream
  uint1_t ready_for_axis_out
){
  // Demo logic for skid buffer
  // Static = register
  static stream(axis8_t) buff;
  static stream(axis8_t) skid_buff;
  // Idea of skid buffer is to switch between two buffers
  // to skid to a stop while avoiding a comb. path from 
  //  ready_for_axis_out -> ready_for_axis_in
  // loosely like a 2-element FIFO...
  static uint1_t output_is_skid_buff; // aka input_is_buff

  // Output signals
  skid_buf_t o; // Default value all zeros

  // Connect output based on buffer in use
  // ready for input if other buffer is empty(not valid)
  if(output_is_skid_buff){
    o.axis_out = skid_buff;
    o.ready_for_axis_in = ~buff.valid;
  }else{
    o.axis_out = buff;
    o.ready_for_axis_in = ~skid_buff.valid;
  }

  // Input ready writes buffer
  if(o.ready_for_axis_in){
    if(output_is_skid_buff){
      buff = axis_in;
    }else{
      skid_buff = axis_in;
    }
  }

  // No Output or output ready
  // clears buffer and switches to next buffer
  if(~o.axis_out.valid | ready_for_axis_out){
    if(output_is_skid_buff){
      skid_buff.valid = 0;
    }else{
      buff.valid = 0;
    }
    output_is_skid_buff = ~output_is_skid_buff;
  }

  return o;
}


// Write into RX FIFO at 50M, Read from TX FIFO
MAIN_MHZ(rx_fifo_write_tx_fifo_read, RMII_CLK_MHZ)
void rx_fifo_write_tx_fifo_read(){
  // TODO MOVE SKID BUFFERS INTO FIFOs as DECLARED

  // Skid buffer in path from
  // RX MAC OUT -> RX FIFO WR IN
  skid_buf_t skid = skid_buf(eth_rx_mac_axis_out, rx_fifo_in_ready);
  rx_fifo_in = skid.axis_out;
  // no rx ready eth_rx_mac_axis_out_ready = skid.ready_for_axis_in;

  //rx_fifo_in = eth_rx_mac_axis_out;
  // no rx ready eth_rx_mac_axis_out_ready = rx_fifo_in_ready;

  // Skid buffer in path from
  // TX FIFO RD OUT -> TX MAC IN
  skid_buf_t skid = skid_buf(tx_fifo_out, eth_tx_mac_input_ready);
  eth_tx_mac_axis_in = skid.axis_out;
  tx_fifo_out_ready = skid.ready_for_axis_in;

  //eth_tx_mac_axis_in = tx_fifo_out;
  //tx_fifo_out_ready = eth_tx_mac_input_ready;
}

// Loopback uses small fifo to to connect RX to TX
#include "fifo.h"
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
  led_g = 1;
  led_b = counter >> 24;
  counter += 1;
}
