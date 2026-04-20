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

// Types for device mem mappings
#include "../clock/mem_map.h"

// Define bounds for IMEM, DMEM, and MMIO
// Needs to match link.ld (TODO how to share variables?)
#define MY_DMEM_ADDR_BIT_CHECK 30
#define MY_DMEM_BASE_ADDR ((uint32_t)((uint32_t)1<<MY_DMEM_ADDR_BIT_CHECK))
#define MY_DMEM_SIZE 2048 // Must be decimal constant since VHDL+C literal
#define MY_IMEM_SIZE 4096 // Must be decimal constant since VHDL+C literal
// Any addresses this high up will be mmio
#define MY_MEM_MAP_ADDR_BIT_CHECK 31
#define MY_MEM_MAP_BASE_ADDR ((uint32_t)((uint32_t)1<<MY_MEM_MAP_ADDR_BIT_CHECK))

// Registers are mapped differently than BRAM, different from AXI RAMs, etc
// easiest to write memory mapped objects for each storage type
// since then only need to handle each storage type roughly once.

// Cant rely on struct packing - produces misaligned accesses? See Makefile notes 
// So manually dont use fields smaller than 32b for now...

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
#define MY_MM_REGS_ADDR MY_MEM_MAP_BASE_ADDR
static volatile my_mm_regs_t* my_mm_regs = (my_mm_regs_t*)MY_MM_REGS_ADDR;
#define MY_MM_REGS_END_ADDR (MY_MM_REGS_ADDR+sizeof(my_mm_regs_t))

// Device mem map address constants
//#include "device/mm_addrs.h"