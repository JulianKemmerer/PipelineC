//////////////////////////////////////////////////////////////////////////////////
// COPIED FROM examples/shared_resource_bus/axi_frame_buffer/*
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, does get correctly packed at 4 bytes sizeof()
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

void kernel(int x, int y, pixel_t* p_in, pixel_t* p_out){
  // Invert all colors
  // Kernel right now doesnt depend on x,y position
  p_out->r = ~p_in->r;
  p_out->g = ~p_in->g;
  p_out->b = ~p_in->b;
}

// Helper to do frame sync
void threads_frame_sync(){
  // Signal done by driving the frame signal 
  // with its expected value
  int32_t expected_value = *FRAME_SIGNAL;
  *FRAME_SIGNAL = expected_value;
  // And wait for a new different expect value
  while(*FRAME_SIGNAL == expected_value){}
}


void frame_buf_read(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  ram_read(addr, (uint32_t*)pixel, num_pixels);
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, (uint32_t*)pixel, num_pixels);
}
void frame_buf_write_start(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_write(addr, (uint32_t*)pixel, num_pixels);
}
// Multiple in flight versions
void frame_buf_read_start(
  uint32_t x, uint32_t y,
  uint32_t num_pixels
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_read(addr, num_pixels);
}
void frame_buf_read_finish(pixel_t* pixel, uint8_t num_pixels){
  finish_ram_read((uint32_t*)pixel, num_pixels);
}
