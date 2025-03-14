#include <stdint.h>
#include <stdlib.h>

// FFT algorithm demo code
#define FFT_USE_FULL_HARDWARE // FFT_USE_COMB_LOGIC_HARDWARE
#include "fft.h"
#include "mem_map.h"
#include "fft.c"

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

// Spectrum is rect bins
// Real freq part of spectrum is NFFT/2
// most of the time audio isnt in upper half, so /8 for looks
#define N_DRAWN_BINS 213 // 213 ~= (NFFT/8) and is almost 640/3
void draw_spectrum(int width, int height, fft_data_t* pwr_bins){
  // Remember the power value from last time to make updates faster
  static int last_height[N_DRAWN_BINS] = {0};
  // How wide is each bin in pixels
  int bin_width = width / N_DRAWN_BINS;
  if(bin_width <= 0) bin_width = 1;
  // Max FFT value depends on if input is complex tone or not?
  // (Max=nfft/2)(*2 for complex tone input?)
  static fft_data_t max_pwr = 1; // adjusts to fit max seen over time
  // Decrease max ocasisonally. not too fast for normal silent gaps in audio
  int RESET_TIME_SEC = 5;
  static int max_reset_counter = 0;
  if(max_reset_counter >= ((RESET_TIME_SEC*44100)/NFFT)){
    max_pwr = (max_pwr * 9)/10;
    max_pwr = max_pwr <= 0 ? 1 : max_pwr;
    max_reset_counter = 0;
  }else{
    max_reset_counter += 1;
  }
  for (size_t b = 0; b < N_DRAWN_BINS; b++)
  {
    // min_bin_height is max near bin zero low freq, min near final bin high freq
    int min_bin_height = (height*(N_DRAWN_BINS-b))/(15*N_DRAWN_BINS); // (height/15) * ((N_DRAWN_BINS-b)/N_DRAWN_BINS);
    int x_start = b * bin_width;
    int x_end = (b+1) * bin_width;
    if(x_end >= width) break;
    if(pwr_bins[b] > max_pwr) max_pwr = pwr_bins[b];
    int bin_height = ((uint64_t)pwr_bins[b] * (uint64_t)height)/max_pwr;
    if(bin_height < 0) bin_height = 0;
    if(bin_height > height) bin_height = height;
    if(bin_height < min_bin_height) bin_height = 0; // For looks cut off "noise" floor
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
// Waveform is n pixel wide rects to form line
void draw_waveform(int width, int height, int line_width, fft_in_t* input_samples, int n_samples){
  // line_width used in y height direction
  // How wide is each point forming line
  int point_width = width / n_samples;
  if(point_width <= 0) point_width = 1;
  int wav_height = height / 3;
  int y_mid = height / 2;
  // Remember the amplitude value from last time to make updates faster
  static int last_y_value[FRAME_WIDTH] = {0};
  // Remember max ampl for auto scale (fixed point only)
  static int max_abs_sample = 1;
  // Decrease max ocasisonally. not too fast for normal silent gaps in audio
  int RESET_TIME_SEC = 5;
  static int max_reset_counter = 0;
  if(max_reset_counter >= ((RESET_TIME_SEC*44100)/NFFT)){
    max_abs_sample = (max_abs_sample * 9)/10;
    max_abs_sample = max_abs_sample <= 0 ? 1 : max_abs_sample;
    max_reset_counter = 0;
  }else{
    max_reset_counter += 1;
  }
  for (size_t i = 0; i < n_samples; i++)
  {
    // Calc x position, gone too far?
    int x_start = i * point_width;
    int x_end = (i+1) * point_width;
    if(x_end>FRAME_WIDTH) break;
    // Calc line current y pos
    #ifdef FFT_TYPE_IS_FLOAT
    int ampl = (int)(wav_height * input_samples[i].real);
    #endif
    #ifdef FFT_TYPE_IS_FIXED
    int sample_abs = abs(input_samples[i].real);
    if(sample_abs > max_abs_sample){
      max_abs_sample = sample_abs;
    }
    int ampl = (wav_height * input_samples[i].real)/max_abs_sample;
    #endif
    ampl = ampl * 2; // Scale x2 since rarely near max vol?
    int y_val = y_mid - ampl; // y inverted 0,0 top left
    if(y_val < 0) y_val = 0;
    if(y_val > height) y_val = height;
    // Erase old line portion to black
    drawRect(x_start, last_y_value[i], x_end, last_y_value[i]+line_width, 0);
    // Calc new line position and draw white
    drawRect(x_start, y_val, x_end, y_val+line_width, 255);
    // Save y value for next time
    last_y_value[i] = y_val;
  }
}

void main() {
  //int count = 0;
  // Clear screen to black
  drawRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT, 0);
  #ifdef FFT_USE_OMEGA_LUT
  // Init lookup table for FFT
  init_omega_lookup();
  #endif

  // FFT in hardware only needs input samples for final waveform display
  // dont need full NFFT as number of samples, at most FRAME_WIDTH points
  #ifdef FFT_USE_FULL_HARDWARE
  fft_in_t fft_input_samples[FRAME_WIDTH] = {0};
  #else 
  fft_in_t fft_input_samples[NFFT] = {0};
  #endif
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
    #ifdef FFT_USE_FULL_HARDWARE
    n_samples = FRAME_WIDTH;
    #endif
    for (size_t i = 0; i < n_samples; i++)
    {
      // I2S samples are 24b fixed point
      #ifdef FFT_TYPE_IS_FLOAT
      float l = (float)samples[i].l/(float)(1<<24);
      float r = (float)samples[i].r/(float)(1<<24);
      fft_input_samples[i].real = (l+r)/2.0;
      fft_input_samples[i].imag = 0;
      #endif
      #ifdef FFT_TYPE_IS_FIXED
      fft_input_samples[i].real = ((samples[i].l >> (24-16)) + (samples[i].r >> (24-16))) >> 1;
      fft_input_samples[i].imag = 0;
      #endif
    }

    *LED = (1<<1);

    // Compute FFT
    uint32_t start_time = mm_status_regs->cpu_clock;
    compute_fft_cc(fft_input_samples, fft_output);
    uint32_t end_time = mm_status_regs->cpu_clock;
    mm_ctrl_regs->compute_fft_cycles = end_time - start_time;
    
    *LED = (1<<2);

    // Compute power
    compute_power(fft_output, fft_output_pwr, N_DRAWN_BINS);

    *LED = (1<<3);
    
    // Screen coloring result
    draw_spectrum(FRAME_WIDTH, FRAME_HEIGHT, fft_output_pwr);
    // Time domain waveform across top two thirds of display
    draw_waveform(FRAME_WIDTH, (FRAME_HEIGHT*2)/3, 2, fft_input_samples, n_samples);
    //count += 1;
  }
}