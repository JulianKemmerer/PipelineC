#include <stdint.h>
#include <stdlib.h> 

// TODO organize includes
#include "../../fft/software/fft_types.h"
#include "../../fft/software/power.h"
#include "../../fft/software/draw.h"
// Not doing FFT in software right now but could...
//#include "../fft/software/fft.c"
#include "mem_map.h"
// TODO how to organize the funcs in these headers?
#include "../../i2s/software/i2s.h"
#include "../../fft/software/fft_read.h"

void main() {
  //int count = 0;
  // Clear screen to black
  drawRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT, 0, FB0);
  #ifdef FFT_USE_OMEGA_LUT
  // Init lookup table for FFT
  init_omega_lookup();
  #endif

  // FFT in hardware only needs input samples for final waveform display
  // dont need full NFFT as number of samples, at most FRAME_WIDTH points
  fft_in_t fft_input_samples[FRAME_WIDTH] = {0};
  fft_out_t fft_output[NFFT] = {0};
  fft_data_t fft_output_pwr[N_DRAWN_BINS] = {0};

  // Configure FFT result AXIS sink to write to AXI DDR at specific address
  fft_config_result((fft_out_t*)FFT_OUT_ADDR);

  // Configure chunks of I2S samples to read
  uint32_t i2s_addr = I2S_BUFFS_ADDR;
  for(uint32_t i = 0; i < I2S_N_DESC; i++)
  {
    i2s_rx_enq_write((i2s_sample_in_mem_t*)i2s_addr, NFFT);
    i2s_addr += sizeof(i2s_sample_in_mem_t)*NFFT;
  } 

  while(1){
    *LED = (1<<0);
    
    // Read i2s samples (in DDR3 off chip)
    i2s_sample_in_mem_t* samples_in_dram = NULL;
    int n_samples = 0;
    i2s_read(&samples_in_dram, &n_samples);
    // Copy samples into BRAM DMEM buffer and convert to input type as needed
    for (size_t i = 0; i < FRAME_WIDTH; i++) // Only need to copy as much as will show in draw_waveform FRAME
    {
      // I2S samples are 24b fixed point
      fft_input_samples[i].real = ((samples_in_dram[i].l >> (24-16)) + (samples_in_dram[i].r >> (24-16))) >> 1;
      fft_input_samples[i].imag = 0;
    }
    // Enqueue the buffer to be used for future rx samples writes
    i2s_rx_enq_write(samples_in_dram, n_samples);

    *LED = (1<<1);

    // Read FFT result (in DDR3 off chip mem)
    fft_out_t* fft_out_in_dram;
    fft_read_result(&fft_out_in_dram, &n_samples);
    // Copy fft output into BRAM DMEM buffer // TODO try without copy?
    for (size_t i = 0; i < N_DRAWN_BINS; i++)
    {
      fft_output[i] = fft_out_in_dram[i];
    }
    // Confgure next FFT result output buffer at same place as current
    fft_config_result(fft_out_in_dram); // Or (fft_out_t*)FFT_OUT_ADDR)...
    
    *LED = (1<<2);

    // Compute power
    compute_power(fft_output, fft_output_pwr, N_DRAWN_BINS);

    *LED = (1<<3);
    
    // Screen coloring result
    draw_spectrum(FRAME_WIDTH, FRAME_HEIGHT, fft_output_pwr, FB0);
    // Time domain waveform across top two thirds of display
    draw_waveform(FRAME_WIDTH, (FRAME_HEIGHT*2)/3, 2, fft_input_samples, n_samples, FB0);

    *LED = 0;
    //count += 1;
  }
}
