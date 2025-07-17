#pragma once
#include "stream/stream.h"

typedef struct xil_temac_rx_inputs_t{
  uint1_t axi_rstn;
  uint4_t mii_d;
  uint1_t mii_dv;
  uint1_t mii_er;
  uint1_t mii_clk;
  uint80_t configuration_vector;
  uint1_t pause_req;
  uint16_t pause_val;
}xil_temac_rx_inputs_t;

typedef struct xil_temac_tx_inputs_t{
  uint1_t axi_rstn;
  uint8_t ifg_delay;
  stream(axis8_t) axis_mac;
  uint1_t mii_clk;
  uint80_t configuration_vector;
}xil_temac_tx_inputs_t;

typedef struct xil_temac_inputs_t{
  xil_temac_rx_inputs_t rx;
  xil_temac_tx_inputs_t tx;
  uint1_t glbl_rstn;
}xil_temac_inputs_t;

typedef struct xil_temac_rx_outputs_t{
  uint28_t statistics_vector;
  uint1_t statistics_valid;
  uint1_t mac_aclk;
  uint1_t reset;
  uint1_t enable;
  stream(axis8_t) axis_mac;
}xil_temac_rx_outputs_t;

typedef struct xil_temac_tx_outputs_t{
  uint32_t statistics_vector;
  uint1_t statistics_valid;
  uint1_t reset;
  uint1_t enable;
  uint1_t mac_aclk;
  uint1_t axis_mac_ready;
  uint4_t mii_d;
  uint1_t mii_en;
  uint1_t mii_er;
}xil_temac_tx_outputs_t;

typedef struct xil_temac_outputs_t{
  xil_temac_rx_outputs_t rx;
  xil_temac_tx_outputs_t tx;
  uint1_t speedis100;
  uint1_t speedis10100;
}xil_temac_outputs_t;

