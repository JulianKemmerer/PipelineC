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
  #include "../led_g/mm_regs.h"
}my_mm_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "my_mm_regs_t_bytes_t.h"
#else
// Try to catch user using small field sizes, but not guarenteed to catch...
_Static_assert(sizeof(my_mm_regs_t) % 4 == 0, "my_mm_regs_t is not aligned to 4 bytes");
#endif
//#define MY_MM_REGS_ADDR MY_MEM_MAP_BASE_ADDR
//static volatile my_mm_regs_t* my_mm_regs = (my_mm_regs_t*)MY_MM_REGS_ADDR;
//#define MY_MM_REGS_END_ADDR (MY_MM_REGS_ADDR+sizeof(my_mm_regs_t))

// Device mem map address constants
//#include "device/mm_addrs.h"


#define N_MM_ENTRIES 4
//#define N_SHARED_AXI_ENTRIES 2

typedef struct led_b_mm_regs_t{
  uint32_t led_on;
}led_b_mm_regs_t;
typedef struct btn_mm_regs_t{
  uint32_t btn_pressed;
}btn_mm_regs_t;

// TRY SIMPLEST VERSION FIRST? start,end no type always regs...
typedef enum my_mm_entry_type_t{
  UNMAPPED,
  REGS,
  BRAM,
  SHARED_AXI
}my_mm_entry_type_t;

typedef struct my_mm_entry_t{
  uint32_t start_addr;
  uint32_t end_addr;
  //uint32_t size; // instead of .end?
  my_mm_entry_type_t dev_type;
  //uint32_t dev_index;
  //uint1_t is_regs;
  //uint1_t is_bram;
  //uint1_t is_shared_axi;
  //char inst_name[128]; //?
}my_mm_entry_t;

// Relative to MY_MEM_MAP_BASE_ADDR
#define REGS_MM_ENTRY_INDEX 0
#define AXIL_TEST_MM_ENTRY_INDEX 1
#define LED_B_MM_ENTRY_INDEX 2
#define BTN_MM_ENTRY_INDEX 3 // TODO set_io -nowarn ICE_PB           10 # active-low
const my_mm_entry_t MY_MM_ENTRIES[N_MM_ENTRIES] = {
  {.start_addr = 0x00, .end_addr = 0x10, .dev_type = REGS},       // 0
  {.start_addr = 0x10, .end_addr = 0x20, .dev_type = SHARED_AXI}, // 1
  {.start_addr = 0x20, .end_addr = 0x30, .dev_type = SHARED_AXI}, // 2
  {.start_addr = 0x30, .end_addr = 0x40, .dev_type = SHARED_AXI}  // 3
};
static volatile my_mm_regs_t* my_mm_regs = (my_mm_regs_t*)(MY_MEM_MAP_BASE_ADDR + MY_MM_ENTRIES[REGS_MM_ENTRY_INDEX].start_addr);
static volatile uint32_t* my_axil_test_u32s = (uint32_t*)(MY_MEM_MAP_BASE_ADDR + MY_MM_ENTRIES[AXIL_TEST_MM_ENTRY_INDEX].start_addr);
static volatile led_b_mm_regs_t* my_led_b = (led_b_mm_regs_t*)(MY_MEM_MAP_BASE_ADDR + MY_MM_ENTRIES[LED_B_MM_ENTRY_INDEX].start_addr);
static volatile btn_mm_regs_t* my_btn = (btn_mm_regs_t*)(MY_MEM_MAP_BASE_ADDR + MY_MM_ENTRIES[BTN_MM_ENTRY_INDEX].start_addr);

// TODO static assert end-start>sizeof