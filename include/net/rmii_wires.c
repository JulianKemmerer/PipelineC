// RMII wires instance like for LAN8720
// (does not use mdio or mdc)

// Declare the ETH clock
#define RMII_CLK_MHZ 50.0
uint1_t rmii_clk;
CLK_MHZ(rmii_clk, RMII_CLK_MHZ)

// Global wires for users
uint1_t rmii_tx_en; // Output
uint2_t rmii_tx; // Output
uint1_t rmii_crs; // Input
uint2_t rmii_rx; // Input

// Connect individual top level bits to global wires
MAIN_MHZ(rmii_connect, RMII_CLK_MHZ)
void rmii_connect(){
  rmii_clk = RMII_CLK_WIRE;
  RMII_TX_EN_WIRE = rmii_tx_en;
  RMII_TX0_WIRE = rmii_tx(0);
  RMII_TX1_WIRE = rmii_tx(1);
  rmii_crs = RMII_CRS_WIRE;
  rmii_rx = uint1_uint1(RMII_RX1_WIRE, RMII_RX0_WIRE);
}
