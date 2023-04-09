#pragma PART "xc7a35ticsg324-1l" 
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

// Demo GoL next
//
//
// FUTURE How to wrap/macro make any new 'resource' (like the frame buffer or autopipeline)
//
// Extend to use DDR3 AXI for frame buffer?
//    Can add/test many in flight ~pipelined full AXI funcitonality?
// Extend to use a autopipeline - sphery? is read of state write to frame buffer only
#define HOST_CLK_MHZ 35.0

// NUM_THREADS Divides FRAME_WIDTH
#define NUM_THREADS 4
#include "shared_dual_frame_buffer.c"


// Demo 'application' state machine that inverts pixels every second

// Func run for every pixel to get new pixel value
uint1_t pixel_kernel(uint16_t x, uint16_t y, uint1_t pixel)
{
  // Invert color of pixel
  return !pixel;
}

// Func run for every n_pixels_t chunk
void pixels_buffer_kernel(uint16_t x_buffer_index, uint16_t y)
{
  // Read the pixels from the 'read' frame buffer
  n_pixels_t pixels = frame_buf_read(frame_buffer_read_port_sel, x_buffer_index, y);
  
  // Run kernel for each pixel
  uint32_t i;
  uint16_t x = x_buffer_index << RAM_PIXEL_BUFFER_SIZE_LOG2;
  for (i = 0; i < RAM_PIXEL_BUFFER_SIZE; i+=1)
  {
    pixels.data[i] = pixel_kernel(x+i, y, pixels.data[i]);
  }  
  
  // Write pixels back to the 'write' frame buffer (opposite read)
  frame_buf_write(!frame_buffer_read_port_sel, x_buffer_index, y, pixels);
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
    }
  }
}
#include "pixels_kernel_seq_range_FSM.h"

// Module that runs pixel_kernel for every pixel
// by instantiating multiple simultaneous 'threads' of pixel_kernel_seq_range
void render_frame()
{
  // Wire up N parallel pixel_kernel_seq_range_FSM instances
  uint1_t thread_done[NUM_THREADS];
  uint32_t i;
  uint1_t all_threads_done;
  while(!all_threads_done)
  {
    pixels_kernel_seq_range_INPUT_t fsm_in[NUM_THREADS];
    pixels_kernel_seq_range_OUTPUT_t fsm_out[NUM_THREADS];
    all_threads_done = 1;
    
    uint16_t THREAD_X_SIZE = FRAME_WIDTH / NUM_THREADS;
    for (i = 0; i < NUM_THREADS; i+=1)
    {
      if(!thread_done[i])
      {
        fsm_in[i].input_valid = 1;
        fsm_in[i].output_ready = 1;
        fsm_in[i].x_start = THREAD_X_SIZE*i;
        fsm_in[i].x_end = (THREAD_X_SIZE*(i+1))-1;
        fsm_in[i].y_start = 0;
        fsm_in[i].y_end = FRAME_HEIGHT-1;
        fsm_out[i] = pixels_kernel_seq_range_FSM(fsm_in[i]);
        thread_done[i] = fsm_out[i].output_valid;
      }
      all_threads_done &= thread_done[i];
    }
    __clk();
  }
  // Final step in rendering frame is switching to read from newly rendered frame buffer
  frame_buffer_read_port_sel = !frame_buffer_read_port_sel;
}

void main()
{
  while(1)
  {
    // Wait a few seconds
    uint32_t sec_ticks_remaining = 10 * (uint32_t)(HOST_CLK_MHZ * 1.0e6);
    while(sec_ticks_remaining > 0)
    {
      sec_ticks_remaining -= 1;
      __clk();
    }

    // Render frame
    render_frame();
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
}
