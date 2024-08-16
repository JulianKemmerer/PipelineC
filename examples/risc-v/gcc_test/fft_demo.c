// gcc fft_demo.c -lm -o fft_demo && ./fft_demo
#include "fft_demo.h"
int main(){

    // Create arrays 
    ci16_t* input = (ci16_t*)malloc(NFFT * sizeof(ci16_t));
    ci32_t* output = (ci32_t*)malloc(NFFT * sizeof(ci32_t));
    float* output_pwr = (float*)malloc(NFFT * sizeof(float));

    // Gen Test signal
    uint32_t Fs = (INT16_MAX+1) / NFFT; // NFFT/1.0 Hz?
    for (uint32_t i = 0; i < NFFT; i++)
    {
        input[i] = exp_taylor(4*i*Fs);
    }

    // print input as float 
    for (uint32_t i = 0; i < NFFT; i++)
    {
      float xi = (float)input[i].real / (float)INT16_MAX;
      float xj = (float)input[i].imag / (float)INT16_MAX;
      printf("i,xi,xj,%d,%f,%f\n", i, xi, xj);
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
        float re = (float)output[i].real / (float)INT16_MAX;
        float im = (float)output[i].imag / (float)INT16_MAX;
        float pwr2 = (re*re) + (im*im);
        float pwr = pwr2 > 0 ? sqrtf(pwr2) : 0;
        printf("i,re,im,p,%d,%f,%f,%f\n", i, re, im, pwr);
    }

    // Print screen coloring results (640x480 ratio image)
    color_screen(NFFT, (NFFT*480)/640, output_pwr, NFFT);
}