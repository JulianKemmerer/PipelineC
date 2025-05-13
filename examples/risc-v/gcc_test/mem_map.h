#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#include <stddef.h>
#endif

// Define bounds for IMEM, DMEM, and MMIO
// Needs to match link.ld (TODO how to share variables?)
#define DMEM_ADDR_BIT_CHECK 30
#define DMEM_BASE_ADDR ((uint32_t)((uint32_t)1<<DMEM_ADDR_BIT_CHECK))
#define DMEM_SIZE 1024 // Must be decimal constant since VHDL+C literal
#define IMEM_SIZE 1024 // Must be decimal constant since VHDL+C literal
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
}mm_ctrl_regs_t;
typedef struct mm_status_regs_t{ 
  uint32_t unused_button; // Only 4 bits used, see above note rounding to 32b
  uint32_t unused_cpu_clock;
}mm_status_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_ctrl_regs_t_bytes_t.h"
#include "mm_status_regs_t_bytes_t.h"
#endif
#define MM_CTRL_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_ctrl_regs_t* mm_ctrl_regs = (mm_ctrl_regs_t*)MM_CTRL_REGS_ADDR;
#define MM_CTRL_REGS_END_ADDR (MM_CTRL_REGS_ADDR+sizeof(mm_ctrl_regs_t))
#define MM_STATUS_REGS_ADDR MM_CTRL_REGS_END_ADDR
static volatile mm_status_regs_t* mm_status_regs = (mm_status_regs_t*)MM_STATUS_REGS_ADDR;
#define MM_STATUS_REGS_END_ADDR (MM_STATUS_REGS_ADDR+sizeof(mm_status_regs_t))

/* 
// Separate handshake data regs 
// so not mixed in with strictly simple in or out status and ctrl registers
// MM Handshake registers
typedef struct mm_handshake_data_t{ 
  uint32_t dummy;
}mm_handshake_data_t;
typedef struct mm_handshake_valid_t{ 
  uint32_t dummy;
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

// Block RAMs
#define MMIO_BRAM0
#ifdef MMIO_BRAM0
#define MMIO_BRAM0_SIZE 1024
#define MMIO_BRAM0_ADDR MM_HANDSHAKE_VALID_END_ADDR
#define MMIO_BRAM0_INIT "(others => (others => '0'))"
static volatile uint8_t* BRAM0 = (uint8_t*)MMIO_BRAM0_ADDR;
#define MMIO_BRAM0_END_ADDR (MMIO_BRAM0_ADDR+MMIO_BRAM0_SIZE)
#endif
*/