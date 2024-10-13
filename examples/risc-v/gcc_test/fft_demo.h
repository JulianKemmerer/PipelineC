// Dutra FFT Demo
#pragma once

#ifndef __PIPELINEC__
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#else
#include "uintN_t.h"
#include "intN_t.h"
#endif

#ifndef NFFT
#define NFFT 1024
#endif

typedef struct complex_t
{
    float real, imag;
}complex_t;

// Select fft data type
//#define FFT_TYPE_IS_FLOAT
#define FFT_TYPE_IS_FIXED
// Use a lookup table for complex exponential values?
#define FFT_USE_OMEGA_LUT // Doesnt work in hardware yet? Get bad looking spectrum!

#ifdef FFT_TYPE_IS_FLOAT
#define fft_data_t float
#define fft_in_t complex_t
#define fft_out_t complex_t
#define ONE_PLUS_0I_INIT {1.0, 0.0} // 1 + 0i
// Complex exponential e ^ (2 * pi * i * x)
static inline complex_t exp_complex(float x){
    complex_t rv;
    rv.real = cos(2.0f*M_PI*x);
    rv.imag = sin(2.0f*M_PI*x);
    return rv;
}
#define EXP_COMPLEX_CONST_ONE 1.0
static inline complex_t mul_in_out(complex_t a, complex_t b){
    complex_t rv;
    rv.real = (a.real* b.real) - (a.imag* b.imag);
    rv.imag = (a.real* b.imag) + (a.imag* b.real);
    return rv; 
}
static inline complex_t mul_in(complex_t a, complex_t b){
    return mul_in_out(a,b);
}
static inline complex_t mul_out(complex_t a, complex_t b){
    return mul_in_out(a,b);
}
#endif

#ifdef FFT_TYPE_IS_FIXED

/* Base Types */

/* Q0.15 Fixed point, 1 sign bit, 0 integer bits, 15 fraction bits = int16 */
typedef struct ci16_t
{
    int16_t real, imag;
}ci16_t;
#define ONE_PLUS_0I_INIT {INT16_MAX, 0} // 1 + 0i

static inline int16_t mul16(int16_t a, int16_t b){
    int16_t rv = ((int16_t)a * (int16_t)b) >> 15;
    return rv;
}

static inline ci16_t mul_in(ci16_t a, ci16_t b){
    ci16_t rv;
    rv.real = mul16(a.real, b.real) - mul16(a.imag, b.imag);
    rv.imag = mul16(a.real, b.imag) + mul16(a.imag, b.real);
    return rv;
}

static inline ci16_t add_ci16(ci16_t a, ci16_t b){
    ci16_t rv = {a.real + b.real, a.imag + b.imag};
    return rv;
}

static inline ci16_t sub_ci16(ci16_t a, ci16_t b){
    ci16_t rv = {a.real - b.real, a.imag - b.imag};
    return rv;
}

/* Q15.16 Fixed point, 1 sign bit, 15 integer bits, 16 fraction bits = int32 */
typedef struct ci32_t
{
    int32_t real, imag;
}ci32_t;
#define fft_data_t int32_t
#define fft_in_t ci16_t
#define fft_out_t ci32_t

complex_t ci16_to_complex(ci16_t c){
    complex_t rv;
    rv.real = (float)c.real / (float)INT16_MAX;
    rv.imag = (float)c.imag / (float)INT16_MAX;
    return rv;
}
complex_t ci32_to_complex(ci32_t c){
    complex_t rv;
    rv.real = (float)c.real / (float)INT16_MAX;
    rv.imag = (float)c.imag / (float)INT16_MAX;
    return rv;
}

static inline int32_t mul32(int32_t a, int32_t b){
    int32_t rv = ((int64_t)a * (int64_t)b) >> 16;
    return rv;
}

static inline ci32_t mul_out(ci32_t a, ci32_t b){
    ci32_t rv;
    rv.real = mul32(a.real, b.real) - mul32(a.imag, b.imag);
    rv.imag = mul32(a.real, b.imag) + mul32(a.imag, b.real);
    return rv;
}

static inline ci32_t mul_in_out(ci16_t a, ci32_t b){
    ci32_t a_e = {.real = (int32_t)a.real << 1, .imag=(int32_t)a.imag << 1};
    return mul_out(a_e,b);
}

/* code from https://www.coranac.com/2009/07/sines/ */
/// A sine approximation via a fourth-order cosine approx.
/// @param x   angle (with 2^15 units/circle)
/// @return     Sine value (I16)
/*static inline int32_t isin_S4(int32_t x)
{
    int c, y;
    static const int B=(2.0 - M_PI/4.0)*INT16_MAX, C=(1.0 - M_PI/4.0)*INT16_MAX;

    c= x<<17;             // Semi-circle info into carry.
    x -= 1<<13;           // sine -> cosine calc

    x= x<<18;             // Mask with PI
    x= x>>18;             // Note: SIGNED shift! (to Q13)
    x=(x*x)>>11;          // x=x^2 To I16

    y= B - (x*C>>15);     // B - x^2*C
    y= INT16_MAX-(x*y>>15); // A - x^2*(B-x^2*C)
    return c>=0 ? y : -y;
}*/

