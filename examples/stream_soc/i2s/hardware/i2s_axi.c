#include "uintN_t.h"
#include "wire.h"
#include "uintN_t.h"
#include "arrays.h"
#include "fifo.h"
#include "compiler.h"

// LEDs for debug
#include "leds/leds_port.c"

// Include I2S 'media access controller' (PMOD+de/serializer logic)
#include "i2s/i2s_regs.c"
#include "i2s/i2s_mac.c"

// Logic for converting the samples stream to-from MAC to-from 32b chunks
#include "i2s/i2s_32b.h"

// TODO rename _loopback stuff after removing loopback ...
// Where to put samples for demo?
#ifndef I2S_LOOPBACK_DEMO_SAMPLES_ADDR
#define I2S_LOOPBACK_DEMO_SAMPLES_ADDR 0
#endif
#ifndef I2S_LOOPBACK_DEMO_N_SAMPLES
#define I2S_LOOPBACK_DEMO_N_SAMPLES 64
#endif
#ifndef I2S_LOOPBACK_DEMO_N_DESC
#define I2S_LOOPBACK_DEMO_N_DESC 16 // 16 is good min, since xilinx async fifo min size 16
#endif

// Library wrapping AXI bus
// https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
//#include "/axi/axi_shared_bus.h"
#include "../../shared_ddr/hardware/axi_xil_mem.c"

// Globally visible fifo as input port for I2S RX desc to be written
GLOBAL_STREAM_FIFO(axi_descriptor_t, i2s_rx_desc_to_write_fifo, I2S_LOOPBACK_DEMO_N_DESC)

// Expose external port FIFO wires for reading RX sample descriptors
// as they go through loopback in DDR mem
#ifdef I2S_RX_MONITOR_PORT
GLOBAL_STREAM_FIFO(axi_descriptor_t, i2s_rx_descriptors_monitor_fifo, I2S_LOOPBACK_DEMO_N_DESC)
//  with extra signal to indicate if missed samples
uint1_t i2s_rx_descriptors_out_monitor_overflow;
#pragma ASYNC_WIRE i2s_rx_descriptors_out_monitor_overflow // Disable timing checks
#endif

// Also expose direct stream wires of samples from I2S RX
// for ex. right into FFT hardware
#ifdef I2S_RX_STREAM_MONITOR_PORT
stream(i2s_samples_t) i2s_rx_samples_monitor_stream;
#endif

