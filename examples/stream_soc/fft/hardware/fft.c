// FFT Device
// Includes FFT hardware and glue to SoC
#include "uintN_t.h"
#include "arrays.h"
#include "stream/stream.h"
#include "stream/serializer.h"
#include "stream/deserializer.h"
#include "axi/axis.h"

// Library wrapping AXI bus
// https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
//#include "examples/shared_resource_bus/axi_shared_bus.h"
#include "examples/shared_resource_bus/axi_ddr/axi_xil_mem.c" // TODO move axi_ddr into stream_soc dir

// The core FFT hardware
#define FFT_CLK_MHZ 120.0
#define FFT_CLK_2X_MHZ 240.0
#include "fft_2pt_2x_clk.c"

// Connect I2S samples stream into samples fifo for FFT here
// (little bit of glue in the I2S clock domain)
#pragma MAIN i2s_to_fft_connect
#pragma FUNC_WIRES i2s_to_fft_connect
void i2s_to_fft_connect(){
  samples_fifo_in = i2s_rx_samples_monitor_stream;
}

// FFT outputs written to DDR

// Declare module to convert FFT out stream to u32 stream for writing to DDR
// (have to use raw base type name ci32_t, not macro fft_out_t)
#include "ci32_t_bytes_t.h" // Auto gen funcs casting ci32_t to-from byte array
type_byte_serializer(fft_out_to_bytes, ci32_t, sizeof(uint32_t))

#pragma MAIN fft_to_ddr_connect
void fft_to_ddr_connect()
{
  // Wire fft output 'output_fifo' stream into AXI writes

  // Convert FFT out stream to u32 stream for writing to DDR
  stream(uint32_t) fft_out_u32;
  uint1_t ready_for_fft_out_u32;
  #pragma FEEDBACK ready_for_fft_out_u32
  fft_out_to_bytes_t u32_from_fft_out = fft_out_to_bytes(
    output_fifo_out.data, // Input stream of FFT output data
    output_fifo_out.valid,
    ready_for_fft_out_u32 // Ready for output stream
  );
  output_fifo_out_ready = u32_from_fft_out.in_data_ready;
  fft_out_u32.data = uint8_array4_le(u32_from_fft_out.out_data);
  // = u32_from_fft_out.last; // TODO packets?
  fft_out_u32.valid = u32_from_fft_out.valid; // Valid output stream

  // Fixed single output buffer for now TODO use multiple descriptors
  stream(axi_descriptor_t) to_write_descriptor;
  to_write_descriptor.data.addr = FFT_OUT_AXI0_ADDR; // Address in DDR AXI0 
  to_write_descriptor.data.num_words = (NFFT*sizeof(fft_out_t))/sizeof(uint32_t); // Number of words to write
  to_write_descriptor.valid = 1; // Valid descriptor
  
  // FFT outputs written to AXI mem
  uint1_t ready_for_descriptors_written = 1; // Always ready, not using this output stream
  axi_stream_to_writes_t to_axi_wr = u32_stream_to_axi_writes(
    to_write_descriptor, // Input stream of descriptors to write
    fft_out_u32, // Input data stream to write
    ready_for_descriptors_written, // Ready for output stream of descriptors written
    dev_to_host(axi_xil_mem, cpu).write // Inputs for write side of AXI bus
  );
  // UNUSED to_axi_wr.descriptors_out_stream;
  // UNUSED to_axi_wr.ready_for_descriptors_in;
  ready_for_fft_out_u32 = to_axi_wr.ready_for_data_stream; // FEEDBACK
  host_to_dev(axi_xil_mem, cpu).write = to_axi_wr.to_dev; // Outputs for write side of AXI bus  
}