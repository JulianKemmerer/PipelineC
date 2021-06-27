#include "compiler.h" // For MAIN_MHZ pragma specifying clock rate
#include "uintN_t.h"
#include "arrays.h"

// LEDs for debug
#include "../leds/leds.c"
// Switches to toggle effects on and off
#include "../switches/switches.c"

// Include I2S 'media access controller' (PMOD+clocking+de/serializer logic)
#include "i2s_mac.c"

// Delay effect
#include "../audio/delay.c"

// Distortion effect
#include "../audio/distortion.c"

// Autopipelineable stateless audio stream effects processing pipeline
i2s_samples_s effects_chain(uint1_t reset_n, i2s_samples_s in_samples)
{
  // Delay effect
  //i2s_samples_s samples_w_delay = delay(reset_n, in_samples);
  
  // Distortion effect
  i2s_samples_s samples_w_distortion = distortion(in_samples);
  
  /*
  static i2s_samples_s test_buff[1024];
  i2s_samples_s buff_out = test_buff[1023];
  ARRAY_SHIFT_BIT_INTO_BOTTOM(test_buff, 1024, in_samples)
  */
  
  // Connect output
  i2s_samples_s out_samples = samples_w_distortion;
  return out_samples;
}

// Send audio through an effects chain
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
  // (as used w/ static state regs in this func, this wont be pipelined)
  i2s_samples_s samples_w_effects = effects_chain(reset_n, mac.rx.samples);
    
  // Save samples w/without effects for next iter transmit
  // Use switch0 to control, 1=effects on
  uint4_t sw;
  WIRE_READ(uint4_t, sw, switches)
  if(uint4_0_0(sw))
  {
    tx_samples = samples_w_effects;  
  }
  else
  {
    tx_samples = mac.rx.samples;
  }
  
  // Reset registers
  if(!reset_n)
  {
    overflow = 0;
  }
}


