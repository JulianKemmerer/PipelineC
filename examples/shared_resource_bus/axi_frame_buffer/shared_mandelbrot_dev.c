// Code to share Mandelbrot calculation hardware
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
// Consists of devices:
//  one to calculate the x,y->complex screen position
//  and another for the Mandelbrot iterations
//  and a final for the iteration count to 8b color scaling output
//  TODO one for RGB coloring?

// PipelineC types
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
//#define float float_8_11_t
#define float_lshift(x,shift) ((x)<<(shift))

#define MANDELBROT_DEV_CLK_MHZ 6.25

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


typedef struct mandelbrot_iter_t{
  complex_t c;
  complex_t z;
  complex_t z_squared;
  uint1_t escaped;
}mandelbrot_iter_t;
#define ESCAPE 2.0
mandelbrot_iter_t mandelbrot_iter_func(mandelbrot_iter_t inputs)
{
  mandelbrot_iter_t rv = inputs;
  rv.z.im = float_lshift((rv.z.re*rv.z.im), 1) + rv.c.im;
  rv.z.re = rv.z_squared.re - rv.z_squared.im + rv.c.re;
  rv.z_squared.re = rv.z.re * rv.z.re;
  rv.z_squared.im = rv.z.im * rv.z.im;
  rv.escaped = (rv.z_squared.re+rv.z_squared.im) > (ESCAPE*ESCAPE);
  return rv;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         mandelbrot_iter
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     mandelbrot_iter_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         mandelbrot_iter_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      mandelbrot_iter_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_USER_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"


#define MAX_ITER 16
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


pixel_t mandelbrot_kernel(screen_state_t state, uint16_t x, uint16_t y)
{
  mandelbrot_iter_t iter;

  // Convert pixel coordinate to complex number
  screen_to_complex_in_t stc;
  stc.state = state;
  stc.x = x;
  stc.y = y;
  iter.c = screen_to_complex(stc);

  // Do the mandelbrot iters
  iter.z.re = 0.0;
  iter.z.im = 0.0;
  iter.z_squared.re = 0.0;
  iter.z_squared.im = 0.0;
  uint32_t n = 0;
  iter.escaped = 0;
  while(!iter.escaped & (n < MAX_ITER)){
    mandelbrot_iter_t iter = mandelbrot_iter(iter);
    n += 1;
  }

  // The color depends on the number of iterations
  uint8_t color = iter_to_8b(n);
  pixel_t p;
  p.r = color;
  p.g = color;
  p.b = color;
  return p;
}


/*
// Access to board buttons and switches
#include "../buttons/buttons.c"
#include "../switches/switches.c"

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
inline user_input_t get_user_input()
{
  user_input_t i;
  // For now only exists in hardware
  #ifdef __PIPELINEC__
  // Select which buttons and switches do what?
  i.up = buttons >> 0;
  i.down = buttons >> 1;
  i.left = buttons >> 2;
  i.right = buttons >> 3;
  i.zoom_in = switches >> 0;
  i.zoom_out = switches >> 1;
  #else
  // TODO user IO for running as C code
  i.up = 0;
  i.down = 0;
  i.left = 0;
  i.right = 0;
  i.zoom_in = 0;
  i.zoom_out = 0;
  #endif
  return i;
}


// State to return to at reset
screen_state_t reset_values()
{
  screen_state_t state;
  // Start zoomed in
  state.re_start = -2.0;
  state.re_width = 3.0;
  state.im_start = -1.0;
  state.im_height = 2.0;
  return state;
}

// Logic for animating state each frame
screen_state_t next_state_func(uint1_t reset, screen_state_t state)
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


*/