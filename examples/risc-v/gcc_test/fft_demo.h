// Dutra FFT Demo

#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct complex_t
{
    float real, imag;
}complex_t;

// Select fft data type
//#define FFT_TYPE_IS_FLOAT
#define FFT_TYPE_IS_FIXED

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

/* Q1.15 Fixed point */
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

/* Q16.16 Fixed point */
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
/// @param x   angle (with 2^15 units/circle)
/// @return    exp value (CI16)
static inline ci16_t exp_complex(int32_t x){
    ci16_t rv;
    // Old fixed point solution doesnt work, not accurate enough?
    // rv.real = icos_S4(x);  // cos first
    // rv.imag = isin_S4(x);  // then, sin... fixed bug
    #warning "exp function computation still does some float math!"
    #warning "to avoid exp func float math, convert i16 fixed point to i32 fixed point used for cordic"
    float theta = 2.0f*M_PI*(float)x/32767.0f;
    // Floating point
    //float c = cosf(theta);
    //float s = sinf(theta);
    //rv.real = (int)(32767.0f * c);
    //rv.imag = (int)(32767.0f * s);
    // New fixed point
    cordic_float_t cordic = cordic_float_mod_fixed32_n32(theta);
    //printf("theta, c, cordic.c, s, cordic.s, %f, %f, %f, %f, %f\n",
    //        theta, c, cordic.c, s, cordic.s);
    rv.real = (int)(32767.0f * cordic.c);
    rv.imag = (int)(32767.0f * cordic.s);
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

/* Based on https://en.wikipedia.org/wiki/Cooley%E2%80%93Tukey_FFT_algorithm#Data_reordering,_bit_reversal,_and_in-place_algorithms */
/* Compute Iterative Complex-FFT with N < 2^16 bins */
// Each bin is SAMPLE_RATE / NUM_POINTS (Hz) wide? TODO what about neg freqencies?
void compute_fft_cc(
    fft_in_t* input, fft_out_t* output,
    uint32_t N
){
    /* Bit-Reverse copy */
    for (uint32_t i = 0; i < N; i++)
    {
        uint32_t ri = rev(i,N);
        output[i].real = input[ri].real; // Fix here, swap order
        output[i].imag = input[ri].imag; // Fix here, swap order
    }

    /* do this sequentially ? */
    // S butterfly levels
    for (uint32_t s = 1; s < (int)ceil(log2(N) + 1.0); s++)
    {
        int32_t m = 1 << s;
        int32_t m_1_2 = m >> 1;
        // Fix here, neg. sign
        fft_in_t omega_m = exp_complex(-EXP_COMPLEX_CONST_ONE / m); // div here, sadly... can be precomputed LUT perhaps

        // Fixed the order here... wrong results before...
        // principle root of nth complex
        // root of unity. ?
        /* do this in parallel ? */
        for (uint32_t k = 0; k < N; k+=m)
        {
            fft_in_t omega = ONE_PLUS_0I_INIT; 
            for (uint32_t j = 0; j < m_1_2; j++)
            {
                // t = twiddle factor
                fft_out_t t = mul_in_out(omega, output[k + j + m_1_2]);
                fft_out_t u = output[k + j];
                // calculating y[k + j]
                output[k + j] = add_complex(u, t);
                // calculating y[k+j+n/2]
                output[k + j + m_1_2] = sub_complex(u, t);
                // updating omega, basically rotating the phase I guess
                omega = mul_in(omega, omega_m);
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