// AXI loopback
MAIN_MHZ(i2s_loopback_app, I2S_MCLK_MHZ)
void i2s_loopback_app(uint1_t reset_n)
{
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Send and receive i2s sample streams via I2S MAC
  //  RX Data+Valid,Ready handshake
  stream(i2s_samples_t) mac_rx_samples;
  uint1_t mac_rx_samples_ready;
  #pragma FEEDBACK mac_rx_samples_ready
  //  TX Ready,Data+Valid handshake
  //uint1_t mac_tx_samples_ready;
  stream(i2s_samples_t) mac_tx_samples;
  //#pragma FEEDBACK mac_tx_samples

  // Read I2S PMOD inputs
  i2s_to_app_t from_i2s;
  from_i2s.rx_data = i2s_rx_data;
  
  // Instance of I2S MAC
  i2s_mac_t mac = i2s_mac(reset_n, 
    mac_rx_samples_ready, 
    mac_tx_samples, 
    from_i2s
  );
  mac_rx_samples = mac.rx.samples;
  //mac_tx_samples_ready = mac.tx.samples_ready;

  // Write I2S PMOD outputs
  i2s_tx_lrck = mac.to_i2s.tx_lrck;
  i2s_tx_sclk = mac.to_i2s.tx_sclk;
  i2s_tx_data = mac.to_i2s.tx_data;
  i2s_rx_lrck = mac.to_i2s.rx_lrck;
  i2s_rx_sclk = mac.to_i2s.rx_sclk;

  // External stream port for samples
  #ifdef I2S_RX_STREAM_MONITOR_PORT
  i2s_rx_samples_monitor_stream.data = mac_rx_samples.data;
  i2s_rx_samples_monitor_stream.valid = mac_rx_samples.valid & mac_rx_samples_ready;
  #endif 

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

  // Received samples written to AXI mem
  // Stream of rx descriptors in
  // what memory will be written with received samples?
  //  Data+Valid,Ready handshake
  stream(axi_descriptor_t) rx_descriptors_out;
  axi_stream_to_writes_t to_axi_wr = u32_stream_to_axi_writes(
    i2s_rx_desc_to_write_fifo_out, // Input stream of descriptors to write
    rx_u32_stream, // Input data stream to write (from I2S MAC)
    i2s_rx_descriptors_monitor_fifo_in_ready, // Ready for output stream of descriptors written
    dev_to_host(axi_xil_mem, i2s).write // Inputs for write side of AXI bus
  );
  i2s_rx_desc_to_write_fifo_out_ready = to_axi_wr.ready_for_descriptors_in;
  rx_u32_stream_ready = to_axi_wr.ready_for_data_stream; // FEEDBACK
  i2s_rx_descriptors_monitor_fifo_in = to_axi_wr.descriptors_out_stream; // Output stream of written descriptors
  host_to_dev(axi_xil_mem, i2s).write = to_axi_wr.to_dev; // Outputs for write side of AXI bus

  // Xilinx AXI DDR would be here in top to bottom data flow
  
  // UNUSED TX
  /*
  // FIFO holding description of memory locations to read TX samples from
  // Descriptor stream out of read fifo
  //  Data+Valid,Ready handshake
  stream(axi_descriptor_t) rd_descp_fifo_out_stream;
  uint1_t rd_descp_fifo_out_stream_ready;
  #pragma FEEDBACK rd_descp_fifo_out_stream_ready
  desc_fifo_t desc_to_read_fifo_out = desc_fifo(
    rd_descp_fifo_out_stream_ready,
    rx_descriptors_out.data,
    rx_descriptors_out.valid
  );
  rd_descp_fifo_out_stream.data = desc_to_read_fifo_out.data_out;
  rd_descp_fifo_out_stream.valid = desc_to_read_fifo_out.data_out_valid;
  rx_descriptors_out_ready = desc_to_read_fifo_out.data_in_ready; // FEEDBACK

  // Transmit samples read from AXI mem
  // Stream of tx descriptors out
  // what memory was used for transmit, is now available to resue?
  //  Data+Valid,Ready handshake
  stream(axi_descriptor_t) tx_descriptors_out;
  uint1_t tx_descriptors_out_ready;
  #pragma FEEDBACK tx_descriptors_out_ready
  //  u32 Data+Valid,Ready handshake
  stream(uint32_t) tx_u32_stream;
  uint1_t tx_u32_stream_ready;
  #pragma FEEDBACK tx_u32_stream_ready
  axi_reads_to_u32_stream_t from_axi_rd = axi_reads_to_u32_stream(
    rd_descp_fifo_out_stream, // Input stream of descriptors to read
    tx_descriptors_out_ready, // Ready for output stream of descriptors read
    tx_u32_stream_ready, // Ready for output stream of u32 data
    dev_to_host(axi_xil_mem, i2s).read // Inputs for read side of AXI bus
  );
  rd_descp_fifo_out_stream_ready = from_axi_rd.ready_for_descriptors_in; // FEEDBACK
  tx_descriptors_out = from_axi_rd.descriptors_out_stream; // Output stream of read descriptors
  tx_u32_stream = from_axi_rd.data_stream; // Output data stream from reads (to I2S MAC)
  host_to_dev(axi_xil_mem, i2s).read = from_axi_rd.to_dev; // Outputs for read side of AXI bus

  // Feedback descriptors loopback
  wr_desc_fifo_in_stream = tx_descriptors_out; // FEEDBACK
  tx_descriptors_out_ready = wr_desc_fifo_in_stream_ready; // FEEDBACK

  // u32 stream to samples
  u32_to_samples_t tx_from_u32 = u32_to_samples(tx_u32_stream, mac_tx_samples_ready);
  tx_u32_stream_ready = tx_from_u32.ready_for_data_in; // FEEDBACK
  // Feedback samples for transmit
  mac_tx_samples = tx_from_u32.out_stream; // FEEDBACK
  */
  
  /* // Detect overflow 
  leds = uint1_4(overflow); // Light up LEDs 0-3 if overflow
  if(mac.rx.overflow)
  {
    overflow = 1;
  }*/
  
  // Reset registers
  if(!reset_n)
  {
    overflow = 0;
  }
}
