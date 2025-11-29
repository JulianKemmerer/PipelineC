#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#include <stddef.h>
#endif

// TODO organize includes
#include "vga/pixel.h"
#include "../../frame_buffers/software/frame_buf.h"
#include "axi/axi_shared_bus.h" // For axi_descriptor_t
#include "risc-v/mem_map.h" // For mm_handshake_read
#include "../../i2s/software/mem_map.h"
#include "../../fft/software/mem_map.h"
#include "../../fft/software/fft_types.h"
#include "../../dvp/software/sccb_types.h"

// Define bounds for IMEM, DMEM, and MMIO
// Needs to match link.ld (TODO how to share variables?)
#define DMEM_ADDR_BIT_CHECK 30
#define DMEM_BASE_ADDR ((uint32_t)((uint32_t)1<<DMEM_ADDR_BIT_CHECK))
#define DMEM_SIZE 32768 // Must be decimal constant since VHDL+C literal
#define IMEM_SIZE 65536 // Must be decimal constant since VHDL+C literal
// Any addresses this high up will be mmio
#define MEM_MAP_ADDR_BIT_CHECK 31
#define MEM_MAP_BASE_ADDR ((uint32_t)((uint32_t)1<<MEM_MAP_ADDR_BIT_CHECK))

// Registers are mapped differently than BRAM, different from AXI RAMs, etc
// easiest to write memory mapped objects for each storage type
// since then only need to handle each storage type roughly once.

// Not using attribute packed for now, so manually dont use ints smaller than 32b...

// OG regs for top IO
typedef struct mm_ctrl_regs_t{ 
  uint32_t led; // Only 4 bits used, see above note rounding to 32b
}mm_ctrl_regs_t;
typedef struct mm_status_regs_t{ 
  uint32_t button; // Only 4 bits used, see above note rounding to 32b
  uint32_t cpu_clock;
}mm_status_regs_t;

typedef struct mm_regs_t{ 
  mm_ctrl_regs_t ctrl;
  #include "../../dvp/software/sccb_ctrl_regs.h"
  mm_status_regs_t status;
  //uint32_t i2s_rx_out_desc_overflow; // Single bit
  #include "../../dvp/software/sccb_status_regs.h"
  axi_descriptor_t i2s_rx_desc_to_write;
  axi_descriptor_t i2s_rx_desc_written;
  //
  // I2S TX unused for now axi_descriptor_t i2s_tx_desc_to_read;
  // I2S TX unused for now axi_descriptor_t i2s_tx_desc_read_from;
  //
  axi_descriptor_t fft_desc_to_write;
  axi_descriptor_t fft_desc_written;
  //
  #include "../../dvp/software/sccb_handshake_datas.h"
  uint32_t i2s_rx_desc_to_write_valid;
  uint32_t i2s_rx_desc_written_valid;
  //
  // I2S TX unused for now uint32_t i2s_tx_desc_to_read_valid;
  // I2S TX unused for now uint32_t i2s_tx_desc_read_from_valid;
  //
  uint32_t fft_desc_to_write_valid;
  uint32_t fft_desc_written_valid;
  //
  #include "../../dvp/software/sccb_handshake_valids.h"
}mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_regs_t_bytes_t.h"
#endif
#define MM_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_regs_t* mm_regs = (mm_regs_t*)MM_REGS_ADDR;
// LED (copying old def)
static volatile uint32_t* LED = (uint32_t*)(MM_REGS_ADDR + offsetof(mm_regs_t, ctrl) + offsetof(mm_ctrl_regs_t, led));//&(mm_regs->led);
#define MM_REGS_END_ADDR (MM_REGS_ADDR+sizeof(mm_regs_t))

// Handshake hardware helper macros

#define HANDSHAKE_MM_READ(regs, hs_name, stream_in, stream_ready_out)\
stream_ready_out = ~regs.hs_name##_valid;\
if(stream_ready_out & stream_in.valid){\
  regs.hs_name = stream_in.data;\
  regs.hs_name##_valid = 1;\
}

#define HANDSHAKE_MM_WRITE(stream_out, stream_ready_in, regs, hs_name)\
stream_out.data = regs.hs_name;\
stream_out.valid = regs.hs_name##_valid;\
if(stream_out.valid & stream_ready_in){\
    regs.hs_name##_valid = 0;\
}

// Read handshake helper macros

