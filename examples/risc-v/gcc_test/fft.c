#include "fft.h"

#ifdef FFT_USE_HARDWARE
static inline fft_2pt_out_t fft_2pt_hardware(fft_2pt_w_omega_lut_in_t i){
  // Write input registers contents
  mm_ctrl_regs->fft_2pt_in = i;
  //(takes just 1 CPU clock cycle, output ready immediately)
  // Return output register contents
  return mm_status_regs->fft_2pt_out;
}
// Macro version of above that does less loads and stores
#define fft_2pt_hardware_macro(T, U, S, J)\
mm_ctrl_regs->fft_2pt_in.t = T;\
mm_ctrl_regs->fft_2pt_in.u = U;\
mm_ctrl_regs->fft_2pt_in.s = S;\
mm_ctrl_regs->fft_2pt_in.j = J;\
T = mm_status_regs->fft_2pt_out.t;\
U = mm_status_regs->fft_2pt_out.u
#endif

/* Based on https://en.wikipedia.org/wiki/Cooley%E2%80%93Tukey_FFT_algorithm#Data_reordering,_bit_reversal,_and_in-place_algorithms */
/* Compute Iterative Complex-FFT with N < 2^16 bins */
// Each bin is SAMPLE_RATE / NUM_POINTS (Hz) wide? TODO what about neg freqencies?
void compute_fft_cc(fft_in_t* input, fft_out_t* output){
    uint32_t N = NFFT;
    /* Bit-Reverse copy */
    for (uint32_t i = 0; i < N; i++)
    {
        uint32_t ri = rev(i,N);
        output[i].real = input[ri].real; // Fix here, swap order
        output[i].imag = input[ri].imag; // Fix here, swap order
    }

    /* do this sequentially */
    // S butterfly levels
    for (uint32_t s = 1; s < (int)ceil(log2(N) + 1.0); s++)
    {
        int32_t m = 1 << s;
        int32_t m_1_2 = m >> 1;
        // principle root of nth complex
        /* do this in parallel */
        for (uint32_t k = 0; k < N; k+=m)
        {   
            for (uint32_t j = 0; j < m_1_2; j++)
            {
                uint32_t t_index = k + j + m_1_2;
                uint32_t u_index = k + j;
                #ifdef FFT_USE_HARDWARE
                // Invoke hardware
                fft_2pt_hardware_macro(output[t_index], output[u_index], s, j);
                #else
                // Run comb logic on CPU instead of using hardware
                fft_2pt_w_omega_lut_in_t fft_in;
                fft_in.t = output[t_index];
                fft_in.u = output[u_index];
                fft_in.s = s;
                fft_in.j = j;
                fft_2pt_out_t fft_out = fft_2pt_w_omega_lut(fft_in);
                output[t_index] = fft_out.t;
                output[u_index] = fft_out.u;
                #endif
            }
        }
    }  
}

// Dont need real power for visualization, fake it
//float pwr2 = (re*re) + (im*im);
//float pwr = sqrtf(pwr2);
//output_pwr[i] = pwr2;
void compute_fake_power(fft_out_t* output, fft_data_t* output_pwr, int N)
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
}
