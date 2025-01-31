#pragma PART "LFE5UM-85F-6BG381C"
#include "uintN_t.h"
#include "compiler.h"

// Configure for RMII PHY module instance 
// connected to these pins on dev board
#define GP11_IN
#define GN11_IN
#define GP12_IN
#define GN12_IN
#define GN9_OUT
#define GP10_OUT
#define GN10_OUT
#include "board/ulxs3.h"
#define RMII_TX_EN_WIRE gn10
#define RMII_TX0_WIRE gp10
#define RMII_TX1_WIRE gn9
#define RMII_CRS_DV_WIRE gp12
#define RMII_RX0_WIRE gn11
#define RMII_RX1_WIRE gp11
#define RMII_CLK_WIRE gn12
#include "net/rmii_wires.c"
#include "net/rmii_eth_mac.c"

// Loopback uses small fifo to to connect RX to TX
// TODO fix to be stream(axis8_t) instead of uint8_t
#include "fifo.h"
#define ETH_FIFO_DEPTH 128
FIFO_FWFT(eth_fifo, uint8_t, ETH_FIFO_DEPTH)

MAIN_MHZ(main, RMII_CLK_MHZ)
void main()
{
	uint8_t data_in = eth_rx_mac_axis_out.data.tdata[0];
	uint1_t wr = eth_rx_mac_axis_out.valid;
  uint1_t rd = eth_tx_mac_input_ready;
	eth_fifo_t eth_read = eth_fifo(rd, data_in, wr);
	eth_tx_mac_axis_in.data.tdata[0] = eth_read.data_out;
	eth_tx_mac_axis_in.data.tkeep[0] = 1; // only 1 byte, always kept
	eth_tx_mac_axis_in.data.tlast = eth_read.empty; // TODO fix, not correct
	eth_tx_mac_axis_in.valid = eth_read.data_out_valid;
	// No RX ready for input, cant push back on rmii rx mac
	// eth_rx_mac_axis_out_ready = eth_read.data_in_ready;
}
