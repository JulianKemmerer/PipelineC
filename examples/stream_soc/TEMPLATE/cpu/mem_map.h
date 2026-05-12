#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#include <stddef.h>
#endif

// RISC-V memory mapping helpers
#include "risc-v/mem_map.h" 

// Define bounds for IMEM, DMEM, and MMIO
// Needs to match link.ld (TODO how to share variables?)
#define MY_DMEM_ADDR_BIT_CHECK 30
#define MY_DMEM_BASE_ADDR ((uint32_t)((uint32_t)1<<MY_DMEM_ADDR_BIT_CHECK))
#define MY_DMEM_SIZE 32768 // Must be decimal constant since VHDL+C literal
#define MY_IMEM_SIZE 65536 // Must be decimal constant since VHDL+C literal
// Any addresses this high up will be mmio
#define MY_MEM_MAP_ADDR_BIT_CHECK 31
#define MY_MEM_MAP_BASE_ADDR ((uint32_t)((uint32_t)1<<MY_MEM_MAP_ADDR_BIT_CHECK))

// Registers are mapped differently than BRAM, different from AXI RAMs, etc
// easiest to write memory mapped objects for each storage type
// since then only need to handle each storage type roughly once.
typedef enum mm_entry_type_t{
  UNMAPPED,
  REGS,
  BRAM,
  SHARED_AXI
}mm_entry_type_t;

// The global constant memory map
typedef struct mm_entry_t{
  uint32_t start_addr;
  uint32_t end_addr;
  mm_entry_type_t dev_type;
}mm_entry_t;
// Relative to MEM_MAP_BASE_ADDR
#define N_MM_ENTRIES 1
#define REGS_MM_ENTRY_INDEX 0
static const mm_entry_t MM_ENTRIES[N_MM_ENTRIES] = {
  {.start_addr = 0x0, .end_addr = 0x010000, .dev_type = REGS} // 0
};
#ifndef __PIPELINEC__
/* TODO make static assert work
_Static_assert(
  (MM_ENTRIES[REGS_MM_ENTRY_INDEX].end_addr - 
  MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr) >=
  sizeof(mm_regs_t),
  "mm_regs_t region too small!"
);*/
#endif

// Cant rely on struct packing - produces misaligned accesses? See Makefile notes 
// So manually dont use fields smaller than 32b for now...

// Types for device mem mappings
#include "../clock/mem_map.h"

// Memory mapped registers type
typedef struct my_mm_regs_t{
  // Device mem map registers
  #include "../clock/mm_regs.h"
  #include "../led/mm_regs.h"
}my_mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "my_mm_regs_t_bytes_t.h"
#else
// Try to catch user using small field sizes, but not guarenteed to catch...
_Static_assert(sizeof(my_mm_regs_t) % 4 == 0, "my_mm_regs_t is not aligned to 4 bytes");
#endif

// Device addresses

// MM Regs
static volatile my_mm_regs_t* my_mm_regs = (my_mm_regs_t*)(MY_MEM_MAP_BASE_ADDR + MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr);
