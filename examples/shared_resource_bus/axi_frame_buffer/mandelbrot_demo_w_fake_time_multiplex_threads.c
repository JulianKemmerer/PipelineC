// Copy of graphics_demo.c baseline
// modified to do Mandelbrot demo

#pragma PART "xc7a100tcsg324-1"
#include "compiler.h"
#include "debug_port.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"

#define HOST_CLK_MHZ 40.0
// Threads must evenly divide frame width and height
#define NUM_HW_THREADS 4 // Split x direction
#define NUM_HW_THREADS_LOG2 2
#define NUM_SW_THREADS 16 // 16 MAX for SHARED RES BUS FIFO
#define NUM_USER_THREADS NUM_HW_THREADS
#include "dual_frame_buffer.c"

// Mandelbrot kernel
#include "shared_mandelbrot_dev_w_fake_time_multiplex_threads.c"
//#include "shared_mandelbrot_dev_fp_ops.c"

typedef struct kernel_args_t{
  uint1_t do_clear;
  screen_state_t state;
}kernel_args_t;

// Wrap n_time_multiplexed_mandelbrot_kernel_fsm to do it or clearing
// REPALCES ABOVE pixel_kernel ? 
void n_time_multiplexed_kernel_fsm(
  kernel_args_t args,
  uint16_t x[NUM_SW_THREADS],
  uint16_t y[NUM_SW_THREADS]
){
  // Zeroed pixels
  n_pixels_t n_pixels = {0};
  if(!args.do_clear){
    // Compute pixels from x and y values
    n_pixels = n_time_multiplexed_mandelbrot_kernel_fsm(args.state, x, y);
  }
  // Write back pixels // TODO convert to START,FINISH
  uint32_t i;
  for(i = 0; i < NUM_SW_THREADS; i+=1){
    // Write [0] then shift
    frame_buf_write(x[0], y[0], n_pixels.data[0]);
    ARRAY_1ROT_DOWN(uint16_t, x, NUM_SW_THREADS)
    ARRAY_1ROT_DOWN(uint16_t, y, NUM_SW_THREADS)
    ARRAY_1ROT_DOWN(pixel_t, n_pixels.data, NUM_SW_THREADS)
  }
}

// Single 'thread' state machine running pixel_kernel "sequentially" across an x,y range
void pixels_kernel_seq_range(
  kernel_args_t args,
  uint16_t x_start, uint16_t x_end, 
  uint16_t y_start, uint16_t y_end)
{
  uint16_t x;
  for(x=x_start; x<=x_end; x+=TILE_FACTOR)
  {
    uint16_t y = y_start;
    while(y<=y_end){
      uint16_t thread_x[NUM_SW_THREADS];
      uint16_t thread_y[NUM_SW_THREADS];
      uint32_t i;
      for (i = 0; i < NUM_SW_THREADS; i+=1)
      {
        thread_x[i] = x;
        thread_y[i] = y + (i*TILE_FACTOR);
      }
      y += (NUM_SW_THREADS*TILE_FACTOR);
      n_time_multiplexed_kernel_fsm(args, thread_x, thread_y);
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
  uint1_t thread_done[NUM_HW_THREADS];
  uint32_t i;
  uint1_t all_threads_done;
  while(!all_threads_done)
  {
    pixels_kernel_seq_range_INPUT_t fsm_in[NUM_HW_THREADS];
    pixels_kernel_seq_range_OUTPUT_t fsm_out[NUM_HW_THREADS];
    all_threads_done = 1;
    for (i = 0; i < NUM_HW_THREADS; i+=1)
    {
      all_threads_done &= thread_done[i];
    }
    
    uint16_t thread_x_size = width >> NUM_HW_THREADS_LOG2;
    uint16_t thread_y_size = height;
    for (i = 0; i < NUM_HW_THREADS; i+=1)
    {
      if(!thread_done[i])
      {
        fsm_in[i].input_valid = 1;
        fsm_in[i].output_ready = 1;
        fsm_in[i].args = args;
        fsm_in[i].x_start = (thread_x_size*i) + x;
        fsm_in[i].x_end = fsm_in[i].x_start + thread_x_size - 1;
        fsm_in[i].y_start = y;
        fsm_in[i].y_end = fsm_in[i].y_start + thread_y_size - 1;
        fsm_out[i] = pixels_kernel_seq_range_FSM(fsm_in[i]);
        thread_done[i] = fsm_out[i].output_valid;
      }
      //all_threads_done &= thread_done[i][j]; // Longer path
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
  __clk();

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
    // Compute updated next state to render
    args.state = get_next_screen_state();
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