/* code from https://www.coranac.com/2009/07/sines/ */
/// A cosine approximation via a fourth-order cosine approx.
/// @param x   angle (with 2^15 units/circle)
/// @return     Cosine value (I16)
/*static inline int32_t icos_S4(int32_t x)
{
    int c, y;
    static const int B=(2.0 - M_PI/4.0)*INT16_MAX, C=(1.0 - M_PI/4.0)*INT16_MAX;

    c= (x<<18) ^ (x<<17);             // Semi-circle info into carry.

    x= x<<18;             // Mask with PI
    x= x>>18;             // Note: SIGNED shift! (to Q13)
    x=(x*x)>>11;          // x=x^2 To I16

    y= B - (x*C>>15);     // B - x^2*C
    y= INT16_MAX-(x*y>>15); // A - x^2*(B-x^2*C)
    return c>=0 ? y : -y;
}*/

#include "../../cordic.h"

/// Complex exponential e ^ (2 * pi * i * x)
/// @param x   angle Qx.15
/// @return    exp value (CI16, Q0.15) 
static inline ci16_t exp_complex(int32_t x){
    ci16_t rv;
    // Old fixed point solution doesnt work, not accurate enough?
    // rv.real = icos_S4(x);  // cos first
    // rv.imag = isin_S4(x);  // then, sin... fixed bug
    //float theta = 2.0f*M_PI*((float)x/32768.0f);
    //int64_t theta_int = (int)(32768.0f * theta);
    // Floating point
    //float c = cosf(theta);
    //float s = sinf(theta);
    //int32_t c_fixed = (int)(32767.0f * c);
    //int32_t s_fixed = (int)(32767.0f * s);
    // New fixed point
    int64_t x_scaled = (int64_t)x << (30-15); // Scale 15b fraction to 30b fraction
    int64_t theta_fixed = cordic_mul_2pi(x_scaled);
    cordic_fixed32_t cordic = cordic_mod_fixed32_n32(theta_fixed);
    ci16_t cordic_scaled;
    cordic_scaled.real = cordic.c >> (30-15);
    cordic_scaled.imag = cordic.s >> (30-15);
    // HACKS WTF life is too short to deal with this number format shit
    if(cordic_scaled.real > 0){
        cordic_scaled.real -= 1;
    }else if(cordic_scaled.real < 0){
        cordic_scaled.real += 1;
    }
    if(cordic_scaled.imag > 0){
        cordic_scaled.imag -= 1;
    }else if(cordic_scaled.imag < 0){
        cordic_scaled.imag += 1;
    }
    //printf("x, theta, theta_fixed, c, cordic_scaled.re, s, cordic_scaled.im, %d, %f, %f, %d, %d, %d, %d\n",
    //        x, theta, cordic_int_to_float(theta_fixed), c_fixed, cordic_scaled.real, s_fixed, cordic_scaled.imag);
    rv = cordic_scaled;
    return rv;
}
#define EXP_COMPLEX_CONST_ONE (1<<15) // Use INT16_MAX?
// No... INT16_MAX = 32767, we need 32768, maybe -INT16_MIN (32768) ?
#endif

static inline fft_out_t add_complex(fft_out_t a, fft_out_t b){
    fft_out_t rv = {a.real + b.real, a.imag + b.imag};
    return rv;
}

static inline fft_out_t sub_complex(fft_out_t a, fft_out_t b){
    fft_out_t rv = {a.real - b.real, a.imag - b.imag};
    return rv;
}

/* Counts the number of set bits */
static inline unsigned int popcnt_(unsigned int v){
    unsigned int c;
    for (c = 0; v; c++)
    {
        v &= v - 1;
    }
    return c;
}


/* Code from https://graphics.stanford.edu/~seander/bithacks.html#ReverseByteWith32Bits*/
static inline uint32_t rev(uint32_t v, const uint32_t N){
    uint32_t sr = 32 - popcnt_(N-1);
    // swap odd and even bits
    v = ((v >> 1) & 0x55555555) | ((v & 0x55555555) << 1);
    // swap consecutive pairs
    v = ((v >> 2) & 0x33333333) | ((v & 0x33333333) << 2);
    // swap nibbles ... 
    v = ((v >> 4) & 0x0F0F0F0F) | ((v & 0x0F0F0F0F) << 4);
    // swap bytes
    v = ((v >> 8) & 0x00FF00FF) | ((v & 0x00FF00FF) << 8);
    // swap 2-byte long pairs
    v = ( v >> 16             ) | ( v               << 16);
    return (v >> sr);
}

