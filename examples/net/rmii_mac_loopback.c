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
#define RMII_WIRES_DEBUG
#define RMII_ETH_MAC_DEBUG
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

// Loopback uses small fifo to to connect RX to TX
#include "fifo.h"
#define ETH_FIFO_DEPTH 128
FIFO_FWFT(eth_fifo, axis8_t, ETH_FIFO_DEPTH)

MAIN_MHZ(main, RMII_CLK_MHZ)
void main()
{
	axis8_t data_in = eth_rx_mac_axis_out.data;
	uint1_t wr = eth_rx_mac_axis_out.valid;
  uint1_t rd = eth_tx_mac_input_ready;
	eth_fifo_t eth_read = eth_fifo(rd, data_in, wr);
	eth_tx_mac_axis_in.data = eth_read.data_out;
	eth_tx_mac_axis_in.valid = eth_read.data_out_valid;
	// No RX ready for input, cant push back on rmii rx mac
	// eth_rx_mac_axis_out_ready = eth_read.data_in_ready;
}

// Santy check clock is working with blinking LED
MAIN_MHZ(blinky_main, RMII_CLK_MHZ)
void blinky_main(){
  static uint23_t counter;
  led_r = 0;
  led_g = 0;
  led_b = counter >> 22;
  counter += 1;
}
