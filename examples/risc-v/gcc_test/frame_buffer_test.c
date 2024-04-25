#include <stdint.h>
#include "mem_map.h"



//////////////////////////////////////////////////////////////////////////////////
// COPIED ROM DUAL FRAME BUFFER .c
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color
#define FRAME_WIDTH 800
#define FRAME_HEIGHT 600
// Tile down by 2,4,8 times etc to fit into on chip ram for now
#define TILE_FACTOR 4 // 4x to fit in 100T BRAM, x8 to not have Verilator build explode in RAM use?
#define TILE_FACTOR_LOG2 2
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define AXI_BUS_BYTE_WIDTH sizeof(uint32_t)
#define AXI_RAM_DEPTH (((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)/AXI_BUS_BYTE_WIDTH)
#define MEM_SIZE (AXI_RAM_DEPTH*AXI_BUS_BYTE_WIDTH) // DDR=268435456 // 2^28 bytes , 256MB DDR3 = 28b address
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
//////////////////////////////////////////////////////////////////////////////////
// Pack and unpack pixel type for ram_read/ram_write
pixel_t frame_buf_read(
  //uint16_t x, uint16_t y
  uint32_t addr
){
  //uint32_t addr = pos_to_addr(x, y);
  uint32_t read_data = ram_read(addr);
  pixel_t pixel;
  pixel.a = read_data >> (3*8);
  pixel.r = read_data >> (2*8);
  pixel.g = read_data >> (1*8);
  pixel.b = read_data >> (0*8);
  return pixel;
}
void frame_buf_write(
  //uint16_t x, uint16_t y,
  uint32_t addr, 
  pixel_t pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel.a<<(3*8));
  write_data |= ((uint32_t)pixel.r<<(2*8));
  write_data |= ((uint32_t)pixel.g<<(1*8));
  write_data |= ((uint32_t)pixel.b<<(0*8));
  //uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, write_data);
}


void main() {
  // Calculate memory bounds based on which core you are
  // Chunk size in bytes rounded to u32 4 byte units
  uint32_t chunk_size = ((MEM_SIZE/NUM_THREADS)/sizeof(uint32_t))*sizeof(uint32_t);
  uint32_t start_addr = *THREAD_ID * chunk_size;
  // Adjust for if mem size divides unevenly
  uint32_t chunks_sum = chunk_size * NUM_THREADS;
  // Last core gets different chunk size
  int32_t last_chunk_extra = MEM_SIZE - chunks_sum;
  int32_t last_chunk_size = chunk_size + last_chunk_extra;
  if(*THREAD_ID==(NUM_THREADS-1)){
    chunk_size = last_chunk_size;
  }
  uint32_t end_addr = start_addr + chunk_size;

  // DO NOTHING
  //while(1){
    *LED = 1;
  //}
  
  // First set all pixels to 255 white
  //while(1){
    pixel_t pixel = {.r=255, .g=255, .b=255};
    uint32_t addr;
    for(addr = start_addr; addr < end_addr; addr+=sizeof(uint32_t))
    {
      frame_buf_write(addr, pixel);
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
  //}

  // Do test of modifying pixels
  while(1){
    for(addr = start_addr; addr < end_addr; addr+=sizeof(uint32_t))
    {
      // Read pixel
      pixel_t pixel = frame_buf_read(addr);
      // Decrement 
      pixel.r -= 1;
      pixel.g -= 1;
      pixel.b -= 1;
      // Write pixel
      frame_buf_write(addr, pixel);
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
  }
}
