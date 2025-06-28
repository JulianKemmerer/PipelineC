#pragma once
// Configure i2s_axi.c to use memory mapped addr offset in CPU's AXI0 region
#define I2S_SAMPLES_ADDR (I2S_BUFFS_ADDR-MMIO_AXI0_ADDR)
#define I2S_N_SAMPLES NFFT // Match FFT size
#define I2S_N_DESC 16 // 16 is good min, since xilinx async fifo min size 16
#define I2S_BUFFS_SIZE (sizeof(i2s_sample_in_mem_t)*I2S_N_SAMPLES*I2S_N_DESC)
