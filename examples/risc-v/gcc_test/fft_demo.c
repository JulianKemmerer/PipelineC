// gcc fft_demo.c -lm -o fft_demo && ./fft_demo
#define NFFT (1<<11)
#include "fft.h"
#include "fft.c"

// Set sample rate for working out units
#define SAMPLE_RATE_INT_HZ 44100 // Fs in integer Hz
#define TONE_RATE_INT_HZ 12345 // integer Hz
//#define TONE_IS_COMPLEX

// For demo writing frame buffer is putting pixel in std out for fft_demo.py to plot
void frame_buf_write(uint16_t x, uint16_t y, uint8_t color)
{
    printf("x,y,c,%d,%d,%d\n", x, y, color);
}

// Some helper drawing code from Dutra :) (has text console stuff too!?)
void drawRect(int start_x, int start_y, int end_x, int end_y, uint8_t color){
    for (int32_t i = start_x; i < end_x; i++)
    {
        for (int32_t j = start_y; j < end_y; j++)
        {
            frame_buf_write(i,j,color);
        }
    }
}

#define N_BINS (NFFT/2)
void draw_spectrum_fast(int width, int height, fft_data_t* pwr_bins){
  // Remember the power value from last time to make updates easier
  static int last_height[N_BINS] = {0};
  // How wide is each bin in pixels
  int bin_width = width / N_BINS;
  if(bin_width <= 0) bin_width = 1;
  // Max FFT value depends on if input is complex tone or not?
  // (Max=nfft/2)(*2 for complex tone input?)
  // Auto size to max like live hardware demo does
  fft_data_t max_pwr = 1;
  for (size_t b = 0; b < N_BINS; b++)
  {
    if(pwr_bins[b]>max_pwr) max_pwr = pwr_bins[b];
  }
  for (size_t b = 0; b < N_BINS; b++)
  {
    int x_start = b * bin_width;
    int x_end = (b+1) * bin_width;
    if(x_end >= width) break;
    int bin_height = ((uint64_t)pwr_bins[b] * (uint64_t)height)/max_pwr;
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

int main(){
    #ifdef FFT_USE_OMEGA_LUT
    // One time init omega lookup
    init_omega_lookup();
    //print_omega_lookup();
    #endif

    // Create arrays for signals
    fft_in_t* input = (fft_in_t*)malloc(NFFT * sizeof(fft_in_t));
    fft_out_t* output = (fft_out_t*)malloc(NFFT * sizeof(fft_out_t));
    fft_data_t* output_pwr = (fft_data_t*)malloc(NFFT * sizeof(fft_data_t));

    // Gen Test signal
    printf("fs,%d\n", SAMPLE_RATE_INT_HZ);
    // Rate constant in the form that works well for float and fixed point:
    //  1/fs seconds per sample, multiplied by tone rate in hz
    #ifdef FFT_TYPE_IS_FIXED
    fft_data_t sec_per_sample_times_rate = (TONE_RATE_INT_HZ*(INT16_MAX+1)) / SAMPLE_RATE_INT_HZ; 
    #endif
    #ifdef FFT_TYPE_IS_FLOAT
    fft_data_t sec_per_sample_times_rate = (float)TONE_RATE_INT_HZ / (float)SAMPLE_RATE_INT_HZ;
    #endif
    for (uint32_t i = 0; i < NFFT; i++)
    {
        input[i] = exp_complex(i*sec_per_sample_times_rate);
        #ifndef TONE_IS_COMPLEX
        input[i].imag = 0;
        #endif
    }

    // print input as float 
    for (uint32_t i = 0; i < NFFT; i++)
    {
      #ifdef FFT_TYPE_IS_FIXED
      complex_t input_f = ci16_to_complex(input[i]);
      float xi = input_f.real;
      float xj = input_f.imag;
      printf("i,xi,xj,%d,%f,%f\n", i, xi, xj);
      #endif
      #ifdef FFT_TYPE_IS_FLOAT
      printf("i,xi,xj,%d,%f,%f\n", i, input[i].real, input[i].imag);
      #endif
    }

    // apply fft (shift is handled in fft_demo.py, not here)
    compute_fft_cc(input, output);
    // compute power in each fft bin
    compute_power(output, output_pwr, NFFT);

    // print fft and power output result 
    for (uint32_t i = 0; i < NFFT; i++)
    {
      #ifdef FFT_TYPE_IS_FIXED
      complex_t output_f = ci32_to_complex(output[i]);
      float re = output_f.real;
      float im = output_f.imag;
      printf("i,re,im,p,%d,%f,%f,%d\n", i, re, im, output_pwr[i]);
      #endif
      #ifdef FFT_TYPE_IS_FLOAT
      float re = output[i].real;
      float im = output[i].imag;
      printf("i,re,im,p,%d,%f,%f,%f\n", i, re, im, output_pwr[i]);
      #endif
    }

    // Print screen coloring results (640x480 ratio image)
    // Only use positive freq power in first half of array
   
    //color_screen(64, 48, output_pwr, NFFT/2);
    drawRect(0, 0, 640, 480, 0); // Clear first
    draw_spectrum_fast(640, 480, output_pwr);
}