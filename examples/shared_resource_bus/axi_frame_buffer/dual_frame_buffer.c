// VGA pmod stuff
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#define VGA_ASYNC_FIFO_N_PIXELS 1
#include "vga/vga_pmod_async_pixels_fifo.c" // Version that expects only x,y pixels, N at a time

// TODO error check rates somehow
//#if HOST_CLK_MHZ < (1.5*PIXEL_CLK_MHZ)
// Maybe can push as low as 1.0x
//#error "Need faster host clock to meet display rate!"
//#endif

// Code for a shared AXI RAMs
#define AXI_RAM_MODE_BRAM
//#define AXI_RAM_MODE_DDR

// Tile down by 2,4,8 times etc to fit into on chip ram for now
#define TILE_FACTOR 8 // 4x to fit in 100T BRAM, x8 to not have Verilator build explode in RAM use?
#define TILE_FACTOR_LOG2 3
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define AXI_RAM_DEPTH (((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)/AXI_BUS_BYTE_WIDTH)

// Pixel x,y pos to pixel index
uint32_t pos_to_pixel_index(uint16_t x, uint16_t y)
{
  uint16_t x_tile_index = x >> TILE_FACTOR_LOG2;
  uint16_t y_tile_index = y >> TILE_FACTOR_LOG2;
  return (y_tile_index*NUM_X_TILES) + x_tile_index;
}
// Pixel index to address in RAM
uint32_t pixel_index_to_addr(uint32_t index)
{
  // Each pixel is a 32b (4 byte) word
  uint32_t addr = index << BYTES_PER_PIXEL_LOG2;
  return addr;
}
// Pixel x,y to pixel ram address
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  uint32_t pixel_index = pos_to_pixel_index(x, y);
  uint32_t addr = pixel_index_to_addr(pixel_index);
  return addr;
}

// Dual frame buffer is writing to one buffer while other is for reading
uint1_t frame_buffer_read_port_sel;
// Slow changing can be loose crossing domains
#pragma ASYNC_WIRE frame_buffer_read_port_sel

// Always-reading logic to drive VGA signal into pmod_async_fifo_write
#ifdef AXI_RAM_MODE_BRAM
#include "bram_dual_frame_buffer.c"
#elif defined(AXI_RAM_MODE_DDR)
#include "ddr_dual_frame_buffer.c"
#endif