#ifdef FFT_USE_OMEGA_LUT
// Lookup table for omega values instead of recalculating during each FFT iteration
// volatile needed for some reason?
volatile fft_in_t OMEGA_LUT[NFFT]={0}; // Init by software for now
void init_omega_lookup(){
    int N = NFFT;
    int index = 0;
    for (uint32_t s = 1; s < (int)ceil(log2(N) + 1.0); s++)
    {
        //printf("s = %d\n", s);
        int32_t m = 1 << s;
        int32_t m_1_2 = m >> 1;
        fft_in_t omega_m = exp_complex(-EXP_COMPLEX_CONST_ONE / m);
        fft_in_t omega = ONE_PLUS_0I_INIT; 
        for (uint32_t j = 0; j < m_1_2; j++)
        {
            //printf("INIT s = %d, j = %d ~= omega lut index[%d]\n", s, j, index);
            OMEGA_LUT[index] = omega;
            index++;
            omega = mul_in(omega, omega_m);
        }
    }  
}
fft_in_t omega_lookup(int s, int j){
    // sum of 2^x from 0 to N = 2^(n+1)-1
    int num_j_elems_so_far = (1<<(s-1)) - 1;
    int index = num_j_elems_so_far + j;
    //printf("LOOKUP s = %d, j = %d ~= omega lut index[%d]\n", s, j, index);
    return OMEGA_LUT[index];
}
#endif

// Hardware PipelineC compilable pipeline for the inner loop math of fft algorithm
/* // t = twiddle factor
fft_out_t t = mul_in_out(omega, output[t_index]);
fft_out_t u = output[u_index];
// calculating y[k + j]
output[u_index] = add_complex(u, t);
// calculating y[k+j+n/2]
output[t_index] = sub_complex(u, t);*/
typedef struct fft_2pt_in_t
{
  fft_out_t t;
  fft_out_t u;
  fft_in_t omega;
}fft_2pt_in_t;
typedef struct fft_2pt_out_t
{
  fft_out_t t;
  fft_out_t u;
}fft_2pt_out_t;
fft_2pt_out_t fft_2pt_comb_logic(
  fft_2pt_in_t i
){
  fft_2pt_out_t o;
  // t = twiddle factor
  fft_out_t t = mul_in_out(i.omega, i.t);
  fft_out_t u = i.u;
  // calculating y[k + j]
  o.u = add_complex(u, t);
  // calculating y[k+j+n/2]
  o.t = sub_complex(u, t);
  return o;
}
#ifdef FFT_USE_HARDWARE
fft_2pt_out_t fft_2pt_hardware(fft_2pt_in_t i){
    // Write input registers contents
    mm_ctrl_regs->fft_2pt_in.t = i.t;
    mm_ctrl_regs->fft_2pt_in.u = i.u;
    mm_ctrl_regs->fft_2pt_in.omega = i.omega;
    //(takes just 1 CPU clock cycle, output ready immediately)
    // Return output register contents
    fft_2pt_out_t o;
    o.t = mm_status_regs->fft_2pt_out->t;
    o.u = mm_status_regs->fft_2pt_out->u;
    return o;
}
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
        #ifndef FFT_USE_OMEGA_LUT
        fft_in_t omega_m = exp_complex(-EXP_COMPLEX_CONST_ONE / m); // div here, sadly... can be precomputed LUT perhaps
        #endif
        
        // principle root of nth complex
        /* do this in parallel */
        for (uint32_t k = 0; k < N; k+=m)
        {   
            #ifndef FFT_USE_OMEGA_LUT
            fft_in_t omega = ONE_PLUS_0I_INIT; 
            #endif
            for (uint32_t j = 0; j < m_1_2; j++)
            {
                #ifdef FFT_USE_OMEGA_LUT
                fft_in_t omega = omega_lookup(s, j);
                #endif
                uint32_t t_index = k + j + m_1_2;
                uint32_t u_index = k + j;
                fft_2pt_in_t fft_in;
                fft_in.t = output[t_index];
                fft_in.u = output[u_index];
                fft_in.omega = omega;
                #ifdef FFT_USE_HARDWARE
                // Invoke hardware
                fft_2pt_out_t fft_out = fft_2pt_hardware(fft_in);
                #else
                // Run comb logic on CPU instead of using hardware
                fft_2pt_out_t fft_out = fft_2pt_comb_logic(fft_in);
                #endif
                output[t_index] = fft_out.t;
                output[u_index] = fft_out.u;
                #ifndef FFT_USE_OMEGA_LUT
                // updating omega, rotating the phase
                omega = mul_in(omega, omega_m);
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
