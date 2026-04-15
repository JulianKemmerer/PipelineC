#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#include <stddef.h>
#endif

// For mm_handshake_read, etc
#include "risc-v/mem_map.h" 

// Types for device registers
#include "../clock/mem_map.h"
#include "../vga/mem_map.h"
#include "../shared_ddr/mem_map.h"
#include "../i2s/mem_map.h"
#include "../power/mem_map.h"
#include "../sccb/mem_map.h"
#include "../video/mem_map.h"
#include "../gpu/mem_map.h"

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

// Cant rely on struct packing - produces misaligned accesses? See Makefile notes 
// So manually dont use fields smaller than 32b for now...

typedef struct mm_regs_t{
  // Device registers
  #include "../clock/mm_regs.h"
  #include "../led/mm_regs.h"
  #include "../buttons/mm_regs.h"
  #include "../switches/mm_regs.h"
  #include "../i2s/i2s_mm_regs.h"
  #include "../power/power_mm_regs.h"
  #include "../sccb/sccb_mm_regs.h"
  #include "../dvp/mm_regs.h"
  #include "../video/mm_regs.h"
  #include "../gpu/mm_regs.h"
}mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_regs_t_bytes_t.h"
#else
// Try to catch user using small field sizes, but not guarenteed to catch...
_Static_assert(sizeof(mm_regs_t) % 4 == 0, "mm_regs_t is not aligned to 4 bytes");
#endif
#define MM_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_regs_t* mm_regs = (mm_regs_t*)MM_REGS_ADDR;
#define MM_REGS_END_ADDR (MM_REGS_ADDR+sizeof(mm_regs_t))

// Device addresses
#include "../shared_ddr/mm_addrs.h"
#include "../vga/mm_addrs.h"
#include "../i2s/mm_addrs.h"
#include "../power/mm_addrs.h"