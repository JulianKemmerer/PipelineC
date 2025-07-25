#pragma once
#include "fft.h"

/* Based on https://en.wikipedia.org/wiki/Cooley%E2%80%93Tukey_FFT_algorithm#Data_reordering,_bit_reversal,_and_in-place_algorithms */
/* Compute Iterative Complex-FFT with N < 2^16 bins */
// Each bin is SAMPLE_RATE / NUM_POINTS (Hz) wide? TODO what about neg freqencies?
void compute_fft_cc(fft_in_t* input, fft_out_t* output){
    uint32_t N = NFFT;
    /* Bit-Reverse copy */
    for (uint32_t i = 0; i < N; i++)
    {
        uint32_t ri = rev(i);
        output[ri].real = input[i].real;
        output[ri].imag = input[i].imag;
    }

    // FFT iterations using hardware matching iterator structs
    fft_iters_t iters = FFT_ITERS_NULL_INIT;
    while(1){
        uint16_t s = iters.s;
        uint16_t k = iters.k;
        uint16_t j = iters.j;
        uint16_t m = (uint32_t)1 << s;
        uint16_t m_1_2 = m >> 1;
        uint16_t t_index = k + j + m_1_2;
        uint16_t u_index = k + j;
        // Run comb logic on CPU instead of using hardware
        fft_2pt_w_omega_lut_in_t fft_in;
        fft_in.t = output[t_index];
        fft_in.u = output[u_index];
        fft_in.s = s;
        fft_in.j = j;
        fft_2pt_out_t fft_out = fft_2pt_w_omega_lut(fft_in);
        output[t_index] = fft_out.t;
        output[u_index] = fft_out.u;
        if(last_iter(iters)){
            //iters = FFT_ITERS_NULL;
            break;
        }else{
            iters = next_iters(iters);
        }
    }

    /* // do this sequentially 
    // S butterfly levels
    for (uint32_t s = 1; s < (int)ceil(log2(N) + 1.0); s++)
    {
        int32_t m = 1 << s;
        int32_t m_1_2 = m >> 1;
        // principle root of nth complex
        // do this in parallel 
        for (uint32_t k = 0; k < N; k+=m)
        {   
            uint32_t t_base_index = k + m_1_2;
            uint32_t u_base_index = k;
            for (uint32_t j = 0; j < m_1_2; j++)
            {
                uint32_t t_index = t_base_index + j;
                uint32_t u_index = u_base_index + j;
                // Run comb logic on CPU instead of using hardware
                fft_2pt_w_omega_lut_in_t fft_in;
                fft_in.t = output[t_index];
                fft_in.u = output[u_index];
                fft_in.s = s;
                fft_in.j = j;
                fft_2pt_out_t fft_out = fft_2pt_w_omega_lut(fft_in);
                output[t_index] = fft_out.t;
                output[u_index] = fft_out.u;
            }
        }
    }*/
}

// Dont need real power for visualization, fake it
/*void compute_fake_power(fft_out_t* output, fft_data_t* output_pwr, int N)
{
    for (uint32_t i = 0; i < N; i++)
    {
        fft_data_t re = output[i].real;
        fft_data_t im = output[i].imag;
        #ifdef FFT_TYPE_IS_FLOAT
        output_pwr[i] = fabs(re) + fabs(im);
        #endif
        #ifdef FFT_TYPE_IS_FIXED
        output_pwr[i] = abs(re) + abs(im);
        #endif
    }
}*/
