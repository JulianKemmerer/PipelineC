// Devices attached to the CPU

// TODO group collections of includes into larger logical devices?

// Simple clock for software wait()
#include "../../clock/hardware/device.c"

// DDR memory controller IO and shared AXI bus
#include "../../ddr/hardware/device.c"
#include "../../shared_ddr/hardware/device.c"

// VGA display from frame buffer in DDR
#include "../../vga/hardware/device.c"

// I2S RX + TX code
//#include "../../i2s/hardware/i2s.c"
// Instead get I2S samples over ethernet (from other dev board)
#include "../../eth_to_i2s/hardware/device.c"

// Hardware for doing the full FFT power spectrum
#define FFT_CLK_MHZ 110.0
#define FFT_CLK_2X_MHZ 220.0
#include "../../fft/hardware/device.c"
#include "../../power/hardware/device.c"

// OV2640 SCCB+DVP camera
#include "../../cam/ov2640/hardware/device.c"
#include "../../video/crop/hardware/device.c"
#include "../../video/scale/hardware/device.c"
#include "../../video/fb_pos/hardware/device.c"

// Basic proto-GPU thing
#include "../../gpu/hardware/device.c"

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

// TODO USE CAMERA PIXELS INPUT TO CROP!
#pragma MAIN video_dataflow
void video_dataflow(){
  // Crop output into scale input
  scale_video_in = crop_video_out;
  crop_video_out_ready = scale_video_in_ready;

  // Scale output into position input
  fb_pos_video_in = scale_video_out;
  scale_video_out_ready = fb_pos_video_in_ready;
}
