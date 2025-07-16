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
// UART
//#define DEFAULT_PI_UART
//#define UART_CLK_MHZ PLL_CLK_MHZ
//#define UART_BAUD 115200
#ifdef BOARD_PICO
#include "board/pico_ice.h"
#elif defined(BOARD_PICO2)
#include "board/pico2_ice.h"
#else
#warning "Unknown board?"
#endif
#include "i2s/i2s_regs.c"
#include "i2s/i2s_mac.c"
#include "net/rmii_wires.c"
//#include "uart/uart_mac.c"


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
  #pragma FEEDBACK mac_tx_samples
  i2s_mac_t mac = i2s_mac(i2s_reset_n, 
    mac_rx_samples_ready, 
    mac_tx_samples, 
    from_i2s
  );
  // Loopback
  mac_tx_samples = mac.rx.samples;
  mac_rx_samples_ready = mac.tx.samples_ready;

  // Write I2S PMOD outputs
  i2s_tx_mclk = pll_clk; // i2s_mclk;
  i2s_tx_lrck = mac.to_i2s.tx_lrck;
  i2s_tx_sclk = mac.to_i2s.tx_sclk;
  i2s_tx_data = mac.to_i2s.tx_data;
  i2s_rx_mclk = pll_clk; // i2s_mclk;
  i2s_rx_lrck = mac.to_i2s.rx_lrck;
  i2s_rx_sclk = mac.to_i2s.rx_sclk;

  /* 
  // Received samples to u32 stream
  //  u32 Data+Valid,Ready handshake
  stream(uint32_t) rx_u32_stream;
  uint1_t rx_u32_stream_ready;
  #pragma FEEDBACK rx_u32_stream_ready
  samples_to_u32_t rx_to_u32 = samples_to_u32(
    mac_rx_samples, rx_u32_stream_ready
  );
  mac_rx_samples_ready = rx_to_u32.ready_for_samples; // FEEDBACK
  rx_u32_stream = rx_to_u32.out_stream;
  */
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

// Instead of loopback, can wire up a demo of doing some work
#define ETH_DEMO_IS_WORK_PIPELINE
#ifdef ETH_DEMO_IS_WORK_PIPELINE
// Include definition of work to compute
#include "examples/net/work.h"
// Global stream pipeline interface looks same as FIFOs
#include "global_func_inst.h"
GLOBAL_VALID_READY_PIPELINE_INST(work_pipeline, work_outputs_t, work, work_inputs_t, 4)
// De/serialize 1 byte at a time to/from the types for the work compute
#include "stream/deserializer.h"
#include "stream/serializer.h"
// axis_packet deserialize variant to handle min eth frame size padding on incoming frames
axis_packet_to_type(work_deserialize, 8, work_inputs_t) 
type_byte_serializer(work_serialize, work_outputs_t, 1)
#else
// Loopback structured as separate RX and TX MAINs
// since typical to have different clocks for RX and TX
// (only one clock in this example though, could write as one MAIN)
// Loopback RX to TX with fifos
//  the FIFOs have valid,ready streaming handshake interfaces
GLOBAL_STREAM_FIFO(axis8_t, loopback_payload_fifo, 32) // One to hold the payload data
#endif
// Work demo and regular loopback use headers FIFO
GLOBAL_STREAM_FIFO(eth_header_t, loopback_headers_fifo, 2) // another one to hold the headers

MAIN_MHZ(rx_main, PLL_CLK_MHZ)
void rx_main()
{  
  // Receive the ETH frame
  #ifdef ETH_DEMO_IS_WORK_PIPELINE
  // Eth rx ready if deser+header fifo ready
  uint1_t deser_ready_for_input;
  #pragma FEEDBACK deser_ready_for_input
  uint1_t eth_rx_out_ready = deser_ready_for_input & loopback_headers_fifo_in_ready;
  #else
  // Eth rx ready if payload fifo+header fifo ready
  uint1_t eth_rx_out_ready = loopback_payload_fifo_in_ready & loopback_headers_fifo_in_ready;
  #endif

  // The rx 'parsing' module
  eth_8_rx_t eth_rx = eth_8_rx(eth_rx_mac_axis_out, eth_rx_out_ready);
  stream(eth8_frame_t) frame = eth_rx.frame;
  // Filter out all but matching destination mac frames
  uint1_t mac_match = frame.data.header.dst_mac == FPGA_MAC;

  // Write DVR handshake if mac match
  uint1_t valid_and_ready = frame.valid & eth_rx_out_ready & mac_match;
  #ifdef ETH_DEMO_IS_WORK_PIPELINE
  // Deserialize and connect to work pipeline input
  stream(axis8_t) deser_in_stream;
  deser_in_stream.data = frame.data.payload;
  deser_in_stream.valid = valid_and_ready;
  uint1_t deser_output_ready = work_pipeline_in_ready;
  work_deserialize_t deser = work_deserialize(
    deser_in_stream,
    deser_output_ready
  );
  deser_ready_for_input = deser.packet_ready; // FEEDBACK
  work_pipeline_in.data = deser.data;
  work_pipeline_in.valid = deser.valid;
  #else
  // Frame payload and headers go into separate fifos
  loopback_payload_fifo_in.data = frame.data.payload;
  loopback_payload_fifo_in.valid = valid_and_ready;
  #endif
  // Header only written once at the start of data packet
  loopback_headers_fifo_in.data = frame.data.header;
  loopback_headers_fifo_in.valid = frame.data.start_of_payload & valid_and_ready;
}

