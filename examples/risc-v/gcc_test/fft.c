#include "fft.h"

#ifdef FFT_USE_COMB_LOGIC_HARDWARE
static inline fft_2pt_out_t fft_2pt_comb_hardware(fft_2pt_w_omega_lut_in_t i){
  // Write input registers contents
  mm_ctrl_regs->fft_2pt_in = i;
  //(takes just 1 or 2 CPU clock cycle, output ready immediately)
  // Return output register contents
  return mm_status_regs->fft_2pt_out;
}
// Macro version of above that does less loads and stores
#define fft_2pt_comb_hardware_macro(T, U, S, J)\
mm_ctrl_regs->fft_2pt_in.t = T;\
mm_ctrl_regs->fft_2pt_in.u = U;\
mm_ctrl_regs->fft_2pt_in.s = S;\
mm_ctrl_regs->fft_2pt_in.j = J;\
/*(takes just 1 or 2 CPU clock cycle, output ready immediately)*/\
T = mm_status_regs->fft_2pt_out.t;\
U = mm_status_regs->fft_2pt_out.u
#endif

/* Based on https://en.wikipedia.org/wiki/Cooley%E2%80%93Tukey_FFT_algorithm#Data_reordering,_bit_reversal,_and_in-place_algorithms */
/* Compute Iterative Complex-FFT with N < 2^16 bins */
// Each bin is SAMPLE_RATE / NUM_POINTS (Hz) wide? TODO what about neg freqencies?
void compute_fft_cc(fft_in_t* input, fft_out_t* output){
    uint32_t N = NFFT;
    #ifdef FFT_USE_FULL_HARDWARE
    // FFT done in hw, just copy results to output
    for (uint32_t i = 0; i < N; i++)
    {
        fft_out_READ(&(output[i]));
    }
    #else // Some work done by CPU
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
        #ifdef FFT_USE_COMB_LOGIC_HARDWARE
        // Invoke hardware comb logic 2pt butterfly
        fft_2pt_comb_hardware_macro(output[t_index], output[u_index], s, j);
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
                #ifdef FFT_USE_COMB_LOGIC_HARDWARE
                // Invoke hardware comb logic 2pt butterfly
                fft_2pt_comb_hardware_macro(output[t_index], output[u_index], s, j);
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
    }*/ 
    #endif
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
/*
// https://en.wikipedia.org/wiki/Fast_inverse_square_root
float Q_rsqrt( float number )
{
	long i;
	float x2, y;
	const float threehalfs = 1.5F;
	x2 = number * 0.5F;
	y  = number;
	i  = * ( long * ) &y;						// evil floating point bit level hacking
	i  = 0x5f3759df - ( i >> 1 );               // what the fuck?
	y  = * ( float * ) &i;
	y  = y * ( threehalfs - ( x2 * y * y ) );   // 1st iteration
	return y;
}
float Q_sqrt(float x) { return x*Q_rsqrt(x); }
// STILL TOO SLOW! TODO MAKE POWER COMPUTE INTO HARDWARE TOO!
void compute_power(fft_out_t* output, fft_data_t* output_pwr, int N)
{
    for (uint32_t i = 0; i < N; i++)
    {
        #ifdef FFT_TYPE_IS_FLOAT
        float re = output[i].real;
        float im = output[i].imag;
        float pwr2 = (re*re) + (im*im);
        float pwr = sqrt(pwr2);
        output_pwr[i] = pwr;
        #endif
        #ifdef FFT_TYPE_IS_FIXED
        fft_data_t re = output[i].real;
        fft_data_t im = output[i].imag;
        int64_t pwr2_fixed = 
            (
                ((int64_t)re * (int64_t)re) +
                ((int64_t)im * (int64_t)im)
            ) >> 16;
        // Approx with shift instead of divide?
        //float pwr2 = (float)pwr2_fixed/(float)INT16_MAX;
        float pwr2 = (float)(pwr2_fixed >> 15);
        //printf("power2 %f\n", pwr2);
        // Faster sqrt from quake?
        //float pwr = sqrt(pwr2);
        float pwr = Q_sqrt(pwr2);
        //printf("power %f\n", pwr);
        // Approx with shift instead of multiply?
        //output_pwr[i] = (fft_data_t)(pwr*INT16_MAX);
        output_pwr[i] = ((fft_data_t)pwr)<<15;
        #endif
    }
}
*/