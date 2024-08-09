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
typedef struct mm_ctrl_regs_t{ 
  uint32_t led; // Only 4 bits used, see above note rounding to 32b
}mm_ctrl_regs_t;
typedef struct mm_status_regs_t{ 
  uint32_t button; // Only 4 bits used, see above note rounding to 32b
  uint32_t i2s_rx_out_desc_overflow; // Single bit
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


// TODO FIX DONT HAVE TWO COPIES OF THIS DEF
typedef struct axi_descriptor_t
{
  uint32_t addr;
  uint32_t num_words; // TODO make number of bytes?
}axi_descriptor_t;

// Separate handshake data regs 
// so not mixed in with strictly simple in or out status and ctrl registers
// MM Handshake registers
typedef struct mm_handshake_data_t{ 
  axi_descriptor_t i2s_rx_out_desc;
}mm_handshake_data_t;
typedef struct mm_handshake_valid_t{ 
  uint32_t i2s_rx_out_desc;
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

// TODO make macro or generic byte copying helper func?
void i2s_rx_out_desc_READ(axi_descriptor_t* desc_out){
  // Wait for valid data to show up
  while(!mm_handshake_valid->i2s_rx_out_desc){}
  // Copy the data to output
  *desc_out = mm_handshake_data->i2s_rx_out_desc;
  // Signal done with data
  mm_handshake_valid->i2s_rx_out_desc = 0;
}

// Block RAMs
#define MMIO_BRAM0
#ifdef MMIO_BRAM0
#define MMIO_BRAM0_SIZE 1024
#define MMIO_BRAM0_ADDR MM_HANDSHAKE_VALID_END_ADDR
#define MMIO_BRAM0_INIT "(others => (others => '0'))"
static volatile uint8_t* BRAM0 = (uint8_t*)MMIO_BRAM0_ADDR;
#define MMIO_BRAM0_END_ADDR (MMIO_BRAM0_ADDR+MMIO_BRAM0_SIZE)
#endif

// TODO ORGANIZE THIS BETTER
// AXI buses (type of shared resource bus)
#define MMIO_AXI0
#ifdef MMIO_AXI0
#define MMIO_AXI0_ADDR MMIO_BRAM0_END_ADDR
#define MMIO_AXI0_SIZE 268435456 // XIL_MEM_SIZE 2^28 bytes , 256MB DDR3 = 28b address
static volatile uint8_t* AXI0 = (uint8_t*)MMIO_AXI0_ADDR;
#define MMIO_AXI0_END_ADDR (MMIO_AXI0_ADDR+MMIO_AXI0_SIZE)
// Frame buffer in AXI0 DDR
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, matching hardware byte order
#define FB0_ADDR MMIO_AXI0_ADDR
static volatile pixel_t* FB0 = (pixel_t*)FB0_ADDR;
// TODO FIX DONT HAVE TWO COPIES OF THIS DEF
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#define TILE_FACTOR 1
#define TILE_FACTOR_LOG2 0
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define FB_SIZE ((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)
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
#define FB0_END_ADDR (FB0_ADDR + FB_SIZE)
// I2S samples also in AXI0 DDR
#define I2S_BUFFS_ADDR FB0_END_ADDR
// Configure i2s_axi_loopback.c to use memory mapped addr offset in CPU's AXI0 region
#define I2S_LOOPBACK_DEMO_SAMPLES_ADDR (I2S_BUFFS_ADDR-MMIO_AXI0_ADDR)
#define I2S_LOOPBACK_DEMO_N_SAMPLES 64 // TODO want 1024+ for FFT?
#define I2S_LOOPBACK_DEMO_N_DESC 16 // 16 is good min, since xilinx async fifo min size 16
// TODO I2S_BUFFS_END_ADDR using size info above
typedef struct i2s_sample_in_mem_t{ // TODO FIX DONT HAVE TWO COPIES OF THIS DEF
  int32_t l;
  int32_t r;
}i2s_sample_in_mem_t;
void i2s_read(i2s_sample_in_mem_t** samples_ptr_out, int* n_samples_out){
  // Read description of samples in memory
  axi_descriptor_t samples_desc;
  i2s_rx_out_desc_READ(&samples_desc);
  // gets pointer to samples in AXI DDR memory
  i2s_sample_in_mem_t* samples = (i2s_sample_in_mem_t*)(samples_desc.addr + MMIO_AXI0_ADDR);
  // and number of samples (in u32 word count)
  int n_samples = (samples_desc.num_words*sizeof(uint32_t))/sizeof(i2s_sample_in_mem_t);
  // return outputs
  *samples_ptr_out = samples;
  *n_samples_out = n_samples;
}

// Often dont care if writes are finished before returning frame_buf_write returning
// turn off waiting for writes to finish and create a RAW hazzard
// Do not read after write (not reliable to read back data after write has supposedly 'finished')
//#define MMIO_AXI0_RAW_HAZZARD
#endif
