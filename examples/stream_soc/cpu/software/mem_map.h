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
#include "devices_mem_map.h" // Types for device registers

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
  // Device registers
  #include "devices_mm_regs.h"
}mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_regs_t_bytes_t.h"
#endif
#define MM_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_regs_t* mm_regs = (mm_regs_t*)MM_REGS_ADDR;
#define MM_REGS_END_ADDR (MM_REGS_ADDR+sizeof(mm_regs_t))

// Device addresses
#include "devices_mm_addrs.h"