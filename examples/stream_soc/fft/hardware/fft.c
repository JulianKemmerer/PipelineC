// FFT Device
// Includes FFT hardware and glue to SoC
#include "uintN_t.h"
#include "arrays.h"
#include "stream/stream.h"
#include "stream/serializer.h"
#include "stream/deserializer.h"
#include "global_func_inst.h"
#include "axi/axis.h"
#include "../software/power.h"

// FFT C code to be instantiated in hardware
#include "../../fft/software/fft.h"

// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"
// Globally visible AXI bus for this module
axi_shared_bus_t_dev_to_host_t fft_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t fft_axi_host_to_dev;

// The core FFT hardware
#define FFT_CLK_MHZ 110.0
#define FFT_CLK_2X_MHZ 220.0
#include "fft_2pt_2x_clk.c"

// Instance of pipeline for computing power from FFT output
DECL_STREAM_TYPE(fft_out_t)
DECL_STREAM_TYPE(fft_data_t)
GLOBAL_VALID_READY_PIPELINE_INST(sample_power_pipeline, fft_data_t, sample_power, fft_out_t, 16)

// Power outputs written to DDR

// Declare module to convert power out stream to u32 stream for writing to DDR
// (have to use raw base type name int32_t, not macro fft_data_t)
#include "int32_t_bytes_t.h" // Auto gen funcs casting to-from byte array
type_byte_serializer(out_to_bytes, int32_t, sizeof(uint32_t))

// Globally visible input stream of descriptors to write
stream(axi_descriptor_t) fft_in_desc_to_write;
uint1_t fft_in_desc_to_write_ready;

// Globally visible stream of FFT output descriptors
stream(axi_descriptor_t) fft_out_desc_written;
uint1_t fft_out_desc_written_ready;

#pragma MAIN fft_to_ddr_connect
void fft_to_ddr_connect()
{
  // FFT output into power computer pipeline
  sample_power_pipeline_in = output_fifo_out;
  output_fifo_out_ready = sample_power_pipeline_in_ready;

  // Wire power output stream into AXI writes

  // Convert FFT out stream to u32 stream for writing to DDR
  stream(uint32_t) out_as_u32;
  uint1_t ready_for_out_as_u32;
  #pragma FEEDBACK ready_for_out_as_u32
  out_to_bytes_t to_u32 = out_to_bytes(
    sample_power_pipeline_out.data, // Input stream of output data
    sample_power_pipeline_out.valid,
    ready_for_out_as_u32 // Ready for output stream
  );
  sample_power_pipeline_out_ready = to_u32.in_data_ready;
  out_as_u32.data = uint8_array4_le(to_u32.out_data);
  // = to_u32.last; // TODO packets?
  out_as_u32.valid = to_u32.valid; // Valid output stream
  
  // FFT outputs written to AXI mem
  axi_stream_to_writes_t to_axi_wr = u32_stream_to_axi_writes(
    fft_in_desc_to_write, // Input stream of descriptors to write
    out_as_u32, // Input data stream to write
    fft_out_desc_written_ready, // Ready for output stream of descriptors written
    fft_axi_host_from_dev.write // Inputs for write side of AXI bus
  );
  fft_in_desc_to_write_ready = to_axi_wr.ready_for_descriptors_in;
  fft_out_desc_written = to_axi_wr.descriptors_out_stream;
  ready_for_out_as_u32 = to_axi_wr.ready_for_data_stream; // FEEDBACK
  fft_axi_host_to_dev.write = to_axi_wr.to_dev; // Outputs for write side of AXI bus  
}