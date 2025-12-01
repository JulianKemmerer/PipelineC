// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"
// Globally visible AXI bus for this module
axi_shared_bus_t_dev_to_host_t power_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t power_axi_host_to_dev;

// Connect Power device to AXI bus (in CPU clock domain)
#pragma MAIN power_axi_connect
void power_axi_connect(){
  host_to_dev(axi_xil_mem, cpu) = power_axi_host_to_dev;
  power_axi_host_from_dev = dev_to_host(axi_xil_mem, cpu);
}

// Instance of pipeline for computing power from FFT output
#include "../software/power.h"
DECL_STREAM_TYPE(fft_out_t)
DECL_STREAM_TYPE(fft_data_t)
GLOBAL_VALID_READY_PIPELINE_INST(sample_power_pipeline, fft_data_t, sample_power, fft_out_t, 16)

// Power outputs written to DDR

// Declare module to convert power out stream to u32 stream for writing to DDR
// (have to use raw base type name int32_t, not macro power_data_t)
#include "int32_t_bytes_t.h" // Auto gen funcs casting to-from byte array
type_byte_serializer(out_to_bytes, int32_t, sizeof(uint32_t))

// Globally visible input stream of descriptors to write
stream(axi_descriptor_t) power_in_desc_to_write;
uint1_t power_in_desc_to_write_ready;

// Globally visible stream of power output descriptors
stream(axi_descriptor_t) power_out_desc_written;
uint1_t power_out_desc_written_ready;

#pragma MAIN power_to_ddr_connect
void power_to_ddr_connect()
{
  // Wire power output stream into AXI writes

  // Convert power out stream to u32 stream for writing to DDR
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
  
  // Power outputs written to AXI mem
  axi_stream_to_writes_t to_axi_wr = u32_stream_to_axi_writes(
    power_in_desc_to_write, // Input stream of descriptors to write
    out_as_u32, // Input data stream to write
    power_out_desc_written_ready, // Ready for output stream of descriptors written
    power_axi_host_from_dev.write // Inputs for write side of AXI bus
  );
  power_in_desc_to_write_ready = to_axi_wr.ready_for_descriptors_in;
  power_out_desc_written = to_axi_wr.descriptors_out_stream;
  ready_for_out_as_u32 = to_axi_wr.ready_for_data_stream; // FEEDBACK
  power_axi_host_to_dev.write = to_axi_wr.to_dev; // Outputs for write side of AXI bus  
}