MAIN_MHZ(tx_main, PLL_CLK_MHZ)
void tx_main()
{ 
  // Wire up the ETH frame to send
  stream(eth8_frame_t) frame;
  // Header matches what was sent other than SRC+DST macs
  frame.data.header = loopback_headers_fifo_out.data;
  frame.data.header.dst_mac = frame.data.header.src_mac; // Send back to where came from
  frame.data.header.src_mac = FPGA_MAC; // From FPGA

  #ifdef ETH_DEMO_IS_WORK_PIPELINE
  // Serialize results coming out of work pipeline
  uint1_t ser_output_ready;
  #pragma FEEDBACK ser_output_ready
  work_serialize_t ser = work_serialize(
    work_pipeline_out.data,
    work_pipeline_out.valid,
    ser_output_ready
  );
  // Header and serializer payload need to be valid to send
  work_pipeline_out_ready = ser.in_data_ready;
  frame.data.payload.tdata = ser.out_data;
  frame.data.payload.tlast = ser.last;
  frame.valid = ser.valid & loopback_headers_fifo_out.valid;
  #else
  // Header and loopback payload need to be valid to send
  frame.data.payload = loopback_payload_fifo_out.data;
  frame.valid = loopback_payload_fifo_out.valid & loopback_headers_fifo_out.valid;
  #endif

  // The tx 'building' module
  eth_8_tx_t eth_tx = eth_8_tx(frame, eth_tx_mac_input_ready);
  eth_tx_mac_axis_in = eth_tx.mac_axis;
  
  // Read DVR handshake from inputs
  uint1_t valid_and_ready = frame.valid & eth_tx.frame_ready;
  #ifdef ETH_DEMO_IS_WORK_PIPELINE
  // Read payload from serializer if was ready
  ser_output_ready = valid_and_ready; // FEEDBACK
  #else
  // Read payload from fifo if was ready
  loopback_payload_fifo_out_ready = valid_and_ready;
  #endif
  // Read header if was ready at end of packet
  loopback_headers_fifo_out_ready = frame.data.payload.tlast & valid_and_ready;

  /*// Connect to debug probes
  // Why does removing _reg's and using debug signals directly cause more resource use?
  //static payload_debug_t payload_debug_reg;
  //payload_debug = payload_debug_reg;
  //static mac_debug_t mac_debug_reg;
  //mac_debug = mac_debug_reg;
  if(valid_and_ready){
    //mac_debug.mac_lsb = frame.data.header.dst_mac;
    //mac_debug.mac_msb = frame.data.header.dst_mac >> 32;
    ARRAY_1SHIFT_INTO_TOP(payload_debug.tdata, PAYLOAD_DEBUG_SAMPLES, frame.data.payload.tdata[0])
    ARRAY_1SHIFT_INTO_TOP(payload_debug.tlast, PAYLOAD_DEBUG_SAMPLES, frame.data.payload.tlast)
  }*/
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

/*
// UART part of demo
MAIN_MHZ(uart_main, PLL_CLK_MHZ)
void uart_main(){
  // Default loopback connect
  uart_tx_mac_word_in = uart_rx_mac_word_out;
  uart_rx_mac_out_ready = uart_tx_mac_in_ready;

  // Override .data to do case change demo
  char in_char = uart_rx_mac_word_out.data;
  char out_char = in_char;
  uint8_t case_diff = 'a' - 'A';
  if(in_char >= 'a' && in_char <= 'z'){
    out_char = in_char - case_diff;
  }else if(in_char >= 'A' && in_char <= 'Z'){
    out_char = in_char + case_diff;
  }
  uart_tx_mac_word_in.data = out_char;
}
*/