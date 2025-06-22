#pragma once
// https://github.com/chmike/fpsqrt/blob/master/fpsqrt.c
int32_t fixed_sqrt(int32_t v) {
    uint32_t t, q, b, r;
    r = (int32_t)v; 
    q = 0;          
    b = 0x40000000UL;
    if( r < 0x40000200 )
    {
        while( b != 0x40 )
        {
            t = q + b;
            if( r >= t )
            {
                r -= t;
                q = t + b; // equivalent to q += 2*b
            }
            r <<= 1;
            b >>= 1;
        }
        q >>= 8;
        return q;
    }
    while( b > 0x40 )
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
            while( b > 0x20 )
            {
                t = q + b;
                if( r >= t )
                {
                    r -= t;
                    q = t + b;
                }
                r <<= 1;
                b >>= 1;
            }
            q >>= 7;
            return q;
        }
        r <<= 1;
        b >>= 1;
    }
    q >>= 8;
    return q;
}

void compute_power(fft_out_t* output, fft_data_t* output_pwr, int N)
{
    for (uint32_t i = 0; i < N; i++)
    {
        fft_data_t re = output[i].real;
        fft_data_t im = output[i].imag;
        #ifdef FFT_TYPE_IS_FLOAT
        fft_data_t pwr2 = (re*re) + (im*im);
        output_pwr[i] = sqrtf(pwr2);
        #endif
        #ifdef FFT_TYPE_IS_FIXED
        // Scaling down >>1 since was overflowing fixed format
        fft_data_t pwr2 = mul32(re>>1,re>>1) + mul32(im>>1,im>>1);
        // Scaled back up some to account for input scale down
        output_pwr[i] = fixed_sqrt(pwr2) << 1;
        // sqrt debug:
        //float input = (float)pwr2 / (1 << 16);
        //float output = (float)output_pwr[i] / (1 << 17); // << 17 for above scaling
        //printf("sqrt(%f) = %f\n", input, output);
        #endif
    }
}