// Blackbox wont be synthesized outside of final external user project
#pragma FUNC_BLACKBOX xil_temac 
xil_temac_outputs_t xil_temac(xil_temac_inputs_t inputs){
  __vhdl__("\n\
  -- Component generated from Xilinx IP catalog (user project specific) \n\
  -- Possible to use entity instantiation? \n\
  COMPONENT tri_mode_ethernet_mac_0 \n\
  PORT ( \n\
    glbl_rstn : IN STD_LOGIC; \n\
    rx_axi_rstn : IN STD_LOGIC; \n\
    tx_axi_rstn : IN STD_LOGIC; \n\
    rx_statistics_vector : OUT STD_LOGIC_VECTOR(27 DOWNTO 0); \n\
    rx_statistics_valid : OUT STD_LOGIC; \n\
    rx_mac_aclk : OUT STD_LOGIC; \n\
    rx_reset : OUT STD_LOGIC; \n\
    rx_enable : OUT STD_LOGIC; \n\
    rx_axis_mac_tdata : OUT STD_LOGIC_VECTOR(7 DOWNTO 0); \n\
    rx_axis_mac_tvalid : OUT STD_LOGIC; \n\
    rx_axis_mac_tlast : OUT STD_LOGIC; \n\
    rx_axis_mac_tuser : OUT STD_LOGIC; \n\
    tx_ifg_delay : IN STD_LOGIC_VECTOR(7 DOWNTO 0); \n\
    tx_statistics_vector : OUT STD_LOGIC_VECTOR(31 DOWNTO 0); \n\
    tx_statistics_valid : OUT STD_LOGIC; \n\
    tx_mac_aclk : OUT STD_LOGIC; \n\
    tx_reset : OUT STD_LOGIC; \n\
    tx_enable : OUT STD_LOGIC; \n\
    tx_axis_mac_tdata : IN STD_LOGIC_VECTOR(7 DOWNTO 0); \n\
    tx_axis_mac_tvalid : IN STD_LOGIC; \n\
    tx_axis_mac_tlast : IN STD_LOGIC; \n\
    tx_axis_mac_tuser : IN STD_LOGIC_VECTOR(0 DOWNTO 0); \n\
    tx_axis_mac_tready : OUT STD_LOGIC; \n\
    pause_req : IN STD_LOGIC; \n\
    pause_val : IN STD_LOGIC_VECTOR(15 DOWNTO 0); \n\
    speedis100 : OUT STD_LOGIC; \n\
    speedis10100 : OUT STD_LOGIC; \n\
    mii_tx_clk : IN STD_LOGIC; \n\
    mii_txd : OUT STD_LOGIC_VECTOR(3 DOWNTO 0); \n\
    mii_tx_en : OUT STD_LOGIC; \n\
    mii_tx_er : OUT STD_LOGIC; \n\
    mii_rxd : IN STD_LOGIC_VECTOR(3 DOWNTO 0); \n\
    mii_rx_dv : IN STD_LOGIC; \n\
    mii_rx_er : IN STD_LOGIC; \n\
    mii_rx_clk : IN STD_LOGIC; \n\
    rx_configuration_vector : IN STD_LOGIC_VECTOR(79 DOWNTO 0); \n\
    tx_configuration_vector : IN STD_LOGIC_VECTOR(79 DOWNTO 0) \n\
  ); \n\
  END COMPONENT; \n\
  signal rx_axis_mac_tvalid : STD_LOGIC; \n\
  begin \n\
  inst : tri_mode_ethernet_mac_0 \n\
  PORT MAP ( \n\
    glbl_rstn => inputs.glbl_rstn(0), \n\
    rx_axi_rstn => inputs.rx.axi_rstn(0), \n\
    tx_axi_rstn => inputs.tx.axi_rstn(0), \n\
    unsigned(rx_statistics_vector) => return_output.rx.statistics_vector, \n\
    rx_statistics_valid => return_output.rx.statistics_valid(0), \n\
    rx_mac_aclk => return_output.rx.mac_aclk(0), \n\
    rx_reset => return_output.rx.reset(0), \n\
    rx_enable => return_output.rx.enable(0), \n\
    unsigned(rx_axis_mac_tdata) => return_output.rx.axis_mac.data.tdata(0), \n\
    rx_axis_mac_tvalid => rx_axis_mac_tvalid, \n\
    rx_axis_mac_tlast => return_output.rx.axis_mac.data.tlast(0), \n\
    rx_axis_mac_tuser => open, \n\
    tx_ifg_delay => std_logic_vector(inputs.tx.ifg_delay), \n\
    unsigned(tx_statistics_vector) => return_output.tx.statistics_vector, \n\
    tx_statistics_valid => return_output.tx.statistics_valid(0), \n\
    tx_mac_aclk => return_output.tx.mac_aclk(0), \n\
    tx_reset => return_output.tx.reset(0), \n\
    tx_enable => return_output.tx.enable(0), \n\
    tx_axis_mac_tdata => std_logic_vector(inputs.tx.axis_mac.data.tdata(0)), \n\
    tx_axis_mac_tvalid => inputs.tx.axis_mac.valid(0), \n\
    tx_axis_mac_tlast => inputs.tx.axis_mac.data.tlast(0), \n\
    tx_axis_mac_tuser(0) => '0', \n\
    tx_axis_mac_tready => return_output.tx.axis_mac_ready(0), \n\
    pause_req => inputs.rx.pause_req(0), \n\
    pause_val => std_logic_vector(inputs.rx.pause_val), \n\
    speedis100 => return_output.speedis100(0), \n\
    speedis10100 => return_output.speedis10100(0), \n\
    mii_tx_clk => inputs.tx.mii_clk(0), \n\
    unsigned(mii_txd) => return_output.tx.mii_d, \n\
    mii_tx_en => return_output.tx.mii_en(0), \n\
    mii_tx_er => return_output.tx.mii_er(0), \n\
    mii_rxd => std_logic_vector(inputs.rx.mii_d), \n\
    mii_rx_dv => inputs.rx.mii_dv(0), \n\
    mii_rx_er => inputs.rx.mii_er(0), \n\
    mii_rx_clk => inputs.rx.mii_clk(0), \n\
    rx_configuration_vector => std_logic_vector(inputs.rx.configuration_vector), \n\
    tx_configuration_vector => std_logic_vector(inputs.tx.configuration_vector) \n\
  ); \n\
  return_output.rx.axis_mac.valid(0) <= rx_axis_mac_tvalid; \n\
  return_output.rx.axis_mac.data.tkeep(0)(0) <= rx_axis_mac_tvalid; \n\
  ");
}


// Internal user facing wire types
// RX
typedef struct xil_temac_to_rx_t
{
  // RX data
  stream(axis8_t) rx_axis_mac;
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
  stream(axis8_t) tx_axis_mac;
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

