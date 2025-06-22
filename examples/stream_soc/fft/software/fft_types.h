#pragma once

#define NFFT 2048 // TODO move, not part of types?

// Select fft data type
//#define FFT_TYPE_IS_FLOAT
#define FFT_TYPE_IS_FIXED

typedef struct complex_t
{
    float real, imag;
}complex_t;

#ifdef FFT_TYPE_IS_FLOAT
#define fft_data_t float
#define fft_in_t complex_t
#define fft_out_t complex_t
#define ONE_PLUS_0I_INIT {1.0, 0.0} // 1 + 0i

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

/* Q15.16 Fixed point, 1 sign bit, 15 integer bits, 16 fraction bits = int32 */
typedef struct ci32_t
{
    int32_t real, imag;
}ci32_t;
#define fft_data_t int32_t
#define fft_in_t ci16_t
#define fft_out_t ci32_t

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
    #ifdef __PIPELINEC__
    // Work around Vivado synth bug
    // that badly trims/optimizes sign bit due to extra casts?
    int32_t rv = (a * b) >> 16;
    #else
    int32_t rv = ((int64_t)a * (int64_t)b) >> 16;
    #endif
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
#endif