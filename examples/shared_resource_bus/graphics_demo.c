#pragma PART "xc7a100tcsg324-1" 
#include "compiler.h"
#include "debug_port.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"

// Next: 
// Add push button LFSR add randomness in function since renders to stead state so fast?

// TODO:
// How to wrap/macro make any new 'resource'?
// Extend to use an autopipeline - sphery? 
//      Async start finish calls?
//      Since waiting hundreds of cycles per op is dumb?
//      Is operaiton render random x,y or next x,y?
// Extend to use DDR3 AXI for frame buffer?
//    Can add/test many in flight ~pipelined full AXI funcitonality?

// NUM_X_THREADS must evenly divide (FRAME_WIDTH/RAM_PIXEL_BUFFER_SIZE)
// NUM_Y_THREADS must evenly divide FRAME_HEIGHT
// RAM_PIXEL_BUFFER_SIZE is RAM width, number of pixels in x direction
// Include FRAME_BUF_INIT_DATA header
#include "frame_buf_init_data_16b.h" // Game of life RAM init data
#define ram_pixel_offset_t uint4_t
#define RAM_PIXEL_BUFFER_SIZE_LOG2 4
#define RAM_PIXEL_BUFFER_SIZE 16
#define DEV_CLK_MHZ 150.0
#define HOST_CLK_MHZ 55.0
#define NUM_X_THREADS 4
#define NUM_Y_THREADS 4
#define NUM_TOTAL_THREADS (NUM_X_THREADS*NUM_Y_THREADS)
#include "shared_dual_frame_buffer.c"

// Frame buffer reads N pixels at a time
// ~Convert that into function calls reading 1 pixel/cell at a time
// Very inefficient, reading N pixels to return just 1 for now...
/*uint1_t pixel_buf_read(uint32_t x, uint32_t y)
{
  // Read the pixels from the 'read' frame buffer
  uint16_t x_buffer_index = x >> RAM_PIXEL_BUFFER_SIZE_LOG2;
  n_pixels_t pixels = dual_frame_buf_read(x_buffer_index, y);
  __clk();
  // Select the single pixel offset of interest (bottom bits of x)
  ram_pixel_offset_t x_offset = x;
  return pixels.data[x_offset];
}*/

/*// 1 cached read
uint1_t pixel_buf_read(uint32_t x, uint32_t y)
{
  // Cache registers
  static uint16_t cache_x_buffer_index = FRAME_WIDTH;
  static uint16_t cache_y = FRAME_HEIGHT;
  static n_pixels_t cache_pixels;
  // Read the pixels from the 'read' frame buffer or from cache
  n_pixels_t pixels;
  uint16_t x_buffer_index = x >> RAM_PIXEL_BUFFER_SIZE_LOG2;
  uint1_t cache_match = (x_buffer_index==cache_x_buffer_index) & (y==cache_y);
  if(cache_match)
  {
    // Use cache
    pixels = cache_pixels;
  }
  else
  {
    // Read RAM and update cache
    pixels = dual_frame_buf_read(x_buffer_index, y);
    cache_x_buffer_index = x_buffer_index;
    cache_y = y;
    cache_pixels = pixels;
  }
  __clk();
  // Select the single pixel offset of interest (bottom bits of x)
  ram_pixel_offset_t x_offset = x;
  return pixels.data[x_offset];
}*/

// 3 'y' lines of reads cached
uint1_t pixel_buf_read(uint32_t x, uint32_t y)
{
  // Cache registers
  static uint16_t cache_x_buffer_index = FRAME_WIDTH;
  static uint16_t cache_y[3] = {FRAME_HEIGHT, FRAME_HEIGHT, FRAME_HEIGHT};
  static n_pixels_t cache_pixels[3];
  // Read the pixels from the 'read' frame buffer or from cache
  n_pixels_t pixels;
  uint16_t x_buffer_index = x >> RAM_PIXEL_BUFFER_SIZE_LOG2;
  // Check cache for match (only one will match)
  uint1_t cache_match = 0;
  uint8_t cache_sel; // Which of 3 cache lines
  uint32_t i;
  for(i=0; i<3; i+=1)
  {
    uint1_t match_i = (x_buffer_index==cache_x_buffer_index) & (y==cache_y[i]);
    cache_match |= match_i;
    if(match_i){
      cache_sel = i;
    }
  } 
  if(cache_match)
  {
    pixels = cache_pixels[cache_sel];
  }
  else
  {
    // Read RAM and update cache
    pixels = dual_frame_buf_read(x_buffer_index, y);
    // If got a new x pos to read then default clear/invalidate entire cache
    if(x_buffer_index != cache_x_buffer_index)
    {
      ARRAY_SET(cache_y, FRAME_HEIGHT, 3)
    }
    cache_x_buffer_index = x_buffer_index;
    // Least recently used style shift out cache entries
    // to make room for keeping new one most recent at [0]
    ARRAY_1SHIFT_INTO_BOTTOM(cache_y, 3, y)
    ARRAY_1SHIFT_INTO_BOTTOM(cache_pixels, 3, pixels)
  }
  //__clk();
  // Select the single pixel offset of interest (bottom bits of x)
  ram_pixel_offset_t x_offset = x;
  return pixels.data[x_offset];
}

