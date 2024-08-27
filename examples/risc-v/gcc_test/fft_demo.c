// gcc fft_demo.c -lm -o fft_demo && ./fft_demo
#include "fft_demo.h"
int main(){

    // Create arrays 
    fft_in_t* input = (fft_in_t*)malloc(NFFT * sizeof(fft_in_t));
    fft_out_t* output = (fft_out_t*)malloc(NFFT * sizeof(fft_out_t));
    float* output_pwr = (float*)malloc(NFFT * sizeof(float));

    // Gen Test signal
    #ifdef FFT_TYPE_IS_FIXED
    uint32_t Fs =  (INT16_MAX+1) / NFFT; // NFFT/1.0 Hz?
    #endif
    #ifdef FFT_TYPE_IS_FLOAT
    float Fs = (1.0 / NFFT) * 2.0 * 3.14; // 2pi/NFFT Hz ?
    #endif
    for (uint32_t i = 0; i < NFFT; i++)
    {
        input[i] = exp_complex(4*i*Fs); // 4 Hz tone
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
    }

    // Print screen coloring results (640x480 ratio image)
    color_screen(NFFT, (NFFT*480)/640, output_pwr, NFFT);
}