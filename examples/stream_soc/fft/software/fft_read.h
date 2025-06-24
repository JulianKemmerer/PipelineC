#pragma once
#include "axi/axi_shared_bus.h"
#include "risc-v/mem_map.h"

// TODO extend mm_handshake_read to use a type and size and be this entire func
void fft_read(fft_out_t** fft_out_ptr, int* n_elems_out){
  // Read description of elements in memory
  axi_descriptor_t fft_desc;
  mm_handshake_read(&fft_desc, fft_out_desc); // fft_desc = fft_out_desc
  // gets pointer to elements in AXI DDR memory
  fft_out_t* fft_out = (fft_out_t*)(fft_desc.addr + MMIO_AXI0_ADDR);
  // and number of elements (in u32 word count)
  int n_elems = (fft_desc.num_words*sizeof(uint32_t))/sizeof(fft_out_t);
  // return outputs
  *fft_out_ptr = fft_out;
  *n_elems_out = n_elems;
}