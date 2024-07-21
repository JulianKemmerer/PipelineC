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
#define DMEM_SIZE 65536 // Must be decimal constant since VHDL+C literal
#define IMEM_SIZE 65536 // Must be decimal constant since VHDL+C literal
// Any addresses this high up will be mmio
#define MEM_MAP_ADDR_BIT_CHECK 31
#define MEM_MAP_BASE_ADDR ((uint32_t)((uint32_t)1<<MEM_MAP_ADDR_BIT_CHECK))

// Registers are mapped differently than BRAM, different from AXI RAMs, etc
// easiest to write memory mapped objects for each storage type
// since then only need to handle each storage type roughly once.

// Not using attribute packed for now, so manually dont use ints smaller than 32b...

// Registers
typedef struct mm_ctrl_regs_t{ // TODO is break apart CTRL and STATUS needed?
  uint32_t led; // Only 4 bits used, see above note rounding to 32b
}mm_ctrl_regs_t;
// To-from bytes conversion func
#ifdef __PIPELINEC__
#include "mm_ctrl_regs_t_bytes_t.h"
#endif
#define MM_CTRL_REGS_ADDR MEM_MAP_BASE_ADDR
static volatile mm_ctrl_regs_t* mm_ctrl_regs = (mm_ctrl_regs_t*)MM_CTRL_REGS_ADDR;
// LED (copying old def)
static volatile uint32_t* LED = (uint32_t*)(MM_CTRL_REGS_ADDR + offsetof(mm_ctrl_regs_t, led));//&(mm_ctrl_regs->led);
#define MM_CTRL_REGS_END_ADDR (MM_CTRL_REGS_ADDR+sizeof(mm_ctrl_regs_t))

// Block RAMs
#define MMIO_BRAM0
#ifdef MMIO_BRAM0
#define MMIO_BRAM0_SIZE 1024
#define MMIO_BRAM0_ADDR MM_CTRL_REGS_END_ADDR
#define MMIO_BRAM0_INIT "(others => (others => '0'))"
static volatile uint8_t* BRAM0 = (uint8_t*)MMIO_BRAM0_ADDR;
#define MMIO_BRAM0_END_ADDR (MMIO_BRAM0_ADDR+MMIO_BRAM0_SIZE)
#endif

// AXI buses (type of shared resource bus)
#define MMIO_AXI0
#ifdef MMIO_AXI0
#define MMIO_AXI0_ADDR MMIO_BRAM0_END_ADDR
#define MMIO_AXI0_SIZE 268435456 // XIL_MEM_SIZE 2^28 bytes , 256MB DDR3 = 28b address
static volatile uint8_t* AXI0 = (uint8_t*)MMIO_AXI0_ADDR;
#define MMIO_AXI0_END_ADDR (MMIO_AXI0_ADDR+MMIO_AXI0_SIZE)
// Frame buffer in AXI0 DDR (at addr=0)
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, matching hardware byte order
static volatile pixel_t* FB0 = (pixel_t*)MMIO_AXI0_ADDR;
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#define TILE_FACTOR 1
#define TILE_FACTOR_LOG2 0
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
// Pixel x,y pos to pixel index in array
uint32_t pos_to_pixel_index(uint16_t x, uint16_t y)
{
  uint32_t x_tile_index = x >> TILE_FACTOR_LOG2;
  uint32_t y_tile_index = y >> TILE_FACTOR_LOG2;
  return (y_tile_index*NUM_X_TILES) + x_tile_index;
}
pixel_t frame_buf_read(uint16_t x, uint16_t y)
{
  return FB0[pos_to_pixel_index(x,y)];
}
void frame_buf_write(uint16_t x, uint16_t y, pixel_t pixel)
{
  FB0[pos_to_pixel_index(x,y)] = pixel;
}
#endif