#define mm_handshake_read(out_ptr, hs_name) \
/* Wait for valid data to show up */ \
while(!mm_regs->hs_name##_valid){} \
/* Copy the data to output */ \
*(out_ptr) = mm_regs->hs_name; \
/* Signal done with data */ \
mm_regs->hs_name##_valid = 0

#define mm_handshake_try_read(success_ptr, out_ptr, hs_name) \
*(success_ptr) = 0;\
if(mm_regs->hs_name##_valid){\
  /* Copy the data to output */ \
  *(out_ptr) = mm_regs->hs_name; \
  /* Signal done with data */ \
  mm_regs->hs_name##_valid = 0;\
  /* Set success */ \
  *(success_ptr) = 1;\
}

// Write handshake helper macro
#define mm_handshake_write(hs_name, in_ptr) \
/* Wait for buffer to be invalid=empty */\
while(mm_regs->hs_name##_valid){} \
/* Put input data into data reg */ \
mm_regs->hs_name = *in_ptr; \
/* Signal data is valid now */ \
mm_regs->hs_name##_valid = 1;

// TODO rewrite desc helper macros as void* and size of element int based functions?

// descriptor: type_t out_ptr,out_nelems_ptr = desc_hs_name in MMIO_ADDR
#define mm_axi_desc_read(desc_out_ptr, type_t, out_addr_ptr, out_nelems_ptr, desc_hs_name, MMIO_ADDR)\
/* Read description of elements in memory*/\
mm_handshake_read(desc_out_ptr, desc_hs_name); /* desc_out_ptr = desc_hs_name*/\
/* gets pointer to elements in some MMIO space*/\
*(out_addr_ptr) = (type_t*)((desc_out_ptr)->addr + (MMIO_ADDR));\
/* and number of elements (in u32 word count)*/\
*(out_nelems_ptr) = ((desc_out_ptr)->num_words*sizeof(uint32_t))/sizeof(type_t)

// success ? descriptor: type_t out_ptr,out_nelems_ptr = desc_hs_name in MMIO_ADDR
#define mm_axi_desc_try_read(success_ptr, desc_out_ptr, type_t, out_addr_ptr, out_nelems_ptr, desc_hs_name, MMIO_ADDR)\
/* Read description of elements in memory*/\
mm_handshake_try_read(success_ptr, desc_out_ptr, desc_hs_name); /* desc_out_ptr = desc_hs_name*/\
if(*(success_ptr)){\
  /* gets pointer to elements in some MMIO space*/\
  *(out_addr_ptr) = (type_t*)((desc_out_ptr)->addr + (MMIO_ADDR));\
  /* and number of elements (in u32 word count)*/\
  *(out_nelems_ptr) = ((desc_out_ptr)->num_words*sizeof(uint32_t))/sizeof(type_t);\
}

// descriptor: desc_hs_name in MMIO_ADDR = type_t in_ptr,in_nelems
#define mm_axi_desc_write(desc_out_ptr, desc_hs_name, MMIO_ADDR, type_t, in_ptr, in_nelems)\
/* compute desc addr from input ptr addr */\
(desc_out_ptr)->addr = (uint32_t)((uint8_t*)(in_ptr) - (MMIO_ADDR));\
/* compare desc size from input nelems */\
(desc_out_ptr)->num_words = (uint32_t)((in_nelems)*sizeof(type_t))/sizeof(uint32_t);\
/* Write description of elements in memory*/\
mm_handshake_write(desc_hs_name, desc_out_ptr) /* desc_hs_name = desc_out_ptr */

// Byte sized version of above
#define mm_axi_desc_sized_write(desc_out_ptr, desc_hs_name, MMIO_ADDR, total_size, in_ptr)\
/* compute desc addr from input ptr addr */\
(desc_out_ptr)->addr = (uint32_t)((void*)(in_ptr) - (MMIO_ADDR));\
/* compare desc size from input nelems */\
(desc_out_ptr)->num_words = (uint32_t)(total_size)/sizeof(uint32_t);\
/* Write description of elements in memory*/\
mm_handshake_write(desc_hs_name, desc_out_ptr) /* desc_hs_name = desc_out_ptr */

// AXI buses (type of shared resource bus)
#define MMIO_AXI0_ADDR MM_REGS_END_ADDR
#define MMIO_AXI0_SIZE 268435456 // XIL_MEM_SIZE 2^28 bytes , 256MB DDR3 = 28b address
static volatile uint8_t* AXI0 = (uint8_t*)MMIO_AXI0_ADDR;
#define MMIO_AXI0_END_ADDR (MMIO_AXI0_ADDR+MMIO_AXI0_SIZE)

// Frame buffer in AXI0 DDR
#define FB0_ADDR MMIO_AXI0_ADDR
static volatile pixel_t* FB0 = (pixel_t*)FB0_ADDR;
#define FB0_END_ADDR (FB0_ADDR + FB_SIZE)

// I2S samples also in AXI0 DDR
#define I2S_BUFFS_ADDR FB0_END_ADDR
#define I2S_BUFFS_END_ADDR (I2S_BUFFS_ADDR+I2S_BUFFS_SIZE)

// FFT output data into AXI0 DDR
#define FFT_OUT_ADDR I2S_BUFFS_END_ADDR
#define FFT_OUT_END_ADDR (FFT_OUT_ADDR + FFT_OUT_SIZE)

// Often dont care if writes are finished before returning frame_buf_write returning
// turn off waiting for writes to finish and create a RAW hazzard
// Do not read after write (not reliable to read back data after write has supposedly 'finished')
//#define MMIO_AXI0_RAW_HAZZARD
