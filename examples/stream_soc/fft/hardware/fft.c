// FFT Device
// Includes FFT hardware and glue to SoC

#define FFT_CLK_MHZ 120.0
#define FFT_CLK_2X_MHZ 240.0
#include "fft_2pt_2x_clk.c"
// FFT output connected into CPU in memory map below
// Connect I2S samples stream into samples fifo for FFT here
// (little bit of glue in the I2S clock domain)
#pragma MAIN i2s_to_fft_connect
#pragma FUNC_WIRES i2s_to_fft_connect
void i2s_to_fft_connect(){
  samples_fifo_in = i2s_rx_samples_monitor_stream;
}