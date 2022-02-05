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

// Two clocks, rx and tx
#define XIL_TEMAC_RX_MHZ 25.0
#define XIL_TEMAC_TX_MHZ 25.0

// RX
typedef struct xil_temac_to_rx_t
{
  // RX data
  axis8_t rx_axis_mac;
  //rx_axis_mac_tuser : OUT STD_LOGIC;
  
  // RX stats
  uint28_t rx_statistics_vector;
  uint1_t rx_statistics_valid;
  uint1_t rx_reset;
  uint1_t rx_enable;

  // Stats
  uint1_t speedis100;
  uint1_t speedis10100;
}xil_temac_to_rx_t;
typedef struct xil_rx_to_temac_t
{
  // RX config
  uint1_t pause_req;
  uint16_t pause_val;
  uint80_t rx_configuration_vector;
}xil_rx_to_temac_t;

// TX
typedef struct xil_tx_to_temac_t
{
  // TX data
  axis8_t tx_axis_mac;
  //tx_axis_mac_tuser : IN STD_LOGIC_VECTOR(0 DOWNTO 0);
  
  // TX config
  uint8_t tx_ifg_delay;
  uint80_t tx_configuration_vector;
}xil_tx_to_temac_t;
typedef struct xil_temac_to_tx_t
{
  // TX flow control
  uint1_t tx_axis_mac_ready;
  
  // TX stats
  uint32_t tx_statistics_vector;
  uint1_t tx_statistics_valid;
  uint1_t tx_reset;
  uint1_t tx_enable;

  // Stats
  uint1_t speedis100;
  uint1_t speedis10100;
}xil_temac_to_tx_t;

// Internal globally visible 'ports' / 'wires' (a subset of clock domain crossing)
// RX
// Input
xil_rx_to_temac_t xil_rx_to_temac;
#include "clock_crossing/xil_rx_to_temac.h"
// Output
xil_temac_to_rx_t xil_temac_to_rx;
#include "clock_crossing/xil_temac_to_rx.h"
// TX
// Input
xil_tx_to_temac_t xil_tx_to_temac;
#include "clock_crossing/xil_tx_to_temac.h"
// Output
xil_temac_to_tx_t xil_temac_to_tx;
#include "clock_crossing/xil_temac_to_tx.h"

// RX
MAIN_MHZ_GROUP(xil_temac_rx_module, XIL_TEMAC_RX_MHZ, xil_temac_rx) // Set clock freq and group
xil_rx_to_temac_t xil_temac_rx_module(xil_temac_to_rx_t temac_to_rx)
{
  xil_rx_to_temac_t rx_to_temac;
  WIRE_READ(xil_rx_to_temac_t, rx_to_temac, xil_rx_to_temac)
  WIRE_WRITE(xil_temac_to_rx_t, xil_temac_to_rx, temac_to_rx)
  return rx_to_temac;
}

// Top level io connection to board interface
// TX
MAIN_MHZ_GROUP(xil_temac_tx_module, XIL_TEMAC_TX_MHZ, xil_temac_tx) // Set clock freq and group
xil_tx_to_temac_t xil_temac_tx_module(xil_temac_to_tx_t temac_to_tx)
{
  xil_tx_to_temac_t tx_to_temac;
  WIRE_READ(xil_tx_to_temac_t, tx_to_temac, xil_tx_to_temac)
  WIRE_WRITE(xil_temac_to_tx_t, xil_temac_to_tx, temac_to_tx)
  return tx_to_temac;
}


