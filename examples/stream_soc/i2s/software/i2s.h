#pragma once
#include "i2s/i2s_32b.h"
#include "axi/axi_shared_bus.h"
#include "../../../risc-v/mem_map.h" // TODO move examples/risc-v into include/risc-v

void i2s_read(i2s_sample_in_mem_t** samples_ptr_out, int* n_samples_out){
  // Read description of samples in memory
  axi_descriptor_t samples_desc;
  mm_handshake_read(&samples_desc, i2s_rx_out_desc); // samples_desc = i2s_rx_out_desc
  // gets pointer to samples in AXI DDR memory
  i2s_sample_in_mem_t* samples = (i2s_sample_in_mem_t*)(samples_desc.addr + MMIO_AXI0_ADDR);
  // and number of samples (in u32 word count)
  int n_samples = (samples_desc.num_words*sizeof(uint32_t))/sizeof(i2s_sample_in_mem_t);
  // return outputs
  *samples_ptr_out = samples;
  *n_samples_out = n_samples;
}