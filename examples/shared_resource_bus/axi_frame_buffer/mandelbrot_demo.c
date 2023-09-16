// Copy of graphics_demo.c baseline
// modified to do Mandelbrot demo

/* TODO:
Make slow single clock Verilator sim work
Does fast DDR version work now?
*/

#pragma PART "xc7a100tcsg324-1"
#include "compiler.h"
#include "debug_port.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"

#define HOST_CLK_MHZ 25.0 // 15.0
// Threads must evenly divide frame width and height
#define NUM_X_THREADS 2
#define NUM_X_THREADS_LOG2 1
#define NUM_Y_THREADS 2
#define NUM_Y_THREADS_LOG2 1
#define NUM_USER_THREADS (NUM_X_THREADS*NUM_Y_THREADS)
#include "dual_frame_buffer.c"

// Mandelbrot kernel
#include "shared_mandelbrot_dev.c"

typedef struct kernel_args_t{
  uint1_t do_clear;
  screen_state_t state;
}kernel_args_t;
//pixel_t pixel, 
pixel_t pixel_kernel(kernel_args_t args, uint16_t x, uint16_t y)
{
  pixel_t pixel = {0};
  if(args.do_clear){
    frame_buf_write(x, y, pixel);
  }else{
    pixel = mandelbrot_kernel(args.state, x, y);
  }
  return pixel;
}

// Single 'thread' state machine running pixel_kernel "sequentially" across an x,y range
void pixels_kernel_seq_range(
  kernel_args_t args,
  uint16_t x_start, uint16_t x_end, 
  uint16_t y_start, uint16_t y_end)
{
  uint16_t x;
  uint16_t y;
  for(y=y_start; y<=y_end; y+=TILE_FACTOR)
  {
    for(x=x_start; x<=x_end; x+=TILE_FACTOR)
    {
      // Read the pixel from the 'read' frame buffer
      //pixel_t pixel = frame_buf_read(x, y);
      pixel_t pixel = pixel_kernel(args, x, y); // pixel,
      // Write pixel back to the 'write' frame buffer
      frame_buf_write(x, y, pixel);
    }
  }
}
#include "pixels_kernel_seq_range_FSM.h"

// Module that runs pixel_kernel for every pixel
// by instantiating multiple simultaneous 'threads' of pixel_kernel_seq_range
void render_demo_kernel(
  kernel_args_t args,
  uint16_t x, uint16_t width,
  uint16_t y, uint16_t height
){
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
    
    uint16_t thread_x_size = width >> NUM_X_THREADS_LOG2;
    uint16_t thread_y_size = height >> NUM_Y_THREADS_LOG2;
    for (i = 0; i < NUM_X_THREADS; i+=1)
    {
      for (j = 0; j < NUM_Y_THREADS; j+=1)
      {
        if(!thread_done[i][j])
        {
          fsm_in[i][j].input_valid = 1;
          fsm_in[i][j].output_ready = 1;
          fsm_in[i][j].args = args;
          fsm_in[i][j].x_start = (thread_x_size*i) + x;
          fsm_in[i][j].x_end = fsm_in[i][j].x_start + thread_x_size - 1;
          fsm_in[i][j].y_start = (thread_y_size*j) + y;
          fsm_in[i][j].y_end = fsm_in[i][j].y_start + thread_y_size - 1;
          fsm_out[i][j] = pixels_kernel_seq_range_FSM(fsm_in[i][j]);
          thread_done[i][j] = fsm_out[i][j].output_valid;
        }
        //all_threads_done &= thread_done[i][j]; // Longer path
      }
    }
    __clk(); // REQUIRED
  }
  
}

// Measure how long it takes to render frame with marked debug chipscope signal
DEBUG_REG_DECL(uint32_t, last_render_time)
uint32_t host_clk_counter;

// Reset wire from Xilinx memory controller
#ifdef AXI_RAM_MODE_DDR
//uint1_t xil_mem_rst_done_wire;
#endif

// Main loop drawing kernels on the screen
void main()
{
  kernel_args_t args;

  // Wait for DDR reset to be done
  #ifdef AXI_RAM_MODE_DDR
  /*while(!xil_mem_rst_done_wire)
  {
    __clk();
  }*/
  while(host_clk_counter < (uint32_t)(HOST_CLK_MHZ*1.0e6)){
    __clk();
  }

  // Do renders of cleared frame, for both buffers
  args.do_clear = 1;
  frame_buffer_read_port_sel = !frame_buffer_read_port_sel;
  render_demo_kernel(args, 0, FRAME_WIDTH, 0, FRAME_HEIGHT);
  frame_buffer_read_port_sel = !frame_buffer_read_port_sel;
  render_demo_kernel(args, 0, FRAME_WIDTH, 0, FRAME_HEIGHT);
  args.do_clear = 0;
  #endif

  // Start render loop
  uint32_t start_time;
  uint32_t iter_count = 0;
  // Start zoomed in
  args.state = screen_state_t_INIT;
  while(1)
  {
    // First step in rendering is reset debug counter
    start_time = host_clk_counter;
    
    // Render kernels

    // Demo kernel is entire frame
    render_demo_kernel(args, 0, FRAME_WIDTH, 0, FRAME_HEIGHT);

    // Final steps in rendering frame:
    // Record render time
    last_render_time = host_clk_counter - start_time;
    // switching to read from newly rendered frame buffer
    frame_buffer_read_port_sel = !frame_buffer_read_port_sel;
    // Grab updated next state to render
    args.state = next_screen_state;
    // Signal to compute next per frame state w/ toggle
    start_next_state = !start_next_state;
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
  #ifdef AXI_RAM_MODE_DDR
  // Reg xil signal for timing
  //static uint1_t xil_mem_rst_done_reg;
  //xil_mem_rst_done_wire = xil_mem_rst_done_reg;
  //xil_mem_rst_done_reg = xil_mem_rst_done;
  #endif
}
