#pragma once
#include "fifo.h" // To store delayed samples
#include "lib/fixed/q0_23.h" // For mono data types
#include "../i2s/i2s_mac.c" // For stereo types

// Delay effect via FIFO
#define DELAY_SAMPLES (44100/2) // half sec, 44.1K samples per 1 sec
// FIFO to use below
FIFO_FWFT(samples_fifo, i2s_samples_t, DELAY_SAMPLES)

// Delay module
i2s_samples_s delay(uint1_t reset_n, i2s_samples_s in_samples)
{
  // Passthrough samples by default
  i2s_samples_s out_samples = in_samples; 
  
  // Buffer up rx_samples into FIFO
  static uint1_t buffer_reached_full;
  i2s_samples_t fifo_data_in = in_samples.samples;
  // Data written into FIFO as passing through
  uint1_t fifo_wr = in_samples.valid; 
  // Read from fifo as passing through, and after delay reaching full buffer
  uint1_t fifo_rd = in_samples.valid & buffer_reached_full;
  samples_fifo_t fifo = samples_fifo(fifo_rd, fifo_data_in, fifo_wr);
  
  // Combine FIFO output delayed samples with current samples
  // if enough samples buffered up / delayed
  if(fifo.count >= DELAY_SAMPLES)
  {
    buffer_reached_full = 1;
  }
  if(fifo_rd & fifo.data_out_valid)
  {
    out_samples.samples.l_data = q0_23_add(rv.out_samples.samples.l_data, fifo.data_out.l_data);
    out_samples.samples.r_data = q0_23_add(rv.out_samples.samples.r_data, fifo.data_out.r_data);
  }
  
  if(!reset_n)
  {
    buffer_reached_full = 0;
  }
    
  return out_samples;
}
