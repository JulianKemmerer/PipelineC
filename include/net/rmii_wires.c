// RMII wires instance like for LAN8720
// (does not use mdio or mdc)

// Declare the ETH clock
#define RMII_CLK_MHZ 50.0
uint1_t rmii_clk;
CLK_MHZ(rmii_clk, RMII_CLK_MHZ)

// Global wires for users
uint2_t rmii_tx; // Output
uint1_t rmii_tx_en; // Output
uint2_t rmii_rx; // Input
uint1_t rmii_crs_dv; // Input

// Connect individual top level bits to global wires
MAIN_MHZ(rmii_connect, RMII_CLK_MHZ)
#pragma FUNC_WIRES rmii_connect
void rmii_connect(){
  rmii_clk = RMII_CLK_WIRE; // No reg on clock signal

  static uint2_t rmii_tx_reg;
  RMII_TX0_WIRE = rmii_tx_reg(0);
  RMII_TX1_WIRE = rmii_tx_reg(1);
  rmii_tx_reg = rmii_tx;

  static uint1_t rmii_tx_en_reg;
  RMII_TX_EN_WIRE = rmii_tx_en_reg;
  rmii_tx_en_reg = rmii_tx_en;

  static uint2_t rmii_rx_reg;
  rmii_rx = rmii_rx_reg;
  rmii_rx_reg = uint1_uint1(RMII_RX1_WIRE, RMII_RX0_WIRE);

  static uint1_t rmii_crs_dv_reg;
  rmii_crs_dv = rmii_crs_dv_reg;
  rmii_crs_dv_reg = RMII_CRS_DV_WIRE;
}

#ifdef RMII_WIRES_DEBUG
#pragma FUNC_MARK_DEBUG rmii_wires_debug
#pragma FUNC_WIRES rmii_wires_debug
#pragma MAIN rmii_wires_debug
void rmii_wires_debug(){
  static uint2_t rmii_tx_reg;
  static uint1_t rmii_tx_en_reg;
  static uint2_t rmii_rx_reg;
  static uint1_t rmii_crs_dv_reg;
  rmii_tx_reg = rmii_tx;
  rmii_tx_en_reg = rmii_tx_en;
  rmii_rx_reg = rmii_rx;
  rmii_crs_dv_reg = rmii_crs_dv;
}
#endif