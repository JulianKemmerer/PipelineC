// TODO how to make switchable between different MII interfaces?
#include "rmii_eth_mac.h"

// instance of RX side FSM for RMII
// Globally visible outputs
stream(axis8_t) eth_rx_mac_axis_out;
uint1_t eth_rx_mac_error;
#pragma MAIN rmii_rx_mac_instance
void rmii_rx_mac_instance(){
  // Instance of rmii_rx_mac connected to global wires
  rmii_rx_mac_t mac_out = rmii_rx_mac(
    rmii_rx, 
    rmii_crs_dv
  );
  eth_rx_mac_axis_out = mac_out.rx_mac_axis_out;
  eth_rx_mac_error = mac_out.rx_mac_error;
}

// instance of TX side FSM for RMII
// Globally visible inputs
stream(axis8_t) eth_tx_mac_axis_in;
// Globally visible outputs
uint1_t eth_tx_mac_input_ready;
#pragma MAIN rmii_tx_mac_instance
void rmii_tx_mac_instance(){
  // Instance of rmii_tx_mac connected to global wires
  rmii_tx_mac_t mac_out = rmii_tx_mac(
    eth_tx_mac_axis_in
  );
  rmii_tx = mac_out.tx_mac_output_data;
  rmii_tx_en = mac_out.tx_mac_output_valid;
  eth_tx_mac_input_ready = mac_out.tx_mac_input_ready;
}