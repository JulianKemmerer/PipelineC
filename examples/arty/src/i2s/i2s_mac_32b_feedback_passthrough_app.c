#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "wire.h"
#include "uintN_t.h"
#include "arrays.h"
#include "compiler.h"

// LEDs for debug
#include "leds/leds_port.c"

// Include I2S 'media access controller' (PMOD+de/serializer logic)
#include "i2s_mac.c"

// Logic for converting the samples stream to-from MAC to-from 32b chunks
#include "i2s_32b.h"

// Small buffered stream loopback
MAIN_MHZ(app, I2S_MCLK_MHZ)
void app(uint1_t reset_n)
{
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Send and receive sample streams
  stream(i2s_samples_t) mac_tx_samples_in;
  #pragma FEEDBACK mac_tx_samples_in
  uint1_t mac_rx_samples_ready;
  #pragma FEEDBACK mac_rx_samples_ready
  i2s_to_app_t from_i2s = read_i2s_pmod();
  i2s_mac_t mac = i2s_mac(reset_n, mac_rx_samples_ready, mac_tx_samples_in, from_i2s);
  write_i2s_pmod(mac.to_i2s);
  stream(i2s_samples_t) mac_rx_samples_out = mac.rx.samples;

  // Samples to u32 stream
  uint1_t u32_stream_ready;
  #pragma FEEDBACK u32_stream_ready
  samples_to_u32_t to_u32 = samples_to_u32(mac_rx_samples_out, u32_stream_ready);
  mac_rx_samples_ready = to_u32.ready_for_samples;
  // u32 stream to samples
  u32_to_samples_t to_samples = u32_to_samples(to_u32.out_stream, mac.tx.samples_ready);
  u32_stream_ready = to_samples.ready_for_data_in;

  // Feedback samples for transmit
  mac_tx_samples_in = to_samples.out_stream;
  
  // Detect overflow 
  leds = uint1_4(overflow); // Light up LEDs 0-3 if overflow
  if(mac.rx.overflow)
  {
    overflow = 1;
  }
  
  // Reset registers
  if(!reset_n)
  {
    overflow = 0;
  }
}
