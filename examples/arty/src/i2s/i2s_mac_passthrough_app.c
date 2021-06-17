#include "wire.h"
#include "uintN_t.h"
#include "arrays.h"
#include "compiler.h"

// LEDs for debug
#include "../leds/leds.c"

// Include I2S 'media access controller' (PMOD+de/serializer logic)
#include "i2s_mac.c"

// Small buffered stream loopback
MAIN_MHZ(app, I2S_MCLK_MHZ)
void app(uint1_t reset_n)
{
  // Register holding sample stream to output, previously received samples
  static i2s_samples_s tx_samples;
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Signal ready for RX if TX output reg is empty
  uint1_t rx_samples_ready = !tx_samples.valid;
  
  // Send and receive sample streams
  i2s_mac_t mac = i2s_mac(reset_n, rx_samples_ready, tx_samples);
  
  // TX being ready for samples clears buffer
  if(mac.tx.samples_ready)
  {
    tx_samples.valid = 0;
  }
  // Loopback received samples into output register if ready
  if(rx_samples_ready)
  {
    tx_samples = mac.rx.samples;
  }
  
  // Detect overflow 
  WIRE_WRITE(uint4_t, leds, uint1_4(overflow)) // Light up LEDs 0-3 if overflow
  if(mac.rx.overflow)
  {
    overflow = 1;
  }
  
  // Reset registers
  if(!reset_n)
  {
    tx_samples.valid = 0;
    overflow = 0;
  }
}
