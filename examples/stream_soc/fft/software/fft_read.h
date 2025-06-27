#pragma once
#include "fft_types.h"
#include "axi/axi_shared_bus.h"

void fft_config_result(fft_out_t* fft_out_in_dram){
  // Configure FFT result AXIS sink to write to AXI DDR at specific address
  axi_descriptor_t fft_desc; // Unused output
  mm_axi_desc_write(
    &fft_desc, 
    fft_desc_to_write, 
    MMIO_AXI0_ADDR, 
    fft_out_t, 
    fft_out_in_dram, 
    NFFT
  );
}

void fft_read_result(fft_out_t** fft_out_ptr, int* n_elems_out){
  // Read description of elements AXIS sink wrote to AXI DDR at specific address
  axi_descriptor_t fft_desc; // Unused output
  mm_axi_desc_read(
    &fft_desc,
    fft_out_t,
    fft_out_ptr, // output pointer to elements in memory
    n_elems_out,   // output number of elements in memory
    fft_desc_written, // descriptor name in MMIO
    MMIO_AXI0_ADDR  // MMIO address offset
  );
}
