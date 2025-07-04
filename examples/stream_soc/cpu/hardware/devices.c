// Devices attached to the CPU

// I2S RX + TX code
#include "../../i2s/hardware/i2s.c"

// Hardware for doing the full FFT
#include "../../fft/hardware/fft.c"

// Devices attached to the CPU interconnected in a dataflow network
#pragma MAIN dataflow
void dataflow()
{
  // For now simple dataflow
  // RX audio samples coming out of the I2S block
  // are connected to the FFT block samples input
  samples_fifo_in = i2s_rx_samples_monitor_stream;
  // No ready, just overflows
}