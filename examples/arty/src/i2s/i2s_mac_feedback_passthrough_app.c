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
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Data transmit is feedback output RX data
  i2s_samples_s tx_samples;
  #pragma FEEDBACK tx_samples
  // Ready for RX is feedback output TX ready
  uint1_t rx_samples_ready;
  #pragma FEEDBACK rx_samples_ready
  
  // Send and receive sample streams
  i2s_mac_t mac = i2s_mac(reset_n, rx_samples_ready, tx_samples);
  
  // Connect feedback
  tx_samples = mac.rx.samples;
  rx_samples_ready = mac.tx.samples_ready;
  
  // Detect overflow 
  WIRE_WRITE(uint4_t, leds, uint1_4(overflow)) // Light up LEDs 0-3 if overflow
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
