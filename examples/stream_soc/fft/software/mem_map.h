#pragma once
#define FFT_OUT_AXI0_ADDR (FFT_OUT_ADDR-MMIO_AXI0_ADDR)
#define FFT_OUT_SIZE (NFFT*sizeof(fft_out_t))
