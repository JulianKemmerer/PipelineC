// gcc fft_demo.c -lm -o fft_demo && ./fft_demo
#include "fft_demo.h"

#define NFFT (1<<6) // 64
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

void color_screen(int width, int height, float* pwr_bins, uint32_t n_bins){
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

int main(){

    // Create arrays 
    fft_in_t* input = (fft_in_t*)malloc(NFFT * sizeof(fft_in_t));
    fft_out_t* output = (fft_out_t*)malloc(NFFT * sizeof(fft_out_t));
    float* output_pwr = (float*)malloc(NFFT * sizeof(float));

    // Gen Test signal
    printf("fs,%d\n", SAMPLE_RATE_INT_HZ);
    // Rate constant in the form that works well for float and fixed point:
    //  1/fs seconds per sample, multiplied by tone rate in hz
    #ifdef FFT_TYPE_IS_FIXED
    uint32_t sec_per_sample_times_rate = (TONE_RATE_INT_HZ*(INT16_MAX+1)) / SAMPLE_RATE_INT_HZ; 
    #endif
    #ifdef FFT_TYPE_IS_FLOAT
    float sec_per_sample_times_rate = (float)TONE_RATE_INT_HZ / (float)SAMPLE_RATE_INT_HZ;
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
      float xi = (float)input[i].real / (float)INT16_MAX;
      float xj = (float)input[i].imag / (float)INT16_MAX;
      printf("i,xi,xj,%d,%f,%f\n", i, xi, xj);
      #endif
      #ifdef FFT_TYPE_IS_FLOAT
      printf("i,xi,xj,%d,%f,%f\n", i, input[i].real, input[i].imag);
      #endif
    }

    // apply fft
    compute_fft_cc(input, output, NFFT);

    // print results 
    for (uint32_t i = 0; i < NFFT; i++)
    {
        // Shift is handled in fft_demo.py, not here
        //uint32_t j = i < (NFFT>>1) ? (NFFT>>1)+i : i-(NFFT>>1); // FFT SHIFT
        //int fj = i-(NFFT>>1);
        //float re_j = (float)output[j].real / (float)INT16_MAX;
        //float im_j = (float)output[j].imag / (float)INT16_MAX;
        #ifdef FFT_TYPE_IS_FIXED
        float re = (float)output[i].real / (float)INT16_MAX;
        float im = (float)output[i].imag / (float)INT16_MAX;
        #endif
        #ifdef FFT_TYPE_IS_FLOAT
        float re = output[i].real;
        float im = output[i].imag;
        #endif
        float pwr2 = (re*re) + (im*im);
        float pwr = pwr2 > 0 ? sqrtf(pwr2) : 0;
        printf("i,re,im,p,%d,%f,%f,%f\n", i, re, im, pwr);
        output_pwr[i] = pwr;
    }

    // Print screen coloring results (640x480 ratio image)
    // Only use positive freq power in first half of array
   
    //color_screen(64, 48, output_pwr, NFFT/2);
    drawRect(0, 0, 64, 48, 0); // Clear first
    draw_spectrum_fast(64, 48, output_pwr);
}