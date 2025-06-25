#pragma once
#include "fft_types.h"
#include "axi/axi_shared_bus.h"

void fft_read(fft_out_t** fft_out_ptr, int* n_elems_out){
  // Read description of elements in memory
  axi_descriptor_t fft_desc; // Unused output
  mm_axi_desc_read(
    &fft_desc,
    fft_out_t,
    fft_out_ptr, // output pointer to elements in memory
    n_elems_out,   // output number of elements in memory
    fft_out_desc, // descriptor name in MMIO
    MMIO_AXI0_ADDR  // MMIO address offset
  );
}