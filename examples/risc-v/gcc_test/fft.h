// FFT Demo, thanks for the help Dutra!
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
#if NFFT==1024
#define LOG2_NFFT 10
#endif
static inline uint32_t rev(uint32_t v){
    uint32_t sr = 32 - LOG2_NFFT;
    #ifdef __PIPELINEC__
    v = v(0, 31); // rev of [31:0]
    #else
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
    #endif
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
uint16_t omega_s_j_to_index(uint16_t s, uint16_t j){
    // sum of 2^x from 0 to N = 2^(n+1)-1
    uint16_t num_j_elems_so_far = ((uint16_t)1<<(s-1)) - 1;
    uint16_t index = num_j_elems_so_far + j;
    return index;
}
fft_in_t omega_lookup(uint16_t s, uint16_t j){
    uint16_t index = omega_s_j_to_index(s, j);
    //printf("LOOKUP s = %d, j = %d ~= omega lut index[%d]\n", s, j, index);
    return OMEGA_LUT[index];
}
/*void print_omega_lookup(){
    printf("fft_in_t the_rom[%d] = {\n", NFFT);
    for (size_t i = 0; i < NFFT; i++)
    {
        printf("{.real=%d, .imag=%d},\n", OMEGA_LUT[i].real, OMEGA_LUT[i].imag);
    }
    printf("};\n");
}*/
#ifdef __PIPELINEC__
// PipelineC hardware hard coded ROM, see print function above
#if NFFT==1024
#pragma FUNC_LATENCY omega_lut_rom 1
fft_in_t omega_lut_rom(uint16_t i){
    static fft_in_t the_rom[1024] = {
    {.real=32767, .imag=0},
    {.real=32767, .imag=0},
    {.real=0, .imag=-32767},
    {.real=32767, .imag=0},
    {.real=23168, .imag=-23170},
    {.real=-2, .imag=-32765},
    {.real=-23169, .imag=-23166},
    {.real=32767, .imag=0},
    {.real=30271, .imag=-12539},
    {.real=23167, .imag=-23168},
    {.real=12537, .imag=-30270},
    {.real=-1, .imag=-32763},
    {.real=-12538, .imag=-30268},
    {.real=-23165, .imag=-23166},
    {.real=-30265, .imag=-12538},
    {.real=32767, .imag=0},
    {.real=32136, .imag=-6392},
    {.real=30271, .imag=-12538},
    {.real=27243, .imag=-18202},
    {.real=23168, .imag=-23167},
    {.real=18202, .imag=-27241},
    {.real=12538, .imag=-30268},
    {.real=6392, .imag=-32132},
    {.real=1, .imag=-32761},
    {.real=-6390, .imag=-32132},
    {.real=-12534, .imag=-30268},
    {.real=-18197, .imag=-27242},
    {.real=-23161, .imag=-23169},
    {.real=-27234, .imag=-18206},
    {.real=-30261, .imag=-12544},
    {.real=-32125, .imag=-6401},
    {.real=32767, .imag=0},
    {.real=32608, .imag=-3211},
    {.real=32135, .imag=-6392},
    {.real=31353, .imag=-9510},
    {.real=30269, .imag=-12537},
    {.real=28894, .imag=-15444},
    {.real=27240, .imag=-18202},
    {.real=25324, .imag=-20784},
    {.real=23165, .imag=-23166},
    {.real=20782, .imag=-25324},
    {.real=18200, .imag=-27239},
    {.real=15442, .imag=-28891},
    {.real=12536, .imag=-30265},
    {.real=9510, .imag=-31348},
    {.real=6392, .imag=-32128},
    {.real=3212, .imag=-32600},
    {.real=2, .imag=-32757},
    {.real=-3208, .imag=-32600},
    {.real=-6387, .imag=-32128},
    {.real=-9505, .imag=-31348},
    {.real=-12530, .imag=-30265},
    {.real=-15435, .imag=-28892},
    {.real=-18192, .imag=-27240},
    {.real=-20773, .imag=-25326},
    {.real=-23154, .imag=-23169},
    {.real=-25312, .imag=-20789},
    {.real=-27227, .imag=-18209},
    {.real=-28879, .imag=-15453},
    {.real=-30253, .imag=-12550},
    {.real=-31336, .imag=-9526},
    {.real=-32117, .imag=-6410},
    {.real=-32590, .imag=-3232},
    {.real=32767, .imag=0},
    {.real=32726, .imag=-1607},
    {.real=32607, .imag=-3210},
    {.real=32409, .imag=-4806},
    {.real=32133, .imag=-6390},
    {.real=31779, .imag=-7959},
    {.real=31349, .imag=-9509},
    {.real=30843, .imag=-11036},
    {.real=30263, .imag=-12536},
    {.real=29611, .imag=-14006},
    {.real=28887, .imag=-15442},
    {.real=28093, .imag=-16840},
    {.real=27232, .imag=-18197},
    {.real=26305, .imag=-19511},
    {.real=25316, .imag=-20778},
    {.real=24266, .imag=-21995},
    {.real=23157, .imag=-23159},
    {.real=21993, .imag=-24267},
    {.real=20775, .imag=-25316},
    {.real=19508, .imag=-26304},
    {.real=18194, .imag=-27229},
    {.real=16836, .imag=-28088},
    {.real=15437, .imag=-28879},
    {.real=14001, .imag=-29601},
    {.real=12532, .imag=-30251},
    {.real=11033, .imag=-30829},
    {.real=9508, .imag=-31333},
    {.real=7960, .imag=-31761},
    {.real=6393, .imag=-32113},
    {.real=4811, .imag=-32387},
    {.real=3216, .imag=-32583},
    {.real=1614, .imag=-32701},
    {.real=8, .imag=-32741},
    {.real=-1598, .imag=-32702},
    {.real=-3200, .imag=-32584},
    {.real=-4793, .imag=-32388},
    {.real=-6376, .imag=-32113},
    {.real=-7943, .imag=-31761},
    {.real=-9491, .imag=-31333},
    {.real=-11016, .imag=-30829},
    {.real=-12514, .imag=-30251},
    {.real=-13982, .imag=-29601},
    {.real=-15416, .imag=-28879},
    {.real=-16813, .imag=-28087},
    {.real=-18169, .imag=-27228},
    {.real=-19482, .imag=-26303},
    {.real=-20747, .imag=-25316},
    {.real=-21963, .imag=-24268},
    {.real=-23126, .imag=-23161},
    {.real=-24233, .imag=-21999},
    {.real=-25281, .imag=-20784},
    {.real=-26269, .imag=-19519},
    {.real=-27194, .imag=-18207},
    {.real=-28052, .imag=-16852},
    {.real=-28843, .imag=-15456},
    {.real=-29564, .imag=-14023},
    {.real=-30215, .imag=-12557},
    {.real=-30793, .imag=-11061},
    {.real=-31297, .imag=-9538},
    {.real=-31725, .imag=-7993},
    {.real=-32077, .imag=-6428},
    {.real=-32352, .imag=-4847},
    {.real=-32549, .imag=-3255},
    {.real=-32668, .imag=-1655},
    {.real=32767, .imag=0},
    {.real=32756, .imag=-804},
    {.real=32726, .imag=-1608},
    {.real=32676, .imag=-2411},
    {.real=32606, .imag=-3213},
    {.real=32517, .imag=-4013},
    {.real=32408, .imag=-4810},
    {.real=32279, .imag=-5605},
    {.real=32131, .imag=-6397},
    {.real=31964, .imag=-7184},
    {.real=31777, .imag=-7967},
    {.real=31571, .imag=-8745},
    {.real=31346, .imag=-9518},
    {.real=31102, .imag=-10285},
    {.real=30839, .imag=-11046},
    {.real=30557, .imag=-11800},
    {.real=30257, .imag=-12547},
    {.real=29939, .imag=-13286},
    {.real=29603, .imag=-14017},
    {.real=29250, .imag=-14740},
    {.real=28879, .imag=-15454},
    {.real=28490, .imag=-16158},
    {.real=28084, .imag=-16853},
    {.real=27661, .imag=-17538},
    {.real=27221, .imag=-18212},
    {.real=26765, .imag=-18874},
    {.real=26293, .imag=-19525},
    {.real=25805, .imag=-20165},
    {.real=25302, .imag=-20793},
    {.real=24783, .imag=-21408},
    {.real=24249, .imag=-22010},
    {.real=23700, .imag=-22598},
    {.real=23138, .imag=-23173},
    {.real=22562, .imag=-23734},
    {.real=21972, .imag=-24281},
    {.real=21369, .imag=-24813},
    {.real=20753, .imag=-25330},
    {.real=20125, .imag=-25832},
    {.real=19485, .imag=-26318},
    {.real=18833, .imag=-26789},
    {.real=18169, .imag=-27244},
    {.real=17494, .imag=-27681},
    {.real=16809, .imag=-28102},
    {.real=16114, .imag=-28506},
    {.real=15409, .imag=-28893},
    {.real=14695, .imag=-29263},
    {.real=13972, .imag=-29615},
    {.real=13241, .imag=-29949},
    {.real=12502, .imag=-30264},
    {.real=11755, .imag=-30561},
    {.real=11002, .imag=-30840},
    {.real=10242, .imag=-31100},
    {.real=9475, .imag=-31342},
    {.real=8702, .imag=-31565},
    {.real=7925, .imag=-31769},
    {.real=7143, .imag=-31954},
    {.real=6356, .imag=-32120},
    {.real=5565, .imag=-32266},
    {.real=4772, .imag=-32393},
    {.real=3976, .imag=-32501},
    {.real=3177, .imag=-32589},
    {.real=2376, .imag=-32657},
    {.real=1574, .imag=-32706},
    {.real=771, .imag=-32735},
    {.real=-33, .imag=-32744},
    {.real=-836, .imag=-32734},
    {.real=-1639, .imag=-32704},
    {.real=-2441, .imag=-32654},
    {.real=-3242, .imag=-32585},
    {.real=-4040, .imag=-32496},
    {.real=-4836, .imag=-32387},
    {.real=-5629, .imag=-32259},
    {.real=-6419, .imag=-32111},
    {.real=-7204, .imag=-31944},
    {.real=-7985, .imag=-31758},
    {.real=-8762, .imag=-31553},
    {.real=-9534, .imag=-31329},
    {.real=-10299, .imag=-31086},
    {.real=-11058, .imag=-30824},
    {.real=-11811, .imag=-30543},
    {.real=-12557, .imag=-30244},
    {.real=-13295, .imag=-29926},
    {.real=-14025, .imag=-29590},
    {.real=-14747, .imag=-29237},
    {.real=-15460, .imag=-28867},
    {.real=-16163, .imag=-28479},
    {.real=-16856, .imag=-28074},
    {.real=-17539, .imag=-27652},
    {.real=-18212, .imag=-27213},
    {.real=-18873, .imag=-26758},
    {.real=-19523, .imag=-26287},
    {.real=-20161, .imag=-25800},
    {.real=-20788, .imag=-25298},
    {.real=-21402, .imag=-24780},
    {.real=-22003, .imag=-24247},
    {.real=-22590, .imag=-23700},
    {.real=-23164, .imag=-23139},
    {.real=-23724, .imag=-22564},
    {.real=-24270, .imag=-21975},
    {.real=-24801, .imag=-21373},
    {.real=-25317, .imag=-20758},
    {.real=-25818, .imag=-20131},
    {.real=-26303, .imag=-19492},
    {.real=-26773, .imag=-18841},
    {.real=-27227, .imag=-18179},
    {.real=-27664, .imag=-17505},
    {.real=-28084, .imag=-16822},
    {.real=-28487, .imag=-16128},
    {.real=-28873, .imag=-15425},
    {.real=-29242, .imag=-14712},
    {.real=-29593, .imag=-13991},
    {.real=-29927, .imag=-13261},
    {.real=-30242, .imag=-12523},
    {.real=-30539, .imag=-11777},
    {.real=-30817, .imag=-11025},
    {.real=-31077, .imag=-10266},
    {.real=-31318, .imag=-9501},
    {.real=-31541, .imag=-8730},
    {.real=-31745, .imag=-7955},
    {.real=-31930, .imag=-7175},
    {.real=-32096, .imag=-6390},
    {.real=-32242, .imag=-5601},
    {.real=-32369, .imag=-4809},
    {.real=-32476, .imag=-4014},
    {.real=-32564, .imag=-3217},
    {.real=-32632, .imag=-2418},
    {.real=-32681, .imag=-1618},
    {.real=-32710, .imag=-817},
    {.real=32767, .imag=0},
    {.real=32763, .imag=-402},
    {.real=32755, .imag=-804},
    {.real=32742, .imag=-1206},
    {.real=32724, .imag=-1608},
    {.real=32701, .imag=-2010},
    {.real=32673, .imag=-2412},
    {.real=32640, .imag=-2813},
    {.real=32602, .imag=-3214},
    {.real=32559, .imag=-3614},
    {.real=32511, .imag=-4014},
    {.real=32458, .imag=-4413},
    {.real=32400, .imag=-4812},
    {.real=32337, .imag=-5210},
    {.real=32270, .imag=-5607},
    {.real=32198, .imag=-6003},
    {.real=32121, .imag=-6399},
    {.real=32039, .imag=-6794},
    {.real=31952, .imag=-7188},
    {.real=31860, .imag=-7580},
    {.real=31764, .imag=-7971},
    {.real=31663, .imag=-8361},
    {.real=31557, .imag=-8749},
    {.real=31446, .imag=-9136},
    {.real=31330, .imag=-9521},
    {.real=31210, .imag=-9905},
    {.real=31085, .imag=-10287},
    {.real=30955, .imag=-10668},
    {.real=30821, .imag=-11047},
    {.real=30682, .imag=-11425},
    {.real=30538, .imag=-11801},
    {.real=30390, .imag=-12175},
    {.real=30237, .imag=-12547},
    {.real=30080, .imag=-12917},
    {.real=29918, .imag=-13286},
    {.real=29752, .imag=-13653},
    {.real=29581, .imag=-14017},
    {.real=29406, .imag=-14379},
    {.real=29226, .imag=-14739},
    {.real=29042, .imag=-15097},
    {.real=28853, .imag=-15453},
    {.real=28660, .imag=-15806},
    {.real=28463, .imag=-16157},
    {.real=28261, .imag=-16506},
    {.real=28055, .imag=-16851},
    {.real=27845, .imag=-17194},
    {.real=27631, .imag=-17534},
    {.real=27412, .imag=-17871},
    {.real=27189, .imag=-18206},
    {.real=26962, .imag=-18538},
    {.real=26731, .imag=-18867},
    {.real=26496, .imag=-19193},
    {.real=26257, .imag=-19517},
    {.real=26014, .imag=-19838},
    {.real=25767, .imag=-20156},
    {.real=25516, .imag=-20471},
    {.real=25261, .imag=-20783},
    {.real=25003, .imag=-21091},
    {.real=24741, .imag=-21396},
    {.real=24475, .imag=-21698},
    {.real=24206, .imag=-21997},
    {.real=23934, .imag=-22292},
    {.real=23658, .imag=-22584},
    {.real=23378, .imag=-22873},
    {.real=23095, .imag=-23158},
    {.real=22808, .imag=-23440},
    {.real=22518, .imag=-23718},
    {.real=22225, .imag=-23993},
    {.real=21928, .imag=-24264},
    {.real=21628, .imag=-24532},
    {.real=21325, .imag=-24796},
    {.real=21018, .imag=-25055},
    {.real=20708, .imag=-25310},
    {.real=20395, .imag=-25562},
    {.real=20079, .imag=-25810},
    {.real=19760, .imag=-26054},
    {.real=19438, .imag=-26294},
    {.real=19113, .imag=-26530},
    {.real=18785, .imag=-26762},
    {.real=18454, .imag=-26990},
    {.real=18120, .imag=-27214},
    {.real=17784, .imag=-27434},
    {.real=17445, .imag=-27650},
    {.real=17103, .imag=-27862},
    {.real=16759, .imag=-28069},
    {.real=16412, .imag=-28272},
    {.real=16063, .imag=-28471},
    {.real=15712, .imag=-28666},
    {.real=15359, .imag=-28856},
    {.real=15003, .imag=-29042},
    {.real=14645, .imag=-29224},
    {.real=14285, .imag=-29401},
    {.real=13923, .imag=-29574},
    {.real=13559, .imag=-29742},
    {.real=13193, .imag=-29906},
    {.real=12825, .imag=-30065},
    {.real=12455, .imag=-30220},
    {.real=12083, .imag=-30370},
    {.real=11709, .imag=-30516},
    {.real=11333, .imag=-30657},
    {.real=10955, .imag=-30794},
    {.real=10576, .imag=-30926},
    {.real=10195, .imag=-31053},
    {.real=9813, .imag=-31176},
    {.real=9429, .imag=-31294},
    {.real=9044, .imag=-31407},
    {.real=8657, .imag=-31515},
    {.real=8269, .imag=-31619},
    {.real=7880, .imag=-31718},
    {.real=7490, .imag=-31812},
    {.real=7099, .imag=-31901},
    {.real=6707, .imag=-31986},
    {.real=6314, .imag=-32066},
    {.real=5920, .imag=-32141},
    {.real=5525, .imag=-32211},
    {.real=5129, .imag=-32276},
    {.real=4733, .imag=-32336},
    {.real=4336, .imag=-32392},
    {.real=3938, .imag=-32443},
    {.real=3539, .imag=-32489},
    {.real=3140, .imag=-32530},
    {.real=2740, .imag=-32566},
    {.real=2340, .imag=-32597},
    {.real=1940, .imag=-32623},
    {.real=1539, .imag=-32644},
    {.real=1138, .imag=-32660},
    {.real=737, .imag=-32671},
    {.real=336, .imag=-32678},
    {.real=-65, .imag=-32680},
    {.real=-465, .imag=-32677},
    {.real=-865, .imag=-32669},
    {.real=-1265, .imag=-32656},
    {.real=-1665, .imag=-32638},
    {.real=-2065, .imag=-32615},
    {.real=-2465, .imag=-32587},
    {.real=-2864, .imag=-32554},
    {.real=-3263, .imag=-32516},
    {.real=-3661, .imag=-32473},
    {.real=-4059, .imag=-32426},
    {.real=-4456, .imag=-32374},
    {.real=-4853, .imag=-32317},
    {.real=-5249, .imag=-32255},
    {.real=-5644, .imag=-32188},
    {.real=-6038, .imag=-32116},
    {.real=-6432, .imag=-32039},
    {.real=-6825, .imag=-31958},
    {.real=-7217, .imag=-31872},
    {.real=-7608, .imag=-31781},
    {.real=-7997, .imag=-31685},
    {.real=-8385, .imag=-31584},
    {.real=-8771, .imag=-31479},
    {.real=-9156, .imag=-31369},
    {.real=-9539, .imag=-31254},
    {.real=-9921, .imag=-31134},
    {.real=-10301, .imag=-31010},
    {.real=-10680, .imag=-30881},
    {.real=-11057, .imag=-30747},
    {.real=-11433, .imag=-30609},
    {.real=-11807, .imag=-30466},
    {.real=-12179, .imag=-30319},
    {.real=-12549, .imag=-30167},
    {.real=-12918, .imag=-30011},
    {.real=-13285, .imag=-29850},
    {.real=-13650, .imag=-29685},
    {.real=-14013, .imag=-29515},
    {.real=-14374, .imag=-29341},
    {.real=-14732, .imag=-29162},
    {.real=-15088, .imag=-28979},
    {.real=-15442, .imag=-28791},
    {.real=-15794, .imag=-28599},
    {.real=-16143, .imag=-28403},
    {.real=-16490, .imag=-28202},
    {.real=-16833, .imag=-27997},
    {.real=-17174, .imag=-27788},
    {.real=-17512, .imag=-27575},
    {.real=-17848, .imag=-27358},
    {.real=-18181, .imag=-27137},
    {.real=-18511, .imag=-26911},
    {.real=-18839, .imag=-26681},
    {.real=-19164, .imag=-26447},
    {.real=-19486, .imag=-26209},
    {.real=-19805, .imag=-25967},
    {.real=-20121, .imag=-25722},
    {.real=-20434, .imag=-25473},
    {.real=-20744, .imag=-25220},
    {.real=-21051, .imag=-24963},
    {.real=-21355, .imag=-24702},
    {.real=-21656, .imag=-24438},
    {.real=-21953, .imag=-24171},
    {.real=-22247, .imag=-23900},
    {.real=-22538, .imag=-23626},
    {.real=-22825, .imag=-23348},
    {.real=-23109, .imag=-23066},
    {.real=-23389, .imag=-22781},
    {.real=-23666, .imag=-22493},
    {.real=-23939, .imag=-22201},
    {.real=-24209, .imag=-21906},
    {.real=-24475, .imag=-21608},
    {.real=-24738, .imag=-21306},
    {.real=-24996, .imag=-21001},
    {.real=-25250, .imag=-20693},
    {.real=-25500, .imag=-20382},
    {.real=-25747, .imag=-20068},
    {.real=-25990, .imag=-19751},
    {.real=-26229, .imag=-19431},
    {.real=-26464, .imag=-19108},
    {.real=-26695, .imag=-18782},
    {.real=-26922, .imag=-18453},
    {.real=-27145, .imag=-18121},
    {.real=-27364, .imag=-17786},
    {.real=-27579, .imag=-17449},
    {.real=-27790, .imag=-17109},
    {.real=-27996, .imag=-16767},
    {.real=-28198, .imag=-16422},
    {.real=-28396, .imag=-16075},
    {.real=-28590, .imag=-15726},
    {.real=-28779, .imag=-15375},
    {.real=-28964, .imag=-15021},
    {.real=-29145, .imag=-14665},
    {.real=-29321, .imag=-14307},
    {.real=-29493, .imag=-13947},
    {.real=-29661, .imag=-13585},
    {.real=-29824, .imag=-13221},
    {.real=-29983, .imag=-12855},
    {.real=-30137, .imag=-12487},
    {.real=-30287, .imag=-12117},
    {.real=-30432, .imag=-11745},
    {.real=-30573, .imag=-11371},
    {.real=-30709, .imag=-10995},
    {.real=-30840, .imag=-10618},
    {.real=-30967, .imag=-10239},
    {.real=-31089, .imag=-9859},
    {.real=-31206, .imag=-9477},
    {.real=-31319, .imag=-9094},
    {.real=-31427, .imag=-8709},
    {.real=-31530, .imag=-8323},
    {.real=-31629, .imag=-7936},
    {.real=-31723, .imag=-7548},
    {.real=-31812, .imag=-7159},
    {.real=-31896, .imag=-6769},
    {.real=-31976, .imag=-6378},
    {.real=-32051, .imag=-5986},
    {.real=-32121, .imag=-5593},
    {.real=-32186, .imag=-5199},
    {.real=-32246, .imag=-4805},
    {.real=-32301, .imag=-4410},
    {.real=-32352, .imag=-4014},
    {.real=-32398, .imag=-3618},
    {.real=-32439, .imag=-3221},
    {.real=-32475, .imag=-2824},
    {.real=-32506, .imag=-2426},
    {.real=-32532, .imag=-2028},
    {.real=-32553, .imag=-1629},
    {.real=-32569, .imag=-1230},
    {.real=-32581, .imag=-831},
    {.real=-32588, .imag=-432},
    {.real=32767, .imag=0},
    {.real=32765, .imag=-201},
    {.real=32762, .imag=-402},
    {.real=32758, .imag=-603},
    {.real=32753, .imag=-804},
    {.real=32747, .imag=-1005},
    {.real=32739, .imag=-1206},
    {.real=32730, .imag=-1407},
    {.real=32720, .imag=-1608},
    {.real=32709, .imag=-1809},
    {.real=32696, .imag=-2010},
    {.real=32682, .imag=-2211},
    {.real=32667, .imag=-2412},
    {.real=32651, .imag=-2613},
    {.real=32633, .imag=-2814},
    {.real=32614, .imag=-3015},
    {.real=32594, .imag=-3216},
    {.real=32573, .imag=-3416},
    {.real=32551, .imag=-3616},
    {.real=32527, .imag=-3816},
    {.real=32502, .imag=-4016},
    {.real=32476, .imag=-4216},
    {.real=32449, .imag=-4416},
    {.real=32420, .imag=-4616},
    {.real=32390, .imag=-4815},
    {.real=32359, .imag=-5014},
    {.real=32327, .imag=-5213},
    {.real=32294, .imag=-5412},
    {.real=32259, .imag=-5611},
    {.real=32223, .imag=-5809},
    {.real=32186, .imag=-6007},
    {.real=32148, .imag=-6205},
    {.real=32108, .imag=-6403},
    {.real=32067, .imag=-6600},
    {.real=32025, .imag=-6797},
    {.real=31982, .imag=-6994},
    {.real=31938, .imag=-7191},
    {.real=31892, .imag=-7387},
    {.real=31845, .imag=-7583},
    {.real=31797, .imag=-7779},
    {.real=31748, .imag=-7975},
    {.real=31698, .imag=-8170},
    {.real=31646, .imag=-8365},
    {.real=31593, .imag=-8560},
    {.real=31539, .imag=-8754},
    {.real=31484, .imag=-8948},
    {.real=31428, .imag=-9142},
    {.real=31370, .imag=-9335},
    {.real=31311, .imag=-9528},
    {.real=31251, .imag=-9721},
    {.real=31190, .imag=-9913},
    {.real=31128, .imag=-10105},
    {.real=31065, .imag=-10296},
    {.real=31000, .imag=-10487},
    {.real=30934, .imag=-10678},
    {.real=30867, .imag=-10868},
    {.real=30799, .imag=-11058},
    {.real=30730, .imag=-11247},
    {.real=30660, .imag=-11436},
    {.real=30588, .imag=-11625},
    {.real=30515, .imag=-11813},
    {.real=30441, .imag=-12001},
    {.real=30366, .imag=-12188},
    {.real=30290, .imag=-12375},
    {.real=30213, .imag=-12561},
    {.real=30134, .imag=-12747},
    {.real=30054, .imag=-12932},
    {.real=29973, .imag=-13117},
    {.real=29891, .imag=-13301},
    {.real=29808, .imag=-13485},
    {.real=29724, .imag=-13668},
    {.real=29639, .imag=-13851},
    {.real=29553, .imag=-14033},
    {.real=29465, .imag=-14215},
    {.real=29376, .imag=-14396},
    {.real=29286, .imag=-14577},
    {.real=29195, .imag=-14757},
    {.real=29103, .imag=-14937},
    {.real=29010, .imag=-15116},
    {.real=28916, .imag=-15294},
    {.real=28821, .imag=-15472},
    {.real=28725, .imag=-15649},
    {.real=28628, .imag=-15826},
    {.real=28529, .imag=-16002},
    {.real=28429, .imag=-16177},
    {.real=28328, .imag=-16352},
    {.real=28226, .imag=-16526},
    {.real=28123, .imag=-16699},
    {.real=28019, .imag=-16871},
    {.real=27914, .imag=-17042},
    {.real=27808, .imag=-17213},
    {.real=27701, .imag=-17383},
    {.real=27593, .imag=-17552},
    {.real=27484, .imag=-17721},
    {.real=27374, .imag=-17889},
    {.real=27263, .imag=-18056},
    {.real=27151, .imag=-18223},
    {.real=27038, .imag=-18389},
    {.real=26924, .imag=-18554},
    {.real=26809, .imag=-18719},
    {.real=26693, .imag=-18883},
    {.real=26576, .imag=-19046},
    {.real=26458, .imag=-19209},
    {.real=26339, .imag=-19371},
    {.real=26219, .imag=-19532},
    {.real=26098, .imag=-19692},
    {.real=25976, .imag=-19852},
    {.real=25853, .imag=-20011},
    {.real=25729, .imag=-20169},
    {.real=25604, .imag=-20326},
    {.real=25478, .imag=-20483},
    {.real=25351, .imag=-20639},
    {.real=25223, .imag=-20794},
    {.real=25094, .imag=-20948},
    {.real=24964, .imag=-21101},
    {.real=24833, .imag=-21254},
    {.real=24701, .imag=-21406},
    {.real=24568, .imag=-21557},
    {.real=24434, .imag=-21707},
    {.real=24299, .imag=-21856},
    {.real=24163, .imag=-22005},
    {.real=24027, .imag=-22153},
    {.real=23890, .imag=-22300},
    {.real=23752, .imag=-22446},
    {.real=23613, .imag=-22591},
    {.real=23473, .imag=-22735},
    {.real=23332, .imag=-22878},
    {.real=23190, .imag=-23021},
    {.real=23047, .imag=-23163},
    {.real=22903, .imag=-23304},
    {.real=22759, .imag=-23444},
    {.real=22614, .imag=-23583},
    {.real=22468, .imag=-23721},
    {.real=22321, .imag=-23858},
    {.real=22173, .imag=-23994},
    {.real=22024, .imag=-24130},
    {.real=21874, .imag=-24265},
    {.real=21724, .imag=-24399},
    {.real=21573, .imag=-24532},
    {.real=21421, .imag=-24664},
    {.real=21268, .imag=-24795},
    {.real=21114, .imag=-24925},
    {.real=20960, .imag=-25054},
    {.real=20805, .imag=-25182},
    {.real=20649, .imag=-25309},
    {.real=20492, .imag=-25435},
    {.real=20334, .imag=-25560},
    {.real=20176, .imag=-25684},
    {.real=20017, .imag=-25807},
    {.real=19857, .imag=-25929},
    {.real=19696, .imag=-26050},
    {.real=19535, .imag=-26170},
    {.real=19373, .imag=-26289},
    {.real=19210, .imag=-26407},
    {.real=19047, .imag=-26524},
    {.real=18883, .imag=-26640},
    {.real=18718, .imag=-26755},
    {.real=18552, .imag=-26869},
    {.real=18386, .imag=-26982},
    {.real=18219, .imag=-27094},
    {.real=18051, .imag=-27205},
    {.real=17883, .imag=-27315},
    {.real=17714, .imag=-27424},
    {.real=17544, .imag=-27532},
    {.real=17374, .imag=-27639},
    {.real=17203, .imag=-27745},
    {.real=17031, .imag=-27850},
    {.real=16859, .imag=-27954},
    {.real=16686, .imag=-28057},
    {.real=16512, .imag=-28159},
    {.real=16338, .imag=-28260},
    {.real=16164, .imag=-28360},
    {.real=15990, .imag=-28459},
    {.real=15815, .imag=-28557},
    {.real=15639, .imag=-28654},
    {.real=15463, .imag=-28749},
    {.real=15286, .imag=-28843},
    {.real=15109, .imag=-28936},
    {.real=14931, .imag=-29028},
    {.real=14752, .imag=-29119},
    {.real=14573, .imag=-29209},
    {.real=14393, .imag=-29298},
    {.real=14213, .imag=-29386},
    {.real=14032, .imag=-29473},
    {.real=13851, .imag=-29559},
    {.real=13669, .imag=-29643},
    {.real=13487, .imag=-29726},
    {.real=13304, .imag=-29808},
    {.real=13121, .imag=-29889},
    {.real=12937, .imag=-29969},
    {.real=12753, .imag=-30048},
    {.real=12568, .imag=-30126},
    {.real=12383, .imag=-30203},
    {.real=12197, .imag=-30278},
    {.real=12011, .imag=-30352},
    {.real=11824, .imag=-30425},
    {.real=11637, .imag=-30497},
    {.real=11449, .imag=-30568},
    {.real=11261, .imag=-30638},
    {.real=11073, .imag=-30707},
    {.real=10884, .imag=-30774},
    {.real=10695, .imag=-30840},
    {.real=10505, .imag=-30905},
    {.real=10315, .imag=-30969},
    {.real=10125, .imag=-31032},
    {.real=9934, .imag=-31094},
    {.real=9743, .imag=-31154},
    {.real=9551, .imag=-31213},
    {.real=9359, .imag=-31271},
    {.real=9167, .imag=-31328},
    {.real=8974, .imag=-31384},
    {.real=8781, .imag=-31439},
    {.real=8588, .imag=-31492},
    {.real=8394, .imag=-31544},
    {.real=8200, .imag=-31595},
    {.real=8006, .imag=-31645},
    {.real=7811, .imag=-31694},
    {.real=7616, .imag=-31741},
    {.real=7421, .imag=-31787},
    {.real=7226, .imag=-31832},
    {.real=7030, .imag=-31876},
    {.real=6834, .imag=-31919},
    {.real=6638, .imag=-31960},
    {.real=6441, .imag=-32000},
    {.real=6244, .imag=-32039},
    {.real=6047, .imag=-32077},
    {.real=5850, .imag=-32114},
    {.real=5653, .imag=-32149},
    {.real=5455, .imag=-32183},
    {.real=5257, .imag=-32216},
    {.real=5059, .imag=-32248},
    {.real=4861, .imag=-32279},
    {.real=4662, .imag=-32308},
    {.real=4463, .imag=-32336},
    {.real=4264, .imag=-32363},
    {.real=4065, .imag=-32389},
    {.real=3866, .imag=-32413},
    {.real=3667, .imag=-32436},
    {.real=3468, .imag=-32458},
    {.real=3268, .imag=-32479},
    {.real=3068, .imag=-32499},
    {.real=2868, .imag=-32517},
    {.real=2668, .imag=-32534},
    {.real=2468, .imag=-32550},
    {.real=2268, .imag=-32565},
    {.real=2068, .imag=-32578},
    {.real=1868, .imag=-32590},
    {.real=1668, .imag=-32601},
    {.real=1468, .imag=-32611},
    {.real=1267, .imag=-32620},
    {.real=1066, .imag=-32627},
    {.real=865, .imag=-32633},
    {.real=664, .imag=-32638},
    {.real=463, .imag=-32642},
    {.real=262, .imag=-32644},
    {.real=61, .imag=-32645},
    {.real=-140, .imag=-32645},
    {.real=-340, .imag=-32644},
    {.real=-540, .imag=-32641},
    {.real=-740, .imag=-32637},
    {.real=-940, .imag=-32632},
    {.real=-1140, .imag=-32626},
    {.real=-1340, .imag=-32619},
    {.real=-1540, .imag=-32610},
    {.real=-1740, .imag=-32600},
    {.real=-1939, .imag=-32589},
    {.real=-2138, .imag=-32577},
    {.real=-2337, .imag=-32563},
    {.real=-2536, .imag=-32548},
    {.real=-2735, .imag=-32532},
    {.real=-2934, .imag=-32515},
    {.real=-3133, .imag=-32497},
    {.real=-3332, .imag=-32477},
    {.real=-3531, .imag=-32456},
    {.real=-3730, .imag=-32434},
    {.real=-3928, .imag=-32411},
    {.real=-4126, .imag=-32386},
    {.real=-4324, .imag=-32360},
    {.real=-4522, .imag=-32333},
    {.real=-4720, .imag=-32305},
    {.real=-4918, .imag=-32276},
    {.real=-5115, .imag=-32245},
    {.real=-5312, .imag=-32213},
    {.real=-5509, .imag=-32180},
    {.real=-5706, .imag=-32146},
    {.real=-5903, .imag=-32110},
    {.real=-6099, .imag=-32073},
    {.real=-6295, .imag=-32035},
    {.real=-6491, .imag=-31996},
    {.real=-6687, .imag=-31956},
    {.real=-6883, .imag=-31914},
    {.real=-7078, .imag=-31871},
    {.real=-7273, .imag=-31827},
    {.real=-7468, .imag=-31782},
    {.real=-7662, .imag=-31736},
    {.real=-7856, .imag=-31689},
    {.real=-8050, .imag=-31640},
    {.real=-8244, .imag=-31590},
    {.real=-8437, .imag=-31539},
    {.real=-8630, .imag=-31487},
    {.real=-8823, .imag=-31434},
    {.real=-9015, .imag=-31379},
    {.real=-9207, .imag=-31323},
    {.real=-9399, .imag=-31266},
    {.real=-9590, .imag=-31208},
    {.real=-9781, .imag=-31149},
    {.real=-9972, .imag=-31089},
    {.real=-10162, .imag=-31027},
    {.real=-10352, .imag=-30964},
    {.real=-10541, .imag=-30900},
    {.real=-10730, .imag=-30835},
    {.real=-10919, .imag=-30769},
    {.real=-11107, .imag=-30702},
    {.real=-11295, .imag=-30633},
    {.real=-11482, .imag=-30563},
    {.real=-11669, .imag=-30492},
    {.real=-11856, .imag=-30420},
    {.real=-12042, .imag=-30347},
    {.real=-12228, .imag=-30273},
    {.real=-12413, .imag=-30197},
    {.real=-12598, .imag=-30120},
    {.real=-12782, .imag=-30042},
    {.real=-12966, .imag=-29963},
    {.real=-13149, .imag=-29883},
    {.real=-13332, .imag=-29802},
    {.real=-13514, .imag=-29720},
    {.real=-13696, .imag=-29637},
    {.real=-13877, .imag=-29552},
    {.real=-14058, .imag=-29466},
    {.real=-14238, .imag=-29379},
    {.real=-14418, .imag=-29291},
    {.real=-14597, .imag=-29202},
    {.real=-14776, .imag=-29112},
    {.real=-14954, .imag=-29021},
    {.real=-15132, .imag=-28929},
    {.real=-15309, .imag=-28836},
    {.real=-15485, .imag=-28742},
    {.real=-15661, .imag=-28647},
    {.real=-15836, .imag=-28550},
    {.real=-16011, .imag=-28452},
    {.real=-16185, .imag=-28353},
    {.real=-16358, .imag=-28253},
    {.real=-16531, .imag=-28152},
    {.real=-16702, .imag=-28050},
    {.real=-16873, .imag=-27947},
    {.real=-17043, .imag=-27843},
    {.real=-17212, .imag=-27738},
    {.real=-17381, .imag=-27632},
    {.real=-17549, .imag=-27525},
    {.real=-17716, .imag=-27417},
    {.real=-17883, .imag=-27308},
    {.real=-18049, .imag=-27198},
    {.real=-18214, .imag=-27087},
    {.real=-18379, .imag=-26975},
    {.real=-18543, .imag=-26862},
    {.real=-18706, .imag=-26748},
    {.real=-18869, .imag=-26633},
    {.real=-19031, .imag=-26517},
    {.real=-19192, .imag=-26400},
    {.real=-19352, .imag=-26282},
    {.real=-19512, .imag=-26163},
    {.real=-19671, .imag=-26043},
    {.real=-19829, .imag=-25922},
    {.real=-19987, .imag=-25800},
    {.real=-20144, .imag=-25677},
    {.real=-20300, .imag=-25553},
    {.real=-20455, .imag=-25428},
    {.real=-20609, .imag=-25302},
    {.real=-20763, .imag=-25175},
    {.real=-20916, .imag=-25047},
    {.real=-21068, .imag=-24918},
    {.real=-21219, .imag=-24788},
    {.real=-21370, .imag=-24657},
    {.real=-21520, .imag=-24525},
    {.real=-21669, .imag=-24392},
    {.real=-21817, .imag=-24259},
    {.real=-21964, .imag=-24125},
    {.real=-22110, .imag=-23990},
    {.real=-22256, .imag=-23854},
    {.real=-22401, .imag=-23717},
    {.real=-22545, .imag=-23579},
    {.real=-22688, .imag=-23440},
    {.real=-22830, .imag=-23300},
    {.real=-22971, .imag=-23159},
    {.real=-23112, .imag=-23018},
    {.real=-23252, .imag=-22876},
    {.real=-23391, .imag=-22733},
    {.real=-23529, .imag=-22589},
    {.real=-23666, .imag=-22444},
    {.real=-23802, .imag=-22298},
    {.real=-23937, .imag=-22151},
    {.real=-24071, .imag=-22004},
    {.real=-24204, .imag=-21856},
    {.real=-24337, .imag=-21707},
    {.real=-24469, .imag=-21557},
    {.real=-24600, .imag=-21406},
    {.real=-24730, .imag=-21255},
    {.real=-24859, .imag=-21103},
    {.real=-24987, .imag=-20950},
    {.real=-25114, .imag=-20796},
    {.real=-25240, .imag=-20641},
    {.real=-25365, .imag=-20486},
    {.real=-25489, .imag=-20330},
    {.real=-25612, .imag=-20173},
    {.real=-25734, .imag=-20015},
    {.real=-25855, .imag=-19857},
    {.real=-25975, .imag=-19698},
    {.real=-26094, .imag=-19538},
    {.real=-26212, .imag=-19377},
    {.real=-26329, .imag=-19216},
    {.real=-26445, .imag=-19054},
    {.real=-26560, .imag=-18891},
    {.real=-26674, .imag=-18728},
    {.real=-26787, .imag=-18564},
    {.real=-26899, .imag=-18399},
    {.real=-27010, .imag=-18234},
    {.real=-27120, .imag=-18068},
    {.real=-27229, .imag=-17901},
    {.real=-27337, .imag=-17733},
    {.real=-27444, .imag=-17565},
    {.real=-27550, .imag=-17396},
    {.real=-27655, .imag=-17227},
    {.real=-27759, .imag=-17057},
    {.real=-27862, .imag=-16886},
    {.real=-27964, .imag=-16715},
    {.real=-28065, .imag=-16543},
    {.real=-28165, .imag=-16370},
    {.real=-28264, .imag=-16198},
    {.real=-28362, .imag=-16025},
    {.real=-28459, .imag=-15852},
    {.real=-28555, .imag=-15678},
    {.real=-28650, .imag=-15503},
    {.real=-28744, .imag=-15328},
    {.real=-28837, .imag=-15152},
    {.real=-28928, .imag=-14976},
    {.real=-29018, .imag=-14799},
    {.real=-29107, .imag=-14622},
    {.real=-29195, .imag=-14444},
    {.real=-29282, .imag=-14265},
    {.real=-29368, .imag=-14086},
    {.real=-29453, .imag=-13906},
    {.real=-29537, .imag=-13726},
    {.real=-29620, .imag=-13545},
    {.real=-29702, .imag=-13364},
    {.real=-29782, .imag=-13182},
    {.real=-29861, .imag=-13000},
    {.real=-29939, .imag=-12817},
    {.real=-30016, .imag=-12634},
    {.real=-30092, .imag=-12450},
    {.real=-30167, .imag=-12266},
    {.real=-30241, .imag=-12081},
    {.real=-30314, .imag=-11896},
    {.real=-30385, .imag=-11711},
    {.real=-30455, .imag=-11525},
    {.real=-30524, .imag=-11339},
    {.real=-30592, .imag=-11152},
    {.real=-30659, .imag=-10965},
    {.real=-30725, .imag=-10777},
    {.real=-30790, .imag=-10589},
    {.real=-30853, .imag=-10401},
    {.real=-30915, .imag=-10212},
    {.real=-30976, .imag=-10023},
    {.real=-31036, .imag=-9833},
    {.real=-31095, .imag=-9643},
    {.real=-31153, .imag=-9453},
    {.real=-31209, .imag=-9262},
    {.real=-31264, .imag=-9071},
    {.real=-31318, .imag=-8880},
    {.real=-31371, .imag=-8688},
    {.real=-31423, .imag=-8496},
    {.real=-31474, .imag=-8304},
    {.real=-31523, .imag=-8111},
    {.real=-31571, .imag=-7918},
    {.real=-31618, .imag=-7725},
    {.real=-31664, .imag=-7532},
    {.real=-31709, .imag=-7338},
    {.real=-31753, .imag=-7144},
    {.real=-31795, .imag=-6950},
    {.real=-31836, .imag=-6755},
    {.real=-31876, .imag=-6560},
    {.real=-31915, .imag=-6365},
    {.real=-31953, .imag=-6170},
    {.real=-31989, .imag=-5974},
    {.real=-32024, .imag=-5778},
    {.real=-32058, .imag=-5582},
    {.real=-32091, .imag=-5386},
    {.real=-32123, .imag=-5190},
    {.real=-32153, .imag=-4993},
    {.real=-32182, .imag=-4796},
    {.real=-32210, .imag=-4599},
    {.real=-32237, .imag=-4402},
    {.real=-32263, .imag=-4205},
    {.real=-32287, .imag=-4008},
    {.real=-32310, .imag=-3810},
    {.real=-32332, .imag=-3612},
    {.real=-32353, .imag=-3414},
    {.real=-32372, .imag=-3216},
    {.real=-32390, .imag=-3018},
    {.real=-32407, .imag=-2820},
    {.real=-32423, .imag=-2622},
    {.real=-32438, .imag=-2424},
    {.real=-32451, .imag=-2226},
    {.real=-32463, .imag=-2027},
    {.real=-32474, .imag=-1828},
    {.real=-32484, .imag=-1629},
    {.real=-32492, .imag=-1430},
    {.real=-32499, .imag=-1231},
    {.real=-32505, .imag=-1032},
    {.real=-32510, .imag=-833},
    {.real=-32514, .imag=-634},
    {.real=-32516, .imag=-435},
    {.real=-32517, .imag=-236},
    {.real=0, .imag=0}
    };
    fft_in_t NULL_WR_DATA;
    // _1 cycle of latency
    return the_rom_RAM_SP_RF_1(i, NULL_WR_DATA, 0);
}
#endif
#else
// Fake rom for software
fft_in_t omega_lut_rom(uint16_t i){
    return OMEGA_LUT[i];
}
#endif
#endif

// Hardware PipelineC compilable pipeline for the inner loop math of fft algorithm
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
/* // t = twiddle factor
fft_out_t t = mul_in_out(omega, output[t_index]);
fft_out_t u = output[u_index];
// calculating y[k + j]
output[u_index] = add_complex(u, t);
// calculating y[k+j+n/2]
output[t_index] = sub_complex(u, t);*/
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

typedef struct fft_2pt_w_omega_lut_in_t
{
  fft_out_t t;
  fft_out_t u;
  uint16_t s;
  uint16_t j;
}fft_2pt_w_omega_lut_in_t;
fft_2pt_out_t fft_2pt_w_omega_lut(
  fft_2pt_w_omega_lut_in_t i
){
    // Compute omega index
    uint16_t index = omega_s_j_to_index(i.s, i.j);

    // Omega lookup
    fft_in_t omega = omega_lut_rom(index);

    // 2 point fft
    fft_2pt_in_t fft_2pt_in;
    fft_2pt_in.t = i.t;
    fft_2pt_in.u = i.u;
    fft_2pt_in.omega = omega;
    fft_2pt_out_t fft_2pt_out = fft_2pt_comb_logic(fft_2pt_in);
    return fft_2pt_out;
}

typedef struct fft_iters_t{
    uint32_t s;
    uint32_t k;
    uint32_t j;
}fft_iters_t;
#if NFFT==1024
#define CEIL_LOG2_NFFT_PLUS_1 (LOG2_NFFT+1)
#endif
uint1_t s_last(fft_iters_t skj){
    return (skj.s == (CEIL_LOG2_NFFT_PLUS_1-1));
}
uint1_t k_last(fft_iters_t skj){
    uint32_t m = (uint32_t)1 << skj.s;
    return (skj.k == (NFFT-m));
}
uint1_t j_last(fft_iters_t skj){
    uint32_t m = (uint32_t)1 << skj.s;
    uint32_t m_1_2 = m >> 1;
    return (skj.j == (m_1_2-1));
}
#define FFT_ITERS_NULL_INIT {.s=1, .k=0, .j=0}
fft_iters_t FFT_ITERS_NULL = FFT_ITERS_NULL_INIT;
fft_iters_t next_iters(fft_iters_t skj){
    if(j_last(skj)){
        skj.j = 0;
        if(k_last(skj)){
            skj.k = 0;
            if(s_last(skj)){
                skj.s = 1;
            }else{
                skj.s += 1;
            }
        }else{
            uint32_t m = (uint32_t)1 << skj.s;
            skj.k += m;
        }
    }else{
        skj.j += 1;
    }
    return skj;
}
uint1_t last_iter(fft_iters_t skj){ 
    return s_last(skj) && k_last(skj) && j_last(skj);
}