#pragma once
// https://www.xilinx.com/support/documentation/ip_documentation/tri_mode_ethernet_mac/v9_0/pg051-tri-mode-eth-mac.pdf
/* Board MII Interface abstracted by this core
    mii_tx_clk : IN STD_LOGIC;
    mii_txd : OUT STD_LOGIC_VECTOR(3 DOWNTO 0);
    mii_tx_en : OUT STD_LOGIC;
    mii_tx_er : OUT STD_LOGIC;
    mii_rxd : IN STD_LOGIC_VECTOR(3 DOWNTO 0);
    mii_rx_dv : IN STD_LOGIC;
    mii_rx_er : IN STD_LOGIC;
    mii_rx_clk : IN STD_LOGIC;
  CLOCK AND RESETS
    glbl_rstn : IN STD_LOGIC;
    rx_axi_rstn : IN STD_LOGIC;
    tx_axi_rstn : IN STD_LOGIC;
    rx_mac_aclk : OUT STD_LOGIC;
    tx_mac_aclk : OUT STD_LOGIC;
*/
#include "compiler.h"
#include "wire.h"
#include "uintN_t.h"
#include "axi/axis.h"

// Flattened simple types board level top IO
DECL_INPUT(uint1_t, eth_rx_clk)
DECL_INPUT(uint4_t, eth_rxd)
DECL_INPUT(uint1_t, eth_rx_dv)
DECL_INPUT(uint1_t, eth_rxerr)
DECL_INPUT(uint1_t, eth_tx_clk)
DECL_OUTPUT(uint4_t, eth_txd)
DECL_OUTPUT(uint1_t, eth_tx_en)
DECL_OUTPUT(uint1_t, eth_mdc)
DECL_OUTPUT(uint1_t, eth_rstn)

// Header for nicer types related to the MAC
#include "xil_temac.h"

// Internal instance of the core
// produces two clocks, rx and tx
// Need to global wires to/from the shared rx/tx instance
// to be marked as as ASYNC_WIRE
// so CDC isnt checked into invidual RX and TX clock domains
xil_temac_to_rx_t xil_temac_to_rx_async;
#pragma ASYNC_WIRE xil_temac_to_rx_async
xil_temac_to_tx_t xil_temac_to_tx_async;
#pragma ASYNC_WIRE xil_temac_to_tx_async
xil_rx_to_temac_t xil_rx_to_temac_async;
#pragma ASYNC_WIRE xil_rx_to_temac_async
xil_tx_to_temac_t xil_tx_to_temac_async;
#pragma ASYNC_WIRE xil_tx_to_temac_async
// The core itself will be in the 'ref_clk' domain
// (this clock is actually only for the external off chip phy)
#define XIL_TEMAC_REF_CLK_MHZ 25.0
// Two separate clocks, rx and tx produced by the TEMAC
#define XIL_TEMAC_RX_MHZ 25.0
#define XIL_TEMAC_TX_MHZ 25.0
uint1_t xil_temac_rx_mac_aclk;
CLK_MHZ_GROUP(xil_temac_rx_mac_aclk, XIL_TEMAC_RX_MHZ, xil_temac_rx)
uint1_t xil_temac_tx_mac_aclk;
CLK_MHZ_GROUP(xil_temac_tx_mac_aclk, XIL_TEMAC_TX_MHZ, xil_temac_tx)

// Internal globally visible 'ports' / 'wires'
// RX
// Input
xil_rx_to_temac_t xil_rx_to_temac;
// Output
xil_temac_to_rx_t xil_temac_to_rx;
MAIN_MHZ_GROUP(xil_temac_rx_module, XIL_TEMAC_RX_MHZ, xil_temac_rx) // Set clock freq and group
void xil_temac_rx_module()
{
  // For the pipelinec tool only
  // use async wires here in a fixed/known clock domain
  // to have them be check for valid CDC
  xil_temac_to_rx = xil_temac_to_rx_async;
  xil_rx_to_temac_async = xil_rx_to_temac;
}

