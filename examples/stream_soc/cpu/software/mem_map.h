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

// Registers
typedef struct mm_ctrl_regs_t{ 
  uint32_t led; // Only 4 bits used, see above note rounding to 32b
  uint32_t compute_fft_cycles; // Cycles per fft iter debug counter
}mm_ctrl_regs_t;
typedef struct mm_status_regs_t{ 
  uint32_t button; // Only 4 bits used, see above note rounding to 32b
  uint32_t cpu_clock;
  //uint32_t i2s_rx_out_desc_overflow; // Single bit
}mm_status_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_ctrl_regs_t_bytes_t.h"
#include "mm_status_regs_t_bytes_t.h"
#endif
#define MM_CTRL_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_ctrl_regs_t* mm_ctrl_regs = (mm_ctrl_regs_t*)MM_CTRL_REGS_ADDR;
// LED (copying old def)
static volatile uint32_t* LED = (uint32_t*)(MM_CTRL_REGS_ADDR + offsetof(mm_ctrl_regs_t, led));//&(mm_ctrl_regs->led);
#define MM_CTRL_REGS_END_ADDR (MM_CTRL_REGS_ADDR+sizeof(mm_ctrl_regs_t))
#define MM_STATUS_REGS_ADDR MM_CTRL_REGS_END_ADDR
static volatile mm_status_regs_t* mm_status_regs = (mm_status_regs_t*)MM_STATUS_REGS_ADDR;
#define MM_STATUS_REGS_END_ADDR (MM_STATUS_REGS_ADDR+sizeof(mm_status_regs_t))

// Separate handshake data regs 
// so not mixed in with strictly simple in or out status and ctrl registers
// MM Handshake registers
// TODO have memory map struct provided by fft,i2s modules that includes handshake fields etc
typedef struct mm_handshake_data_t{ 
  axi_descriptor_t i2s_rx_desc_to_write;
  axi_descriptor_t i2s_rx_desc_written;
  //
  // I2S TX unused for now axi_descriptor_t i2s_tx_desc_to_read;
  // I2S TX unused for now axi_descriptor_t i2s_tx_desc_read_from;
  //
  axi_descriptor_t fft_desc_to_write;
  axi_descriptor_t fft_desc_written;
}mm_handshake_data_t;
typedef struct mm_handshake_valid_t{ 
  uint32_t i2s_rx_desc_to_write;
  uint32_t i2s_rx_desc_written;
  //
  // I2S TX unused for now uint32_t i2s_tx_desc_to_read;
  // I2S TX unused for now uint32_t i2s_tx_desc_read_from;
  //
  uint32_t fft_desc_to_write;
  uint32_t fft_desc_written;
}mm_handshake_valid_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_handshake_data_t_bytes_t.h"
#include "mm_handshake_valid_t_bytes_t.h"
#endif
#define MM_HANDSHAKE_DATA_ADDR MM_STATUS_REGS_END_ADDR
static volatile mm_handshake_data_t* mm_handshake_data = (mm_handshake_data_t*)MM_HANDSHAKE_DATA_ADDR;
#define MM_HANDSHAKE_DATA_END_ADDR (MM_HANDSHAKE_DATA_ADDR+sizeof(mm_handshake_data_t))
#define MM_HANDSHAKE_VALID_ADDR MM_HANDSHAKE_DATA_END_ADDR
static volatile mm_handshake_valid_t* mm_handshake_valid = (mm_handshake_valid_t*)MM_HANDSHAKE_VALID_ADDR;
#define MM_HANDSHAKE_VALID_END_ADDR (MM_HANDSHAKE_VALID_ADDR+sizeof(mm_handshake_valid_t))

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
#define MMIO_AXI0_ADDR MM_HANDSHAKE_VALID_END_ADDR
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
