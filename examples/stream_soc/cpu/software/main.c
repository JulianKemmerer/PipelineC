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
  // Clear screen to black
  drawRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT, 0, FB0);

  // Configure chunks of I2S samples to read
  uint32_t i2s_addr = I2S_BUFFS_ADDR;
  for(uint32_t i = 0; i < I2S_N_DESC; i++)
  {
    i2s_rx_enq_write((i2s_sample_in_mem_t*)i2s_addr, NFFT);
    i2s_addr += sizeof(i2s_sample_in_mem_t)*NFFT;
  }

  // Configure FFT result AXIS sink to write to AXI DDR at specific address
  fft_config_result((fft_out_t*)FFT_OUT_ADDR);

  // Buffer for power result output
  fft_data_t fft_output_pwr[N_DRAWN_BINS] = {0};

  while(1){
    // Read i2s samples (in DDR3 off chip)
    i2s_sample_in_mem_t* samples_in_dram = NULL;
    int n_samples = 0;
    if(i2s_try_read(&samples_in_dram, &n_samples)){
      *LED = (1<<0);

      // Time domain waveform across top two thirds of display
      draw_waveform(FRAME_WIDTH, (FRAME_HEIGHT*2)/3, 2, samples_in_dram, n_samples, FB0);

      // Enqueue the buffer to be used for future rx samples writes
      i2s_rx_enq_write(samples_in_dram, n_samples);
    }

    *LED = 0;

    // Read FFT result (in DDR3 off chip mem)
    fft_out_t* fft_out_in_dram;
    if(fft_try_read_result(&fft_out_in_dram, &n_samples)){
      *LED = (1<<1);

      // Compute power
      compute_power(fft_out_in_dram, fft_output_pwr, N_DRAWN_BINS);      

      // Confgure next FFT result output buffer at same place as current
      fft_config_result(fft_out_in_dram); // Or (fft_out_t*)FFT_OUT_ADDR)...

      *LED = (1<<2);

      // Screen coloring result
      draw_spectrum(FRAME_WIDTH, FRAME_HEIGHT, fft_output_pwr, FB0);
    }
    
    *LED = 0;
  }
}
