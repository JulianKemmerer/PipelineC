#include "compiler.h" // For MAIN_MHZ pragma specifying clock rate
#include "fifo.h" // To store delayed samples
#include "uintN_t.h"

// LEDs for debug
#include "../leds/leds.c"

// Include I2S 'media access controller' (PMOD+clocking+de/serializer logic)
#include "i2s_mac.c"

// Distortion effect
#include "../audio/distortion_func.c"

// Delay effect
#include "../audio/delay.c"

// Send audio through distortion and delay
MAIN_MHZ(app, I2S_MCLK_MHZ)
void app(uint1_t reset_n)
{
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Transmit data
  i2s_samples_s tx_samples;
  #pragma FEEDBACK tx_samples
  // Ready for RX
  uint1_t rx_samples_ready;
  #pragma FEEDBACK rx_samples_ready
  
  // Send and receive sample streams
  i2s_mac_t mac = i2s_mac(reset_n, rx_samples_ready, tx_samples);
  
  // Send RX data through delay
  uint1_t delay_out_ready = mac.tx.samples_ready;
  delay_t d = delay(reset_n, mac.rx.samples, delay_out_ready);
  // Connect feedback
  rx_samples_ready = d.rx_samples_ready;
  // Send delay signal to TX
  tx_samples = d.tx_data;
  
  // Light up LEDs 0-3 with overflow indicator bit
  WIRE_WRITE(uint4_t, leds, uint1_4(overflow))
  // Detect overflow
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
