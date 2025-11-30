#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#include <stddef.h>
#endif

#include "risc-v/mem_map.h" // For mm_handshake_read, etc
#include "axi/axi_shared_bus.h" // For axi_descriptor_t, etc
#include "vga/pixel.h"
#include "../../i2s/software/mem_map.h"
#include "../../fft/software/mem_map.h"
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

// Original regs for top IO, TODO make into modules
typedef struct mm_ctrl_regs_t{ 
  uint32_t led; // Only 4 bits used, see above note rounding to 32b
}mm_ctrl_regs_t;
typedef struct mm_status_regs_t{ 
  uint32_t button; // Only 4 bits used, see above note rounding to 32b
  uint32_t cpu_clock;
}mm_status_regs_t;

typedef struct mm_regs_t{ 
  mm_ctrl_regs_t ctrl;
  mm_status_regs_t status;
  #include "../../i2s/software/i2s_mm_regs.h"
  #include "../../fft/software/fft_mm_regs.h"
  #include "../../dvp/software/sccb_mm_regs.h"
}mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_regs_t_bytes_t.h"
#endif
#define MM_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_regs_t* mm_regs = (mm_regs_t*)MM_REGS_ADDR;
#define MM_REGS_END_ADDR (MM_REGS_ADDR+sizeof(mm_regs_t))

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
