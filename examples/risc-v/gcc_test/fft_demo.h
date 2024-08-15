// Dutra FFT Demo

#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* Base Types */

/* Q1.15 Fixed point */
typedef struct ci16_t
{
    int16_t real, imag;
}ci16_t;


static inline int16_t mul16(int16_t a, int16_t b){
    int16_t rv = ((int16_t)a * (int16_t)b) >> 15;
    return rv;
}

static inline ci16_t mul_ci16(ci16_t a, ci16_t b){
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

static inline int32_t mul32(int32_t a, int32_t b){
    int32_t rv = ((int64_t)a * (int64_t)b) >> 16;
    return rv;
}

static inline ci32_t mul_ci32(ci32_t a, ci32_t b){
    ci32_t rv;
    rv.real = mul32(a.real, b.real) - mul32(a.imag, b.imag);
    rv.imag = mul32(a.real, b.imag) + mul32(a.imag, b.real);
    return rv;
}

static inline ci32_t add_ci32(ci32_t a, ci32_t b){
    ci32_t rv = {a.real + b.real, a.imag + b.imag};
    return rv;
}

static inline ci32_t sub_ci32(ci32_t a, ci32_t b){
    ci32_t rv = {a.real - b.real, a.imag - b.imag};
    return rv;
}

static inline ci32_t mul_ci16_ci32(ci16_t a, ci32_t b){
    ci32_t a_e = {.real = (int32_t)a.real << 1, .imag=(int32_t)a.imag << 1};
    return mul_ci32(a_e,b);
}

/* code from https://www.coranac.com/2009/07/sines/ */
/// A sine approximation via a fourth-order cosine approx.
/// @param x   angle (with 2^15 units/circle)
/// @return     Sine value (I16)
static inline int32_t isin_S4(int32_t x)
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
}

/* code from https://www.coranac.com/2009/07/sines/ */
/// A cosine approximation via a fourth-order cosine approx.
/// @param x   angle (with 2^15 units/circle)
/// @return     Cosine value (I16)
static inline int32_t icos_S4(int32_t x)
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
}

/// Complex exponential e ^ (2 * pi * i * x)
/// @param x   angle (with 2^15 units/circle)
/// @return    exp value (CI16)
static inline ci16_t exp_taylor(int32_t x){
    ci16_t rv;
    rv.real = icos_S4(x);  // cos first
    rv.imag = isin_S4(x);  // then, sin... fixed bug
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
void compute_fft_cc(ci16_t* input, ci32_t* output, uint32_t N){
    /* Bit-Reverse copy */
    for (uint32_t i = 0; i < N; i++)
    {
        uint32_t ri = rev(i,N);
        output[ri].real = input[i].real;
        output[ri].imag = input[i].imag;
    }

    /* do this sequentially ? */
    // S butterfly levels
    for (uint32_t s = 1; s < (int)ceil(log2(N) + 1.0); s++)
    {
        int32_t m = 1 << s;
        int32_t m_1_2 = m >> 1;
        ci16_t omega_m = exp_taylor((1<<15) / m); // div here, sadly... can be precomputed LUT perhaps

        // Fixed the order here... wrong results before...
        // principle root of nth complex
        // root of unity. ?
        /* do this in parallel ? */
        for (uint32_t k = 0; k < N; k+=m)
        {
            ci16_t omega = {INT16_MAX, 0}; // 1 + 0i
            for (uint32_t j = 0; j < m_1_2; j++)
            {
                // t = twiddle factor
                ci32_t t = mul_ci16_ci32(omega, output[k + j + m_1_2]);
                ci32_t u = output[k + j];
                // calculating y[k + j]
                output[k + j] = add_ci32(u, t);
                // calculating y[k+j+n/2]
                output[k + j + m_1_2] = sub_ci32(u, t);
                // updating omega, basically rotating the phase I guess
                omega = mul_ci16(omega, omega_m);
            }
        }
    }  
}

#define NFFT (1<<6)

void color_screen(int width, int height, float* output_pwr, uint32_t N){
  for (int i = 0; i < width; i++)
  {
    for (int j = 0; j < height; j++)
    {
      // TODO use output real and scale to 255?
      printf("x,y,c,%d,%d,%d\n", i, j, 0);
    }
  }
}

/*int main(){

    // Create arrays 
    ci16_t* input = (ci16_t*)malloc(NFFT * sizeof(ci16_t));
    ci32_t* output = (ci32_t*)malloc(NFFT * sizeof(ci32_t));

    // Gen Test signal
    uint32_t Fs = (INT16_MAX+1) / NFFT;
    for (uint32_t i = 0; i < NFFT; i++)
    {
        input[i] = exp_taylor(16*i*Fs);
    }

    // apply fft 
    printf("f,v\n");
    compute_fft_cc(input, output, NFFT);

    // print results 
    for (uint32_t i = 0; i < NFFT; i++)
    {
        uint32_t j = i < (NFFT>>1) ? (NFFT>>1)+i : i-(NFFT>>1); // FFT SHIFT
        float re = (float)output[j].real / (float)INT16_MAX; // small typo fix
        float im = (float)output[j].imag / (float)INT16_MAX;
        float pwr2 = (re*re) + (im*im);
        float pwr = pwr2 > 0 ? sqrtf(pwr2) : 0;
        printf("%d, %f\n",i-(NFFT>>1),pwr); // i-(NFFT>>1) yields -NFFT/2, NFFT/2
    } 
}*/
