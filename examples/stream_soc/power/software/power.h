#pragma once
#include "compiler.h"
#include "uintN_t.h"
#include "../../fft/software/fft_types.h"

// https://github.com/chmike/fpsqrt/blob/master/fpsqrt.c
int32_t fixed_sqrt(int32_t v) {
    uint32_t t, q, b, r;
    r = (int32_t)v; 
    q = 0;          
    b = 0x40000000UL;
    uint1_t returned = 0;
    int32_t rv;
    if( r < 0x40000200 )
    {
        //uint32_t loop0 = 0;
        //while( b != 0x40 )
        limited_while(b != 0x40, i, 24)
        {
            t = q + b;
            if( r >= t )
            {
                r -= t;
                q = t + b; // equivalent to q += 2*b
            }
            r <<= 1;
            b >>= 1;

            //loop0++;
        }
        //printf("loop0: %d\n", loop0); // 24
        q >>= 8;
        rv = q; returned = 1; //return q;
    }
    if(~returned)
    {
        //uint32_t loop1 = 0;
        //while( b > 0x40 ) 
        limited_while((b > 0x40) & ~returned, i, 1)
        {
            t = q + b;
            if( r >= t )
            {
                r -= t;
                q = t + b; // equivalent to q += 2*b
            }
            if( (r & 0x80000000) != 0 )
            {
                q >>= 1;
                b >>= 1;
                r >>= 1;
                //uint32_t loop2 = 0;
                //while( b > 0x20 )
                limited_while(b > 0x20, j, 24)
                {
                    t = q + b;
                    if( r >= t )
                    {
                        r -= t;
                        q = t + b;
                    }
                    r <<= 1;
                    b >>= 1;

                    //loop2++;
                }
                //printf("loop2: %d\n", loop2); // 24
                //printf("loop1: %d\n", loop1); // 1
                q >>= 7;
                rv = q; returned = 1; //return q;
            }
            if(~returned){
                r <<= 1;
                b >>= 1;

                //loop1++;
            }
        }
        if(~returned){
            //printf("loop1: %d\n", loop1);
            q >>= 8;
            rv = q; returned = 1; //return q;
        }
    }
    return rv;
}

fft_data_t sample_power(fft_out_t fft_out_sample){
    //#warning "sample_power DISABLED FOR TESTING"
    //return fft_out_sample.real;
    fft_data_t re = fft_out_sample.real;
    fft_data_t im = fft_out_sample.imag;
    #ifdef FFT_TYPE_IS_FLOAT
    fft_data_t pwr2 = (re*re) + (im*im);
    fft_data_t rv = sqrtf(pwr2);
    #endif
    #ifdef FFT_TYPE_IS_FIXED
    // Scaling down >>1 since was overflowing fixed format
    fft_data_t pwr2 = mul32(re>>1,re>>1) + mul32(im>>1,im>>1);
    // Scaled back up some to account for input scale down
    fft_data_t rv = fixed_sqrt(pwr2) << 1;
    #endif
    return rv;
}

void compute_power(fft_out_t* output, fft_data_t* output_pwr, int N)
{
    for (uint32_t i = 0; i < N; i++)
    {
        output_pwr[i] = sample_power(output[i]);
    }
}