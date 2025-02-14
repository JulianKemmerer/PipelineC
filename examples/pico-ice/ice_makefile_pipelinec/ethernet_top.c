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
// with enabled clock crossing fifos (with skid buffers)
#define RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH 8
#define RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH 8
#include "net/rmii_eth_mac.c"

// Include logic for parsing/building ethernet frames (8b AXIS)
#include "net/eth_8.h"
// MAC address info we want the fpga to have
#define FPGA_MAC 0xA0B1C2D3E4F5

// Loopback structured as separate RX and TX MAINs
// since typical to have different clocks for RX and TX
// (only one clock in this example though, could write as one MAIN)
// Loopback RX to TX with fifos
//  the FIFOs have valid,ready streaming handshake interfaces
GLOBAL_STREAM_FIFO(axis8_t, loopback_payload_fifo, 16) // One to hold the payload data
GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

MAIN_MHZ(rx_main, PLL_CLK_MHZ)
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

MAIN_MHZ(tx_main, PLL_CLK_MHZ)
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

// Santy check RMII clock is working with blinking LED
MAIN_MHZ(blinky_main, RMII_CLK_MHZ)
void blinky_main(){
  static uint25_t counter;
  led_r = counter >> 24;
  led_g = 1;
  led_b = 1;
  counter += 1;
}
