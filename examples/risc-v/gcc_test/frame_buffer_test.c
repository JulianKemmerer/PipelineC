#include <stdint.h>
#include "mem_map.h"



//////////////////////////////////////////////////////////////////////////////////
// COPIED FROM examples/shared_resource_bus/axi_frame_buffer/*
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color
#define FRAME_WIDTH 800
#define FRAME_HEIGHT 600
// Tile down by 2,4,8 times etc to fit into on chip ram for now
#define TILE_FACTOR 1 // 4x to fit in 100T BRAM, x8 to not have Verilator build explode in RAM use?
#define TILE_FACTOR_LOG2 0
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define AXI_BUS_BYTE_WIDTH sizeof(uint32_t)
#define AXI_RAM_DEPTH (((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)/AXI_BUS_BYTE_WIDTH)
#define MEM_SIZE (AXI_RAM_DEPTH*AXI_BUS_BYTE_WIDTH) // DDR=268435456 // 2^28 bytes , 256MB DDR3 = 28b address
// Pixel x,y pos to pixel index
static inline __attribute__((always_inline)) uint32_t pos_to_pixel_index(uint32_t x, uint32_t y)
{
  uint32_t x_tile_index = x >> TILE_FACTOR_LOG2;
  uint32_t y_tile_index = y >> TILE_FACTOR_LOG2;
  return (y_tile_index*NUM_X_TILES) + x_tile_index;
}
// Pixel index to address in RAM
static inline __attribute__((always_inline)) uint32_t pixel_index_to_addr(uint32_t index)
{
  // Each pixel is a 32b (4 byte) word
  uint32_t addr = index << BYTES_PER_PIXEL_LOG2;
  return addr;
}
// Pixel x,y to pixel ram address
static inline __attribute__((always_inline)) uint32_t pos_to_addr(uint32_t x, uint32_t y)
{
  uint32_t pixel_index = pos_to_pixel_index(x, y);
  uint32_t addr = pixel_index_to_addr(pixel_index);
  return addr;
}
//////////////////////////////////////////////////////////////////////////////////
// Pack and unpack pixel type for ram_read/ram_write
pixel_t frame_buf_read(
  uint32_t x, uint32_t y
  //uint32_t addr
){
  uint32_t addr = pos_to_addr(x, y);
  uint32_t read_data = ram_read(addr);
  pixel_t pixel;
  pixel.a = read_data >> (0*8);
  pixel.r = read_data >> (1*8);
  pixel.g = read_data >> (2*8);
  pixel.b = read_data >> (3*8);
  return pixel;
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel.a<<(0*8));
  write_data |= ((uint32_t)pixel.r<<(1*8));
  write_data |= ((uint32_t)pixel.g<<(2*8));
  write_data |= ((uint32_t)pixel.b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, write_data);
}

// Helper to do frame sync
void threads_frame_sync(){
  // Signal done by driving the frame signal 
  // with its expected value
  int32_t expected_value = *FRAME_SIGNAL;
  *FRAME_SIGNAL = expected_value;
  // And wait for a new different expect value
  while(*FRAME_SIGNAL == expected_value){}
  return;
}


void main() {
  // Do test of modifying pixels
  *LED = 1;
  // x,y bounds based on which thread you are
  // Let each thread do entire horizontal X lines, split Y direction

  // Write all pixels zero
  for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
      for(int x=0; x < FRAME_WIDTH; x++){
          pixel_t p = {.r=0, .g=0, .b=0};
          frame_buf_write(x, y, p);
      }
  }
  *LED = ~*LED;
  threads_frame_sync();

  // Toggle as test of fast read and write
  while(1){
    for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
        for(int x=0; x < FRAME_WIDTH; x++){
            // Read pixel
            pixel_t p = frame_buf_read(x, y);
            // Invert all colors 
            p.r = ~p.r;
            p.g = ~p.g;
            p.b = ~p.b;
            // Write to screen
            frame_buf_write(x, y, p);
        }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
  }
}