// TX
// Input
xil_tx_to_temac_t xil_tx_to_temac;
// Output
xil_temac_to_tx_t xil_temac_to_tx;
MAIN_MHZ_GROUP(xil_temac_tx_module, XIL_TEMAC_TX_MHZ, xil_temac_tx) // Set clock freq and group
void xil_temac_tx_module()
{
  // For the pipelinec tool only
  // use async wires here in a fixed/known clock domain
  // to have them be check for valid CDC
  xil_temac_to_tx = xil_temac_to_tx_async;
  xil_tx_to_temac_async = xil_tx_to_temac;
}

// Instance of the core connected to ASYNC global wires
// (separate global wires and main funcs are used to give clock to RX/TX parts above)
MAIN_MHZ(xil_temac_instance, XIL_TEMAC_REF_CLK_MHZ)
void xil_temac_instance(uint1_t reset_n){
  xil_temac_inputs_t xil_temac_inputs;
  // Clock and Reset
  xil_temac_inputs.glbl_rstn = reset_n;
  xil_temac_inputs.rx.axi_rstn = reset_n;
  xil_temac_inputs.tx.axi_rstn = reset_n;
  // MII
  xil_temac_inputs.rx.mii_clk = eth_rx_clk;
  xil_temac_inputs.rx.mii_d = eth_rxd;
  xil_temac_inputs.rx.mii_dv = eth_rx_dv;
  xil_temac_inputs.rx.mii_er = eth_rxerr;
  xil_temac_inputs.tx.mii_clk = eth_tx_clk;
  // AXIS
  xil_temac_inputs.tx.axis_mac = xil_tx_to_temac_async.tx_axis_mac;
  // Everything else
  xil_temac_inputs.tx.configuration_vector = xil_tx_to_temac_async.tx_configuration_vector;
  xil_temac_inputs.tx.ifg_delay = xil_tx_to_temac_async.tx_ifg_delay;
  xil_temac_inputs.rx.configuration_vector = xil_rx_to_temac_async.rx_configuration_vector;
  xil_temac_inputs.rx.pause_req = xil_rx_to_temac_async.pause_req;
  xil_temac_inputs.rx.pause_val = xil_rx_to_temac_async.pause_val;
  xil_temac_outputs_t xil_temac_outputs = xil_temac(xil_temac_inputs);
  // Clock and Reset
  xil_temac_rx_mac_aclk = xil_temac_outputs.rx.mac_aclk;
  xil_temac_tx_mac_aclk = xil_temac_outputs.tx.mac_aclk;
  xil_temac_to_rx_async.rx_reset = xil_temac_outputs.rx.reset;
  xil_temac_to_tx_async.tx_reset = xil_temac_outputs.tx.reset;
  // MII
  eth_rstn = reset_n;
  eth_txd = xil_temac_outputs.tx.mii_d;
  eth_tx_en = xil_temac_outputs.tx.mii_en;
  eth_mdc = 0;
  xil_temac_to_rx_async.rx_enable = xil_temac_outputs.rx.enable;
  xil_temac_to_tx_async.tx_enable = xil_temac_outputs.tx.enable;
  // AXIS
  xil_temac_to_rx_async.rx_axis_mac = xil_temac_outputs.rx.axis_mac;
  xil_temac_to_tx_async.tx_axis_mac_ready = xil_temac_outputs.tx.axis_mac_ready;
  // Everything else
  xil_temac_to_rx_async.rx_statistics_vector = xil_temac_outputs.rx.statistics_vector;
  xil_temac_to_rx_async.rx_statistics_valid = xil_temac_outputs.rx.statistics_valid;
  xil_temac_to_rx_async.speedis100 = xil_temac_outputs.speedis100;
  xil_temac_to_rx_async.speedis10100 = xil_temac_outputs.speedis10100;
  xil_temac_to_tx_async.tx_statistics_vector = xil_temac_outputs.tx.statistics_vector;
  xil_temac_to_tx_async.tx_statistics_valid = xil_temac_outputs.tx.statistics_valid;
  xil_temac_to_tx_async.speedis100 = xil_temac_outputs.speedis100;
  xil_temac_to_tx_async.speedis10100 = xil_temac_outputs.speedis10100;
}

