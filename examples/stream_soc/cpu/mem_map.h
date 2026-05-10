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
#include "../ddr/mem_map.h"
#include "../shared_ddr/mem_map.h"
#include "../frame_buffers/mem_map.h"
#include "../i2s/mem_map.h"
#include "../fft/mem_map.h"
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
typedef enum mm_entry_type_t{
  UNMAPPED,
  REGS,
  BRAM,
  SHARED_AXI
}mm_entry_type_t;

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

// The global constant memory map
typedef struct mm_entry_t{
  uint32_t start_addr;
  uint32_t end_addr;
  mm_entry_type_t dev_type;
}mm_entry_t;
// Relative to MEM_MAP_BASE_ADDR
#define N_MM_ENTRIES 2
#define SHARED_AXI_DDR3_MM_ENTRY_INDEX 0
#define REGS_MM_ENTRY_INDEX            1
#define N_SHARED_AXI_DEV 1
static const mm_entry_t MM_ENTRIES[N_MM_ENTRIES] = {
  {.start_addr = 0x0,        .end_addr = 0x10000000, .dev_type = SHARED_AXI}, // 0
  {.start_addr = 0x10000000, .end_addr = 0x10010000, .dev_type = REGS}        // 1
};
#ifndef __PIPELINEC__
/* TODO make static assert work
_Static_assert(
  (MM_ENTRIES[SHARED_AXI_DDR3_MM_ENTRY_INDEX].end_addr - 
  MM_ENTRIES[SHARED_AXI_DDR3_MM_ENTRY_INDEX].start_addr) >=
  XIL_MEM_SIZE,
  "Xil DDR3 MM region too small!"
);
_Static_assert(
  (MM_ENTRIES[REGS_MM_ENTRY_INDEX].end_addr - 
  MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr) >=
  sizeof(mm_regs_t),
  "mm_regs_t region too small!"
);*/
#endif
//static volatile uint8_t* AXI0 = (uint8_t*)(MEM_MAP_BASE_ADDR + MM_ENTRIES[SHARED_AXI_DDR3_MM_ENTRY_INDEX].start_addr);
static volatile mm_regs_t* mm_regs = (mm_regs_t*)(MEM_MAP_BASE_ADDR + MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr);

// Device addresses

// Subdivide the shared axi DDR3 further for specific devices
//#include "../shared_ddr/mm_addrs.h"
#define MMIO_AXI0_ADDR MEM_MAP_BASE_ADDR
#define MMIO_AXI0_SIZE 268435456 // XIL_MEM_SIZE 2^28 bytes , 256MB DDR3 = 28b address
#define MMIO_AXI0_END_ADDR (MMIO_AXI0_ADDR+MMIO_AXI0_SIZE)
//#include "../vga/mm_addrs.h"
#define FB0_ADDR MMIO_AXI0_ADDR
// Frame buffer in AXI0 DDR
//static volatile pixel_t* FB0 = (pixel_t*)FB0_ADDR;
#define FB0_END_ADDR (FB0_ADDR + FB_SIZE)
//#include "../i2s/mm_addrs.h"
// I2S samples also in AXI0 DDR
#define I2S_BUFFS_ADDR FB0_END_ADDR
#define I2S_BUFFS_END_ADDR (I2S_BUFFS_ADDR+I2S_BUFFS_SIZE)
// Power spectrum output data into AXI0 DDR
//#include "../power/mm_addrs.h"
#define POWER_OUT_ADDR I2S_BUFFS_END_ADDR
#define POWER_OUT_END_ADDR (POWER_OUT_ADDR + POWER_OUT_SIZE)
#ifndef __PIPELINEC__
/* TODO make static assert work
_Static_assert(
  POWER_OUT_END_ADDR <= 
  MM_ENTRIES[SHARED_AXI_DDR3_MM_ENTRY_INDEX].end_addr,
  "Xil DDR3 mappings out of range!"
);*/
#endif