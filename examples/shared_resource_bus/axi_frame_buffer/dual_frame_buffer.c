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
//#define AXI_RAM_MODE_BRAM
#define AXI_RAM_MODE_DDR

// Tile down by 2,4,8 times etc to fit into on chip ram for now
#define TILE_FACTOR 1
#define TILE_FACTOR_LOG2 0
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

// Always-reading logic to drive VGA signal into pmod_async_fifo_write
#ifdef AXI_RAM_MODE_BRAM
#include "bram_dual_frame_buffer.c"
#elif defined(AXI_RAM_MODE_DDR)
#include "ddr_dual_frame_buffer.c"
#endif

/*
// FSM style version of VGA read start and finish
// max rate at output is 1 clock to finish read, 1 clock to write into VGA fifo
// so max rate is a read every other cycle
void host_vga_read_starter()
{
  vga_pos_t vga_pos;
  while(1)
  {
    // Start read of the 1 pixel at x,y pos
    frame_buf_read_only_start(vga_pos.x, vga_pos.y);
    // Increment vga pos for next time
    vga_pos = vga_frame_pos_increment(vga_pos, 1);
  }
}
void host_vga_read_finisher()
{
  while(1)
  {
    // Receive the output of the read started prior
    pixel_t pixels[1];
    pixels[0] = frame_buf_read_only_finish();
    
    // Write pixels into async fifo feeding vga pmod for display
    pmod_async_fifo_write(pixels);
  }
}
// Wrap up FSMs at top level
#include "host_vga_read_starter_FSM.h"
#include "host_vga_read_finisher_FSM.h"
MAIN_MHZ(host_vga_reader_wrapper, HOST_CLK_MHZ)
void host_vga_reader_wrapper()
{
  host_vga_read_starter_INPUT_t starter_i;
  starter_i.input_valid = 1;
  starter_i.output_ready = 1;
  host_vga_read_starter_OUTPUT_t starter_o = host_vga_read_starter_FSM(starter_i);
  host_vga_read_finisher_INPUT_t finisher_i;
  finisher_i.input_valid = 1;
  finisher_i.output_ready = 1;
  host_vga_read_finisher_OUTPUT_t finisher_o = host_vga_read_finisher_FSM(finisher_i);
}
*/
/* Single in flight always reading for VGA
void host_vga_reader()
{
  vga_pos_t vga_pos;
  while(1)
  {
    // Start read of the 1 pixel at x,y pos
    pixel_t pixels[1];
    pixels[0] = frame_buf_read(vga_pos.x, vga_pos.y);
    // Write pixels into async fifo feeding vga pmod for display
    pmod_async_fifo_write(pixels);
    // Increment vga pos for next time
    vga_pos = vga_frame_pos_increment(vga_pos, 1);
  }
}
#include "host_vga_reader_FSM.h"
MAIN_MHZ(host_vga_reader_wrapper, HOST_CLK_MHZ)
void host_vga_reader_wrapper()
{
  host_vga_reader_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  host_vga_reader_OUTPUT_t o = host_vga_reader_FSM(i);
}*/