// Demo application that plays Conway's Game of Life
// https://www.geeksforgeeks.org/program-for-conways-game-of-life/
// Can be used to derive HW FSMs
// Returns the count of alive neighbours around x,y
uint32_t count_neighbors(uint32_t x, uint32_t y){
  int32_t i, j;
  int32_t count=0;
  for(j=y-1;j<=y+1;j+=1){
      for(i=x-1; i<=x+1; i+=1){
          if(!( ((i==x) and (j==y)) or ((i<0) or (j<0)) or ((i>=FRAME_WIDTH) or (j>=FRAME_HEIGHT)))){
            uint1_t cell_alive = pixel_buf_read(i, j);
            //__clk();
            if(cell_alive==1){
              count+=1;
            }
          }
      }
  }
  //__clk();
  return count;
}
// Game of Life logic to determine if cell at x,y lives or dies
uint1_t cell_next_state(uint1_t cell_alive, uint32_t x, uint32_t y){
  //__clk();
  uint32_t neighbour_live_cells = count_neighbors(x, y);
  //__clk();
  uint1_t cell_alive_next;
  if((cell_alive==1) and ((neighbour_live_cells==2) or (neighbour_live_cells==3))){
      cell_alive_next=1;
  }else if((cell_alive==0) and (neighbour_live_cells==3)){
      cell_alive_next=1;
  }else{
      cell_alive_next=0;
  }
  return cell_alive_next;
}

/*// Func run for every pixel to get new pixel value
uint1_t pixel_kernel(uint16_t x, uint16_t y, uint1_t pixel)
{
  // Invert color of pixel
  return !pixel;
}*/

// Func run for every n_pixels_t chunk
void pixels_buffer_kernel(uint16_t x_buffer_index, uint16_t y)
{
  //__clk();
  // Read the pixels from the 'read' frame buffer
  n_pixels_t pixels = dual_frame_buf_read(x_buffer_index, y);
  //__clk();
  // Run kernel for each pixel
  uint32_t i;
  uint16_t x = x_buffer_index << RAM_PIXEL_BUFFER_SIZE_LOG2;
  for (i = 0; i < RAM_PIXEL_BUFFER_SIZE; i+=1)
  { 
    pixels.data[i] = cell_next_state(pixels.data[i], x+i, y);
  }  
  
  // Write pixels back to the 'write' frame buffer 
  dual_frame_buf_write(x_buffer_index, y, pixels);
}

// Single 'thread' state machine running pixels_buffer_kernel "sequentially" across an x,y range
void pixels_kernel_seq_range(
  uint16_t x_start, uint16_t x_end, 
  uint16_t y_start, uint16_t y_end)
{
  uint16_t x_buffer_index_start = x_start >> RAM_PIXEL_BUFFER_SIZE_LOG2;
  uint16_t x_buffer_index_end = x_end >> RAM_PIXEL_BUFFER_SIZE_LOG2;
  uint16_t x_buffer_index;
  uint16_t y;
  for(y=y_start; y<=y_end; y+=1)
  {
    for(x_buffer_index=x_buffer_index_start; x_buffer_index<=x_buffer_index_end; x_buffer_index+=1)
    {
      pixels_buffer_kernel(x_buffer_index, y);
      //__clk();
    }
  }
}
#include "pixels_kernel_seq_range_FSM.h"

// Module that runs pixel_kernel for every pixel
// by instantiating multiple simultaneous 'threads' of pixel_kernel_seq_range
void render_frame()
{
  // Wire up N parallel pixel_kernel_seq_range_FSM instances
  uint1_t thread_done[NUM_X_THREADS][NUM_Y_THREADS];
  uint32_t i,j;
  uint1_t all_threads_done;
  while(!all_threads_done)
  {
    pixels_kernel_seq_range_INPUT_t fsm_in[NUM_X_THREADS][NUM_Y_THREADS];
    pixels_kernel_seq_range_OUTPUT_t fsm_out[NUM_X_THREADS][NUM_Y_THREADS];
    all_threads_done = 1;
    for (i = 0; i < NUM_X_THREADS; i+=1)
    {
      for (j = 0; j < NUM_Y_THREADS; j+=1)
      {
        all_threads_done &= thread_done[i][j];
      }
    }
    
    uint16_t THREAD_X_SIZE = FRAME_WIDTH / NUM_X_THREADS;
    uint16_t THREAD_Y_SIZE = FRAME_HEIGHT / NUM_Y_THREADS;
    for (i = 0; i < NUM_X_THREADS; i+=1)
    {
      for (j = 0; j < NUM_Y_THREADS; j+=1)
      {
        if(!thread_done[i][j])
        {
          fsm_in[i][j].input_valid = 1;
          fsm_in[i][j].output_ready = 1;
          fsm_in[i][j].x_start = THREAD_X_SIZE*i;
          fsm_in[i][j].x_end = (THREAD_X_SIZE*(i+1))-1;
          fsm_in[i][j].y_start = THREAD_Y_SIZE*j;
          fsm_in[i][j].y_end = (THREAD_Y_SIZE*(j+1))-1;
          fsm_out[i][j] = pixels_kernel_seq_range_FSM(fsm_in[i][j]);
          thread_done[i][j] = fsm_out[i][j].output_valid;
        }
        //all_threads_done &= thread_done[i][j]; // Longer path
      }
    }
    __clk(); // REQUIRED
  }
  // Final step in rendering frame is switching to read from newly rendered frame buffer
  frame_buffer_read_port_sel = !frame_buffer_read_port_sel;
}

// Measure how long it takes to render frame with marked debug chipscope signal
DEBUG_REG_DECL(uint32_t, last_render_time)
uint32_t host_clk_counter;
void main()
{
  uint32_t start_time;
  while(1)
  {
    start_time = host_clk_counter;
    // Render frame
    render_frame();
    last_render_time = host_clk_counter - start_time;
  }
}
// Wrap up main FSM as top level
#include "main_FSM.h"
MAIN_MHZ(main_wrapper, HOST_CLK_MHZ)
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
  // Counter lives here on ticking host clock
  static uint32_t host_clk_counter_reg;
  host_clk_counter = host_clk_counter_reg;
  host_clk_counter_reg += 1;
}
