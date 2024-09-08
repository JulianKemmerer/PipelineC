#include <stdint.h>
#include <stdlib.h>
#include "mem_map.h"

// FFT algorithm demo code
#include "fft_demo.h"

// Some helper drawing code 
// Rect from Dutra :) (has text console stuff too!?)
void drawRect(int start_x, int start_y, int end_x, int end_y, uint8_t color){
    pixel_t p = {color, color, color, color};
    for (int32_t i = start_x; i < end_x; i++)
    {
        for (int32_t j = start_y; j < end_y; j++)
        {
            frame_buf_write(i,j,p);
        }
    }
}
/*
// Spectrum is rect bins
void draw_spectrum(int width, int height, float* pwr_bins, uint32_t n_bins){
  // How wide is each bin in pixels
  int bin_width = width / n_bins;
  // Max FFT value depends on if input is complex tone or not?
  // (Max=nfft/2)(*2 for complex tone input?)
  float max_pwr = NFFT*0.5;
  for (size_t b = 0; b < n_bins; b++)
  {
    // Calculate bounds for this bin
    // (recall 0,0 is top left)
    int x_start = b * bin_width;
    int x_end = (b+1) * bin_width;
    int y_end = height;
    int bin_height = (pwr_bins[b]/max_pwr) * height;
    int y_start = y_end - bin_height; //-1; //?
    // Clear bin by drawing full height black first
    drawRect(x_start, 0, x_end, height, 0);
    // Then white with proper y bounds
    drawRect(x_start, y_start, x_end, y_end, 255);
  }
}
*/
#define N_BINS (NFFT/2)
void draw_spectrum_fast(int width, int height, float* pwr_bins){
  // Remember the power value from last time to make updates easier
  static int last_height[N_BINS] = {0};
  // How wide is each bin in pixels
  int bin_width = width / N_BINS;
  // Max FFT value depends on if input is complex tone or not?
  // (Max=nfft/2)(*2 for complex tone input?)
  float max_pwr = NFFT/4; // /4 since rarely near max audio to speakers?
  for (size_t b = 0; b < N_BINS; b++)
  {
    int x_start = b * bin_width;
    int x_end = (b+1) * bin_width;
    int bin_height = (pwr_bins[b]/max_pwr) * height;
    if(bin_height > height) bin_height = height;
    uint8_t color = 0;
    int y_start = 0;
    int y_end = 0;
    // Calculate bounds for this bin
    // (recall 0,0 is top left)
    // Increase rect height or shorten?
    if(bin_height > last_height[b]){
      // Increase height, draw white
      y_start = height - bin_height;
      y_end = height - last_height[b];
      color = 255;
    }else{
      // Decrease height, draw black
      y_start = height - last_height[b];
      y_end =  height - bin_height;
      color = 0;
    }

    // Rect with proper y bounds
    drawRect(x_start, y_start, x_end, y_end, color);

    // Store power for next time
    last_height[b] = bin_height;
  }
}

void main() {
  //int count = 0;
  // Clear screen to black
  drawRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT, 0);
  while(1){
    *LED = 0; //mm_status_regs->i2s_rx_out_desc_overflow;
    
    // Read i2s samples (in DDR3 off chip)
    i2s_sample_in_mem_t* samples = NULL;
    int n_samples = 0;
    i2s_read(&samples, &n_samples);

    *LED = (1<<0);

    // Copy samples into buffer and convert to input type as needed (in BRAM)
    fft_in_t fft_input_samples[NFFT] = {0};
    for (size_t i = 0; i < NFFT; i++)
    {
      #ifdef FFT_TYPE_IS_FLOAT
      fft_input_samples[i].real = (float)samples[i].l/(float)(1<<24);
      fft_input_samples[i].imag = 0;
      #endif
      #ifdef FFT_TYPE_IS_FIXED
      fft_input_samples[i].real = samples[i].l >> (24-16);
      fft_input_samples[i].imag = 0;
      #endif
    }

    *LED = (1<<1);

    // Compute FFT
    fft_out_t fft_output[NFFT] = {0};
    compute_fft_cc(fft_input_samples, fft_output, NFFT);
    
    *LED = (1<<2);

    // Compute power
    float fft_output_pwr[NFFT] = {0};
    for (uint32_t i = 0; i < NFFT; i++)
    {
        #ifdef FFT_TYPE_IS_FIXED
        float re = (float)fft_output[i].real / (float)INT16_MAX;
        float im = (float)fft_output[i].imag / (float)INT16_MAX;
        #endif
        #ifdef FFT_TYPE_IS_FLOAT
        float re = fft_output[i].real;
        float im = fft_output[i].imag;
        #endif
        float pwr2 = (re*re) + (im*im);
        float pwr = sqrtf(pwr2);
        //printf("i,re,im,p,%d,%f,%f,%f\n", i, re, im, pwr);
        fft_output_pwr[i] = pwr;
    }

    *LED = (1<<3);
    
    // Print screen coloring results
    // Only use positive freq power in first half of array
    draw_spectrum_fast(FRAME_WIDTH, FRAME_HEIGHT, fft_output_pwr);
   
    //count += 1;
  }
}