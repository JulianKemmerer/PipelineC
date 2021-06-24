#include "compiler.h" // For MAIN_MHZ pragma specifying clock rate
#include "fifo.h" // To store delayed samples
#include "uintN_t.h"
#include "arrays.h"

// LEDs for debug
#include "../leds/leds.c"

// Include I2S 'media access controller' (PMOD+de/serializer logic)
#include "i2s_mac.c"

// Delay effect via FIFO
#define DELAY_SAMPLES (44100/2) // half sec, 44.1K samples per 1 sec
// FIFO to use below
FIFO_FWFT(samples_fifo, i2s_samples_t, DELAY_SAMPLES)

// Delay module
typedef struct delay_t{
  i2s_samples_s tx_data;
  uint1_t rx_samples_ready;
}delay_t;
delay_t delay(uint1_t reset_n, i2s_samples_s rx_data, uint1_t tx_samples_ready)
{
  delay_t rv;

  // Passthrough samples by default
  rv.rx_samples_ready = tx_samples_ready;
  rv.tx_data = rx_data;
  
  // Buffer up rx_samples into FIFO
  static uint1_t buffer_reached_full;
  i2s_samples_t fifo_data_in = rx_data.samples;
  // Data written into FIFO as passing through
  uint1_t fifo_wr = rx_data.valid & tx_samples_ready; 
  // Read from fifo as passing through, and after delay reaching full buffer
  uint1_t fifo_rd = rx_data.valid & tx_samples_ready & buffer_reached_full;
  samples_fifo_t fifo = samples_fifo(fifo_rd, fifo_data_in, fifo_wr);
  
  // Combine FIFO output delayed samples with current samples
  // if enough samples buffered up / delayed
  if(fifo.count >= DELAY_SAMPLES)
  {
    buffer_reached_full = 1;
  }
  if(fifo_rd & fifo.data_out_valid)
  {
    rv.tx_data.samples.l_data += fifo.data_out.l_data;
    rv.tx_data.samples.r_data += fifo.data_out.r_data;
  }
  
  if(!reset_n)
  {
    buffer_reached_full = 0;
  }
    
  return rv;
}


// Send audio through delay
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
