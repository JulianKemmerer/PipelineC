#pragma once
#include "i2s/i2s_32b.h"
#include "axi/axi_shared_bus.h"

void i2s_read(i2s_sample_in_mem_t** samples_ptr_out, int* n_samples_out){
  // Read description of samples in memory
  axi_descriptor_t samples_desc; // Unused output
  mm_axi_desc_read(
    &samples_desc,
    i2s_sample_in_mem_t,
    samples_ptr_out, // output pointer to samples in memory
    n_samples_out,   // output number of samples in memory
    i2s_rx_out_desc, // descriptor name in MMIO
    MMIO_AXI0_ADDR  // MMIO address offset
  );
}