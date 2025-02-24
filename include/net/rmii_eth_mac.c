// TODO how to make switchable between different MII interfaces?
#include "rmii_eth_mac.h"
#include "global_fifo.h"

// Optional to include a FIFO (with built in skid buffers)
#ifdef RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH
// Skid buffer in path from
// RX MAC OUT -> RX FIFO WR IN
GLOBAL_STREAM_FIFO_SKID_IN_BUFF(axis8_t, rmii_eth_mac_rx_fifo, RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH)
#endif
#ifdef RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH
// Skid buffer in path from
// TX FIFO RD OUT -> TX MAC IN
GLOBAL_STREAM_FIFO_SKID_OUT_BUFF(axis8_t, rmii_eth_mac_tx_fifo, RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH)
#endif

// instance of RX side FSM for RMII
// Globally visible outputs
stream(axis8_t) eth_rx_mac_axis_out;
uint1_t eth_rx_mac_error;
// Instance of rmii_rx_mac connected to global wires
#pragma MAIN rmii_rx_mac_instance
void rmii_rx_mac_instance(){
  rmii_rx_mac_t mac_out = rmii_rx_mac(
    rmii_rx, 
    rmii_crs_dv
  );
  #ifdef RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH
  // MAC output connects into FIFO write
  rmii_eth_mac_rx_fifo_in = mac_out.rx_mac_axis_out;
  eth_rx_mac_error = mac_out.rx_mac_error;
  #else
  // Normal no fifo connect mac out to globals
  eth_rx_mac_axis_out = mac_out.rx_mac_axis_out;
  eth_rx_mac_error = mac_out.rx_mac_error;
  #endif
}
#ifdef RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH
#pragma FUNC_WIRES rmii_rx_mac_fifo_connect
#pragma MAIN rmii_rx_mac_fifo_connect
void rmii_rx_mac_fifo_connect(){
  // FIFO read output connects to globals
  eth_rx_mac_axis_out = rmii_eth_mac_rx_fifo_out;
  rmii_eth_mac_rx_fifo_out_ready = 1; // No flow control, overflows
}
#endif

// instance of TX side FSM for RMII
// Globally visible inputs
stream(axis8_t) eth_tx_mac_axis_in;
// Globally visible outputs
uint1_t eth_tx_mac_input_ready;
// Instance of rmii_tx_mac connected to global wires
#pragma MAIN rmii_tx_mac_instance
void rmii_tx_mac_instance(){
  #ifdef RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH
  // FIFO read output into MAC
  rmii_tx_mac_t mac_out = rmii_tx_mac(
    rmii_eth_mac_tx_fifo_out
  );
  rmii_eth_mac_tx_fifo_out_ready = mac_out.tx_mac_input_ready;
  #else
  // Normal no fifo connect globals to mac in
  rmii_tx_mac_t mac_out = rmii_tx_mac(
    eth_tx_mac_axis_in
  );
  eth_tx_mac_input_ready = mac_out.tx_mac_input_ready;
  #endif
  rmii_tx = mac_out.tx_mac_output_data;
  rmii_tx_en = mac_out.tx_mac_output_valid;
}
#ifdef RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH
#pragma FUNC_WIRES rmii_tx_mac_fifo_connect
#pragma MAIN rmii_tx_mac_fifo_connect
void rmii_tx_mac_fifo_connect(){
  // Globals to FIFO write input
  rmii_eth_mac_tx_fifo_in = eth_tx_mac_axis_in;
  eth_tx_mac_input_ready = rmii_eth_mac_tx_fifo_in_ready;
}
#endif

#ifdef RMII_ETH_MAC_DEBUG
#pragma FUNC_MARK_DEBUG rmii_eth_mac_debug
#pragma MAIN rmii_eth_mac_debug
void rmii_eth_mac_debug(){
  static stream(axis8_t) eth_rx_mac_axis_out_reg;
  //static uint1_t eth_rx_mac_error_reg; 
  static stream(axis8_t) eth_tx_mac_axis_in_reg;
  static uint1_t eth_tx_mac_input_ready_reg;
  eth_rx_mac_axis_out_reg = eth_rx_mac_axis_out;
  //eth_rx_mac_error_reg = eth_rx_mac_error;
  eth_tx_mac_axis_in_reg = eth_tx_mac_axis_in;
  eth_tx_mac_input_ready_reg = eth_tx_mac_input_ready;  
}
#endif