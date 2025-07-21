#include "uintN_t.h"
#include "compiler.h"

// See pico-ice-sdk/rtl/pico_ice.pcf
#pragma PART "ICE40UP5K-SG48"
// Get clock rate constant PLL_CLK_MHZ from header written by make flow
#include "../pipelinec_makefile_config.h"
// By default PipelineC names clock ports with the rate included
// ex. clk_12p0
// Override this behavior by creating an input with a constant name
// and telling the tool that input signal is a clock of specific rate
DECL_INPUT(uint1_t, pll_clk)
CLK_MHZ(pll_clk, PLL_CLK_MHZ)
DECL_INPUT(uint1_t, pll_locked)

// Configure IO direction for each pin used

// I2S PMOD on PMOD1
/*
tx_mclk  PMOD1 a o1
tx_lrck  PMOD1 a o2
tx_sclk  PMOD1 a o3
tx_data  PMOD1 a o4
rx_mclk  PMOD1 b o1
rx_lrck  PMOD1 b o2
rx_sclk  PMOD1 b o3
rx_data  PMOD1 b i4
*/
#define PMOD_1A_O1
#define I2S_TX_MCLK_WIRE pmod_1a_o1
#define PMOD_1A_O2
#define I2S_TX_LRCK_WIRE pmod_1a_o2
#define PMOD_1A_O3
#define I2S_TX_SCLK_WIRE pmod_1a_o3
#define PMOD_1A_O4
#define I2S_TX_DATA_WIRE pmod_1a_o4
#define PMOD_1B_O1
#define I2S_RX_MCLK_WIRE pmod_1b_o1
#define PMOD_1B_O2
#define I2S_RX_LRCK_WIRE pmod_1b_o2
#define PMOD_1B_O3
#define I2S_RX_SCLK_WIRE pmod_1b_o3
#define PMOD_1B_I4
#define I2S_RX_DATA_WIRE pmod_1b_i4
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
#ifdef BOARD_PICO
#include "board/pico_ice.h"
#elif defined(BOARD_PICO2)
#include "board/pico2_ice.h"
#else
#warning "Unknown board?"
#endif
#include "i2s/i2s_regs.c"
#include "net/rmii_wires.c"


// Want 32b aligned type to transmit
#include "i2s/i2s_32b.h"
// But will be transmitted via 8b axis
#include "axi/axis.h"
// I2S MAC to connect to pmod io regs
#include "i2s/i2s_mac.c"

// Func for converting 32b I2S samples to 8b AXIS
type_to_axis(i2s_to_8b_axis, i2s_sample_in_mem_t, 8)

// Global FIFO for moving samples (as 8b AXIS) from i2s receive to eth transmit
#include "global_fifo.h"
GLOBAL_STREAM_FIFO(axis8_t, i2s_rx_to_eth_tx_fifo, 4)

// I2S MAC Loopback
MAIN_MHZ(i2s_main, I2S_MCLK_MHZ)
void i2s_main()
{
  // Send and receive i2s sample streams via I2S MAC

  // Read I2S PMOD inputs
  i2s_to_app_t from_i2s;
  from_i2s.rx_data = i2s_rx_data;
  
  // Instance of I2S MAC
  uint1_t i2s_reset_n = pll_locked; // Needed?
  //  RX Data+Valid,Ready handshake
  uint1_t mac_rx_samples_ready;
  #pragma FEEDBACK mac_rx_samples_ready
  //  TX Ready,Data+Valid handshake
  stream(i2s_samples_t) mac_tx_samples;
  // NO TX FOR NOW #pragma FEEDBACK mac_tx_samples
  i2s_mac_t mac = i2s_mac(i2s_reset_n, 
    mac_rx_samples_ready, 
    mac_tx_samples, 
    from_i2s
  );

  // Write I2S PMOD outputs
  i2s_tx_mclk = pll_clk; // i2s_mclk;
  i2s_tx_lrck = mac.to_i2s.tx_lrck;
  i2s_tx_sclk = mac.to_i2s.tx_sclk;
  i2s_tx_data = mac.to_i2s.tx_data;
  i2s_rx_mclk = pll_clk; // i2s_mclk;
  i2s_rx_lrck = mac.to_i2s.rx_lrck;
  i2s_rx_sclk = mac.to_i2s.rx_sclk;

  // Convert to 32b aligned data type
  i2s_sample_in_mem_t sample_in_mem = i2s_samples_in_mem(mac.rx.samples.data);

  // Convert to 8b AXIS, connected to FIFO
  i2s_to_8b_axis_t to_axis = i2s_to_8b_axis(
    sample_in_mem,
    mac.rx.samples.valid,
    i2s_rx_to_eth_tx_fifo_in_ready
  );
  mac_rx_samples_ready = to_axis.input_data_ready; // FEEDBACK
  i2s_rx_to_eth_tx_fifo_in = to_axis.payload;
}

// Include ethernet media access controller configured to use RMII wires and 8b AXIS
// with enabled clock crossing fifos (with skid buffers)
#define RMII_ETH_MAC_RX_SKID_IN_FIFO_DEPTH 4
#define RMII_ETH_MAC_TX_SKID_OUT_FIFO_DEPTH 4
#include "net/rmii_eth_mac.c"

// Include logic for parsing/building ethernet frames (8b AXIS)
#include "net/eth_8.h"
// MAC address info we want the fpga to have (shared with software)
#include "examples/net/fpga_mac.h"

// Structured as separate RX and TX MAINs
// since typical to have different clocks for RX and TX
// (only one clock in this example though, could write as one MAIN)

/* NO ETH RX FOR NOW
MAIN_MHZ(eth_rx_main, PLL_CLK_MHZ)
void eth_rx_main()
{
}
*/

MAIN_MHZ(eth_tx_main, PLL_CLK_MHZ)
void eth_tx_main()
{ 
  // Wire up the ETH frame to send
  stream(eth8_frame_t) frame;
  // Header hard coded
  frame.data.header.dst_mac = FPGA_MAC; // To other FPGA
  frame.data.header.src_mac = 0; // Source not important
  frame.data.header.ethertype = 0xFFFF;
  // Payload is the i2s rx data from FIFO
  frame.data.payload = i2s_rx_to_eth_tx_fifo_out.data;
  frame.valid = i2s_rx_to_eth_tx_fifo_out.valid;
  
  // The tx 'building' module, connected to TX MAC
  eth_8_tx_t eth_tx = eth_8_tx(frame, eth_tx_mac_input_ready);
  i2s_rx_to_eth_tx_fifo_out_ready = eth_tx.frame_ready;
  eth_tx_mac_axis_in = eth_tx.mac_axis;
}

// Santy check RMII clock is working with blinking LED
MAIN_MHZ(blinky_main, RMII_CLK_MHZ)
void blinky_main(){
  static uint25_t counter;
  led_r = 1;
  led_g = 1;
  led_b = counter >> 24;
  counter += 1;
}
