// Devices attached to the CPU

// Simple clock for software wait()
#include "../../clock/hardware/clock.c"

// I2S RX + TX code
//#include "../../i2s/hardware/i2s.c"
// Instead get I2S samples over ethernet (from other dev board)
#include "../../eth_to_i2s/eth_to_i2s.c"

// Hardware for doing the full FFT
#include "../../fft/hardware/fft.c"

// DVP
#include "../../dvp/hardware/dvp.c"

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
