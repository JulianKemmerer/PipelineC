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
    rv.tx_data.samples.l_data = q0_23_add(rv.tx_data.samples.l_data, fifo.data_out.l_data);
    rv.tx_data.samples.r_data = q0_23_add(rv.tx_data.samples.r_data, fifo.data_out.r_data);
  }
  
  if(!reset_n)
  {
    buffer_reached_full = 0;
  }
    
  return rv;
}
