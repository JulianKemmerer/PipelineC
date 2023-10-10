// Code to share Mandelbrot calculation hardware
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
// Consists of devices:
//  one to calculate the x,y->complex screen position
//  and another for the Mandelbrot iterations
//  and a final for the iteration count to 8b color scaling output

// PipelineC types
#include "compiler.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
//#define float float_8_11_t
#define float_lshift(x,shift) ((x)<<(shift))

#define MANDELBROT_DEV_CLK_MHZ 160.0

// Complex numbers as pair of floats
typedef struct complex_t
{
  float re;
  float im;
}complex_t;

// Screen bounds
typedef struct screen_state_t
{
  // Plot window
  float re_start;
  float re_width;
  float im_start;
  float im_height;
}screen_state_t;
screen_state_t screen_state_t_INIT = {
  .re_start = -2.0, 
  .re_width = 3.0,
  .im_start = -1.0,
  .im_height = 2.0
};

// Screen position to complex value transform device:

// WTF TIMING LOOPS https://github.com/JulianKemmerer/PipelineC/issues/172
// Had to use this wrapper to make it not find timing loop 
// sigh... not enough time in life to investigate right now...
float vivado_is_a_pos_dumb_func(float a, float b, float c)
{
  return a * b * c;
}
// The pipeline
typedef struct screen_to_complex_in_t{
  uint16_t x;
  uint16_t y;
  screen_state_t state;
}screen_to_complex_in_t;
complex_t screen_to_complex_func(screen_to_complex_in_t inputs)
{
  complex_t c = {
    inputs.state.re_start + vivado_is_a_pos_dumb_func((float)inputs.x, (1.0f/(float)FRAME_WIDTH), inputs.state.re_width),
    inputs.state.im_start + vivado_is_a_pos_dumb_func((float)inputs.y, (1.0f/(float)FRAME_HEIGHT), inputs.state.im_height)
    };
  return c;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         screen_to_complex
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     complex_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         screen_to_complex_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      screen_to_complex_in_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_USER_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"


// Do N Mandelbrot iterations per call to mandelbrot_iter_func
#define ITER_CHUNK_SIZE 1
#define MAX_ITER 32
typedef struct mandelbrot_iter_t{
  complex_t c;
  complex_t z;
  complex_t z_squared;
  uint1_t escaped;
  uint32_t n;
}mandelbrot_iter_t;
#define ESCAPE 2.0
mandelbrot_iter_t mandelbrot_iter_func(mandelbrot_iter_t inputs)
{
  mandelbrot_iter_t rv = inputs;
  uint32_t i;
  for(i=0;i<ITER_CHUNK_SIZE;i+=1)
  {
    // Mimic while loop
    if(!rv.escaped & (rv.n < MAX_ITER))
    {
      rv.z.im = float_lshift((rv.z.re*rv.z.im), 1) + rv.c.im;
      rv.z.re = rv.z_squared.re - rv.z_squared.im + rv.c.re;
      rv.z_squared.re = rv.z.re * rv.z.re;
      rv.z_squared.im = rv.z.im * rv.z.im;
      rv.n = rv.n + 1;
      rv.escaped = (rv.z_squared.re+rv.z_squared.im) > (ESCAPE*ESCAPE);
    }
  }
  return rv;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         mandelbrot_iter
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     mandelbrot_iter_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         mandelbrot_iter_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      mandelbrot_iter_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_USER_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h" // Not using _no_io_regs


/*
uint8_t iter_to_8b_func(uint32_t n)
{
  uint8_t color = 255 - (int32_t)((float)n *(255.0/(float)MAX_ITER));
  return color;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         iter_to_8b
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     uint8_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         iter_to_8b_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      uint32_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_USER_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"
*/

/* COLOR SIMPLE LOOKUP TABLE
https://stackoverflow.com/questions/16500656/which-color-gradient-is-used-to-color-mandelbrot-in-wikipedia
*/
pixel_t iter_to_color_func(uint32_t n)
{
  pixel_t p; // Default black
  if((n < MAX_ITER) & (n > 0)){
    //uint4_t index = (iter_t)n % 16;
    // Fake modulo since not implemented for integers yet and simple for pow2 16...
    /*uint32_t div_16 = n >> 4; // / 16;
    uint32_t total_16 = div_16 << 4; // * 16;
    uint32_t mod_16 = n - total_16;
    uint4_t index = mod_16;*/
    uint4_t index = n; // works? same as mod pow2 only use bottom bits?
    pixel_t color_lut[16];
    color_lut[0].r =  66;  color_lut[0].g =  30;  color_lut[0].b =  15;
    color_lut[1].r =  25;  color_lut[1].g =  7;   color_lut[1].b =  26;
    color_lut[2].r =  9;   color_lut[2].g =  1;   color_lut[2].b =  47;
    color_lut[3].r =  4;   color_lut[3].g =  4;   color_lut[3].b =  73;
    color_lut[4].r =  0;   color_lut[4].g =  7;   color_lut[4].b =  100;
    color_lut[5].r =  12;  color_lut[5].g =  44;  color_lut[5].b =  138;
    color_lut[6].r =  24;  color_lut[6].g =  82;  color_lut[6].b =  177;
    color_lut[7].r =  57;  color_lut[7].g =  125; color_lut[7].b =  209;
    color_lut[8].r =  134; color_lut[8].g =  181; color_lut[8].b =  229;
    color_lut[9].r =  211; color_lut[9].g =  236; color_lut[9].b =  248;
    color_lut[10].r = 241; color_lut[10].g = 233; color_lut[10].b = 191;
    color_lut[11].r = 248; color_lut[11].g = 201; color_lut[11].b = 95;
    color_lut[12].r = 255; color_lut[12].g = 170; color_lut[12].b = 0;
    color_lut[13].r = 204; color_lut[13].g = 128; color_lut[13].b = 0;
    color_lut[14].r = 153; color_lut[14].g = 87;  color_lut[14].b = 0;
    color_lut[15].r = 106; color_lut[15].g = 52;  color_lut[15].b = 3;
    p = color_lut[index];
  }
  return p;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         iter_to_color
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     pixel_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         iter_to_color_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      uint32_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_USER_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"

// The high level mandelbrot_kernel state machine can be time multiplexed coroutine style
// if written manually as an FSM (FSM of FSMs here) using async start and stop for long ops
// Like a CPU context switching to let a process wait for IO
typedef enum mandelbrot_kernel_fsm_state_t{
  screen_to_complex_START,
  screen_to_complex_FINISH,
  mandelbrot_iter_START,
  mandelbrot_iter_FINISH,
  iter_to_color_START,
  iter_to_color_FINISH
}mandelbrot_kernel_fsm_state_t;
typedef struct mandelbrot_kernel_state_t{
  mandelbrot_kernel_fsm_state_t fsm_state;
  pixel_t pixel;
  screen_state_t screen_state;
  uint16_t x;
  uint16_t y;
  mandelbrot_iter_t iter;
  screen_to_complex_in_t stc;
  pixel_t p;
  uint1_t done;
}mandelbrot_kernel_state_t;
mandelbrot_kernel_state_t mandelbrot_kernel_fsm(mandelbrot_kernel_state_t state)
{
  state.done = 0;
  if(state.fsm_state==screen_to_complex_START){
    // Convert pixel coordinate to complex number 
    state.stc.state = state.screen_state;
    state.stc.x = state.x;
    state.stc.y = state.y;
    /*state.iter.c = */screen_to_complex_start(state.stc);
    state.fsm_state = screen_to_complex_FINISH;
  }else if(state.fsm_state==screen_to_complex_FINISH){
    state.iter.c = screen_to_complex_finish(/*state.stc*/);
    // Do the mandelbrot iters
    state.iter.z.re = 0.0;
    state.iter.z.im = 0.0;
    state.iter.z_squared.re = 0.0;
    state.iter.z_squared.im = 0.0;
    state.iter.n = 0;
    state.iter.escaped = 0;
    state.fsm_state = mandelbrot_iter_START;
  }else if(state.fsm_state==mandelbrot_iter_START){
    if(!state.iter.escaped & (state.iter.n < MAX_ITER)){
      /*state.iter = */mandelbrot_iter_start(state.iter);
      state.fsm_state = mandelbrot_iter_FINISH;
    }else{
      state.fsm_state = iter_to_color_START;
    }
  }else if(state.fsm_state==mandelbrot_iter_FINISH){
    state.iter = mandelbrot_iter_finish(/*state.iter*/);
    state.fsm_state = mandelbrot_iter_START;
  }else if(state.fsm_state==iter_to_color_START){
    // The color depends on the number of iterations
    /*state.p = */iter_to_color_start(state.iter.n);
    state.fsm_state = iter_to_color_FINISH;
  }else if(state.fsm_state==iter_to_color_FINISH){
    state.p = iter_to_color_finish(/*state.iter.n*/);
    state.done = 1;
    state.fsm_state = screen_to_complex_START; // Probably not needed
  }
  return state;
}

// Single 'thread' state machine implementing N '~coroutine' 'software' thread instances
// of the mandelbrot kernel
typedef struct n_pixels_t{
  pixel_t data[NUM_SW_THREADS];
}n_pixels_t;
n_pixels_t n_time_multiplexed_mandelbrot_kernel_fsm(
  screen_state_t screen_state,
  uint16_t x[NUM_SW_THREADS], 
  uint16_t y[NUM_SW_THREADS]
){
  n_pixels_t rv;
  mandelbrot_kernel_state_t kernel_state[NUM_SW_THREADS];
  // INIT
  uint32_t i;
  for(i = 0; i < NUM_SW_THREADS; i+=1)
  {
    kernel_state[i].fsm_state = screen_to_complex_START; // Probabaly not needed
    kernel_state[i].screen_state = screen_state;
    kernel_state[i].x = x[i];
    kernel_state[i].y = y[i];
  }
  // LOOP doing N 'coroutine'/fsms until done
  uint1_t thread_done[NUM_SW_THREADS];
  uint1_t all_threads_done = 0;
  do
  {
    all_threads_done = 1;
    for(i = 0; i < NUM_SW_THREADS; i+=1)
    {
      // operate on front of shift reg [0] (as opposed to random[i])
      if(!thread_done[0]){
        kernel_state[0] = mandelbrot_kernel_fsm(kernel_state[0]);
        rv.data[0] = kernel_state[0].p;
        thread_done[0] = kernel_state[0].done;
        all_threads_done &= thread_done[0];
      }
      // And then shift the reg to prepare next at [0]
      ARRAY_1ROT_DOWN(mandelbrot_kernel_state_t, kernel_state, NUM_SW_THREADS)
      ARRAY_1ROT_DOWN(pixel_t, rv.data, NUM_SW_THREADS)
      ARRAY_1ROT_DOWN(uint1_t, thread_done, NUM_SW_THREADS)
    }
  }while(!all_threads_done);
  return rv;
}


// User interface + animation stuff:

// Access to board buttons and switches
#include "buttons/buttons.c"
#include "switches/switches.c"

// User input
typedef struct user_input_t
{
  uint1_t up;
  uint1_t down;
  uint1_t left;
  uint1_t right;
  uint1_t zoom_in;
  uint1_t zoom_out;
}user_input_t;
user_input_t get_user_input()
{
  user_input_t i;
  // Select which buttons and switches do what?
  i.up = buttons >> 0;
  i.down = buttons >> 1;
  i.left = buttons >> 2;
  i.right = buttons >> 3;
  i.zoom_in = switches >> 0;
  i.zoom_out = switches >> 1;
  return i;
}

// Logic for animating state each frame
screen_state_t next_state_func(screen_state_t state)
{
  // Read input controls from user
  user_input_t i = get_user_input();
  
  float XY_SCALE = 0.002; // X-Y movement
  float Z_SCALE = 0.002; // Zoom movement
  
  // Move window right left (flipped) or up down
  // Using only a single FP adder
  float re_inc = (XY_SCALE*state.re_width);
  float im_inc = (XY_SCALE*state.im_height);
  float val_to_inc;
  float inc;
  if(i.left|i.right)
  {
    if(i.right)
    {
      re_inc = -re_inc;
    }
    val_to_inc = state.re_start;
    inc = re_inc;
  }
  else if(i.up|i.down)
  {
    if(i.down)
    {
      im_inc = -im_inc;
    }
    val_to_inc = state.im_start;
    inc = im_inc;
  }
  float incremented_val = val_to_inc + inc; 
  if(i.left|i.right)
  {
    state.re_start = incremented_val;
  }
  else if(i.up|i.down)
  {
    state.im_start = incremented_val;
  }  
  
  // Move window in and out
  float zoom_mult;
  if(i.zoom_in)
  {
    zoom_mult = (1.0-Z_SCALE);
  }
  else
  {
    zoom_mult = (1.0+Z_SCALE);
  }
  if(i.zoom_in|i.zoom_out)
  {
    state.re_width *= zoom_mult;
    state.im_height *= zoom_mult;
  }
  
  return state;
}

// Just use a slow clock and comb. compute next state since only needed as fast as 60Hz
// Need a clock >=60Hz and slow enough to easily meet timing
// (could make a 60Hz clock like was done for sphery
// but in this case how to align with actual frame render etc?)
screen_state_t next_screen_state;
#pragma ASYNC_WIRE next_screen_state
uint1_t start_next_state;
#pragma ASYNC_WIRE start_next_state
#pragma MAIN_MHZ frame_logic 6.25
void frame_logic()
{
  static uint1_t power_on_reset = 1;
  static uint1_t start_next_state_reg; // Toggle detect reg
  static screen_state_t state_reg; // The state register TODO can use screen_state_t_INIT? in decl?
  next_screen_state = state_reg; // Drives state wire directly

  // Update date when 'start' toggle happens
  if(start_next_state != start_next_state_reg)
  {
    state_reg = next_state_func(state_reg);
  }

  // Input regs
  start_next_state_reg = start_next_state;

  // Reset
  if(power_on_reset){
    state_reg = screen_state_t_INIT;
  }
  power_on_reset = 0;
}

screen_state_t get_next_screen_state()
{
  // Grab updated next state to render
  screen_state_t rv = next_screen_state;
  // Signal to compute next per frame state w/ toggle
  start_next_state = !start_next_state;
  return rv;
}