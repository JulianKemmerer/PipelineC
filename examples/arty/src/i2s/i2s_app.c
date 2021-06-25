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

// Autopipelineable stateless audio stream effects processing
i2s_samples_s effects_chain(uint1_t reset_n, i2s_samples_s in_samples)
{
  // Delay effect
  delay_t d = delay(reset_n, in_samples, 1);
  
  // Connect output
  i2s_samples_s out_samples;
  out_samples = d.out_samples;
  return out_samples;
}

// Send audio through distortion and delay
MAIN_MHZ(app, I2S_MCLK_MHZ)
void app(uint1_t reset_n)
{
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  
  // Transmit data
  static i2s_samples_s tx_samples;
  
  // Send and receive sample streams using I2S MAC
  // Effects chain, where rx is going, is assumed always ready for samples
  // (overflow detected in tx_samples stream output from effects)
  uint1_t rx_samples_ready = 1;
  i2s_mac_t mac = i2s_mac(reset_n, rx_samples_ready, tx_samples);
  
  // Light up LEDs 0-3 with overflow indicator bit
  WIRE_WRITE(uint4_t, leds, uint1_4(overflow))
  // Detect overflow
  if(tx_samples.valid & !mac.tx.samples_ready)
  {
    overflow = 1;
  }
  
  // Send RX data through effects chain
  i2s_samples_s samples_w_effects = effects_chain(reset_n, mac.rx.samples);
    
  // Save samples w effects for next iter transmit
  tx_samples = samples_w_effects;  
  
  // Reset registers
  if(!reset_n)
  {
    overflow = 0;
  }
}


