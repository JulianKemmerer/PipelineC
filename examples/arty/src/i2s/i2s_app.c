#include "compiler.h" // For MAIN_MHZ pragma specifying clock rate
#include "uintN_t.h"
#include "arrays.h"

// LEDs for debug
#include "../leds/leds.c"
// Switches to toggle effects on and off
#include "../switches/switches.c"

// Include I2S 'media access controller' (PMOD+clocking+de/serializer logic)
// Exposes globally visible RX and TX stream wires
#include "i2s_mac.c"

// Delay effect
#include "../audio/delay.c"

// Distortion effect
#include "../audio/distortion.c"

// Autopipelineable stateless audio stream effects processing pipeline
i2s_samples_s effects_chain(uint1_t reset_n, i2s_samples_s in_samples)
{
  // Delay effect
  i2s_samples_s samples_w_delay = delay(reset_n, in_samples);
  
  // Distortion effect
  i2s_samples_s samples_w_distortion = distortion(samples_w_delay); //in_samples);
  
  // "Volume effect", cut effects volume in half w/ switches
  i2s_samples_s samples_w_effects = samples_w_distortion;
  uint4_t sw;
  WIRE_READ(uint4_t, sw, switches)
  if(uint4_1_1(sw))
  {
    samples_w_effects.samples.l_data.qmn = samples_w_effects.samples.l_data.qmn >> 1;
    samples_w_effects.samples.r_data.qmn = samples_w_effects.samples.r_data.qmn >> 1;
  }
  if(uint4_2_2(sw))
  {
    samples_w_effects.samples.l_data.qmn = samples_w_effects.samples.l_data.qmn >> 1;
    samples_w_effects.samples.r_data.qmn = samples_w_effects.samples.r_data.qmn >> 1;
  }
  if(uint4_3_3(sw))
  {
    samples_w_effects.samples.l_data.qmn = samples_w_effects.samples.l_data.qmn >> 1;
    samples_w_effects.samples.r_data.qmn = samples_w_effects.samples.r_data.qmn >> 1;
  }
  
  // Use switch0 to control, 1=effects on
  // Connect output
  i2s_samples_s out_samples;
  if(uint4_0_0(sw))
  {
    out_samples = samples_w_effects;
  }
  else
  {
    out_samples = in_samples;
  }
  
  return out_samples;
}

// Stateful status, output is LEDs
void app_status(uint1_t reset_n, uint1_t tx_samples_valid, uint1_t tx_samples_ready)
{
  // Debug reg to light up leds if overflow occurs
  static uint1_t overflow;
  // Light up LEDs 0-3 with overflow indicator bit
  WIRE_WRITE(uint4_t, leds, uint1_4(overflow))
  // Detect overflow
  if(tx_samples_valid & !tx_samples_ready)
  {
    overflow = 1;
  }
  // Reset registers
  if(!reset_n)
  {
    overflow = 0;
  }
}

// Send audio through an effects chain
#pragma MAIN app
void app(uint1_t reset_n)
{
  // Read wires from I2S mac
  i2s_mac_rx_to_app_t from_rx_mac;
  WIRE_READ(i2s_mac_rx_to_app_t, from_rx_mac, i2s_mac_rx_to_app)
  i2s_mac_tx_to_app_t from_tx_mac;
  WIRE_READ(i2s_mac_tx_to_app_t, from_tx_mac, i2s_mac_tx_to_app)
  
  // Received samples
  i2s_samples_s rx_samples = from_rx_mac.samples;
  // Signal always ready draining through effects chain, checking overflow in status
  uint1_t rx_samples_ready = 1;
  
  // Send through effects chain
  i2s_samples_s samples_w_effects = effects_chain(reset_n, rx_samples);
  
  // Samples to transmit
  i2s_samples_s tx_samples = samples_w_effects;
  
  // Write wires to I2S mac
  app_to_i2s_mac_tx_t to_tx_mac;
  to_tx_mac.samples = tx_samples;
  to_tx_mac.reset_n = reset_n;
  WIRE_WRITE(app_to_i2s_mac_tx_t, app_to_i2s_mac_tx, to_tx_mac)
  app_to_i2s_mac_rx_t to_rx_mac;
  to_rx_mac.samples_ready = rx_samples_ready;
  to_rx_mac.reset_n = reset_n;
  WIRE_WRITE(app_to_i2s_mac_rx_t, app_to_i2s_mac_rx, to_rx_mac)

  // Control+status logic is stateful (ex. overflow bit)
  // and is kept separate from this stateless autopipelineable function
  app_status(reset_n, to_tx_mac.samples.valid, from_tx_mac.samples_ready);
}
