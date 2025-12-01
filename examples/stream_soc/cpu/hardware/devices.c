// Devices attached to the CPU

// TODO group collections of includes into larger logical devices?

// Simple clock for software wait()
#include "../../clock/hardware/clock.c"

// DDR memory controller IO and shared AXI bus
#include "../../ddr/hardware/ddr.c"
#include "../../shared_ddr/hardware/shared_ddr.c"

// VGA display from frame buffer in DDR
#include "../../vga/hardware/vga.c"

// I2S RX + TX code
//#include "../../i2s/hardware/i2s.c"
// Instead get I2S samples over ethernet (from other dev board)
#include "../../eth_to_i2s/eth_to_i2s.c"

// Hardware for doing the full FFT power spectrum
#define FFT_CLK_MHZ 110.0
#define FFT_CLK_2X_MHZ 220.0
#include "../../fft/hardware/fft_2pt_2x_clk.c"
#include "../../power/hardware/power.c"

// OV2640 SCCB+DVP camera
#include "../../cam/ov2640/hardware/device.c"
// TODO include video/crop,scale,pos

// Devices attached to the CPU interconnected in a dataflow network
// Different dataflow MAINs are needed for different clock domains

#pragma MAIN i2s_dataflow
void i2s_dataflow()
{
  // TODO bytes into byte-to-samples eth to i2c module

  // For now simple dataflow
  // RX audio samples coming out of the I2S block
  // are connected to the FFT block samples input
  samples_fifo_in = i2s_rx_samples_monitor_stream;
  // No ready, just overflows
}

#pragma MAIN fft_dataflow
void fft_dataflow()
{
  // FFT output into power computer pipeline
  sample_power_pipeline_in = output_fifo_out;
  output_fifo_out_ready = sample_power_pipeline_in_ready;
}

// TODO pixels from DVP into video processing modules
