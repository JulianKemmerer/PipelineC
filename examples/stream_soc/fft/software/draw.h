
// Draw shapes in frame buffer
#include "../../frame_buffers/software/draw.h"
#include "i2s/i2s_32b.h"

// Spectrum is rect bins
// Real freq part of spectrum is NFFT/2
// most of the time audio isnt in upper half, so /8 for looks
#define N_DRAWN_BINS 213 // 213 ~= (NFFT/8) and is almost 640/3
void draw_spectrum(int width, int height, fft_data_t* pwr_bins, volatile pixel_t* FB){
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
    drawRect(x_start, y_start, x_end, y_end, color, FB);
    // Store power for next time
    last_height[b] = bin_height;
  }
}
// Waveform is n pixel wide rects to form line
void draw_waveform(int width, int height, int line_width, i2s_sample_in_mem_t* i2s_input_samples, int n_samples, volatile pixel_t* FB){
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
    fft_in_t sample;
    sample.real = ((i2s_input_samples[i].l >> (24-16)) + (i2s_input_samples[i].r >> (24-16))) >> 1;
    // Calc x position, gone too far?
    int x_start = i * point_width;
    int x_end = (i+1) * point_width;
    if(x_end>FRAME_WIDTH) break;
    // Calc line current y pos
    int sample_abs = abs(sample.real);
    if(sample_abs > max_abs_sample){
      max_abs_sample = sample_abs;
    }
    int ampl = (wav_height * sample.real)/max_abs_sample;
    ampl = ampl * 2; // Scale x2 since rarely near max vol?
    int y_val = y_mid - ampl; // y inverted 0,0 top left
    if(y_val < 0) y_val = 0;
    if(y_val > height) y_val = height;
    // Erase old line portion to black
    drawRect(x_start, last_y_value[i], x_end, last_y_value[i]+line_width, 0, FB);
    // Calc new line position and draw white
    drawRect(x_start, y_val, x_end, y_val+line_width, 255, FB);
    // Save y value for next time
    last_y_value[i] = y_val;
  }
}