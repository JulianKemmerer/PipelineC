#include <stdint.h>
#include <stdlib.h> 

// FFT algorithm demo code
#include "../fft/software/fft_types.h"
#include "../fft/software/power.h"
#include "../fft/software/draw.h"
// Not doing FFT in software right now but could...
//#include "../fft/software/fft.c"
#include "mem_map.h"
// I2S hardware
#include "../i2s/software/i2s.h"

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

  while(1){
    *LED = 0; //mm_status_regs->i2s_rx_out_desc_overflow;
    
    // Read i2s samples (in DDR3 off chip)
    i2s_sample_in_mem_t* samples = NULL;
    int n_samples = 0;
    i2s_read(&samples, &n_samples);

    *LED = (1<<0);

    // Copy samples into buffer and convert to input type as needed (in BRAM)
    n_samples = FRAME_WIDTH;
    for (size_t i = 0; i < n_samples; i++)
    {
      // I2S samples are 24b fixed point
      fft_input_samples[i].real = ((samples[i].l >> (24-16)) + (samples[i].r >> (24-16))) >> 1;
      fft_input_samples[i].imag = 0;
    }

    *LED = (1<<1);

    // Compute FFT
    uint32_t start_time = mm_status_regs->cpu_clock;
    //compute_fft_cc(fft_input_samples, fft_output);
    // FFT result in AXI DDR RAM
    // Copy fft output into buffer
    for (size_t i = 0; i < N_DRAWN_BINS; i++)
    {
      fft_output[i] = ((fft_out_t*)FFT_OUT_ADDR)[i];
    }
    uint32_t end_time = mm_status_regs->cpu_clock;
    mm_ctrl_regs->compute_fft_cycles = end_time - start_time;
    
    *LED = (1<<2);

    // Compute power
    compute_power(fft_output, fft_output_pwr, N_DRAWN_BINS);

    *LED = (1<<3);
    
    // Screen coloring result
    draw_spectrum(FRAME_WIDTH, FRAME_HEIGHT, fft_output_pwr, FB0);
    // Time domain waveform across top two thirds of display
    draw_waveform(FRAME_WIDTH, (FRAME_HEIGHT*2)/3, 2, fft_input_samples, n_samples, FB0);
    //count += 1;
  }
}
