// Code to share Mandelbrot calculation hardware
// See docs: https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus
// Consists of devices:
//  one to calculate the x,y->complex screen position
//  and another for the Mandelbrot iterations
//  and a final for the iteration count to 8b color scaling output

// PipelineC types
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
//#define float float_8_11_t
#define float_lshift(x,shift) ((x)<<(shift))

#define MANDELBROT_DEV_CLK_MHZ 40.0

#define NUM_FP_OP_THREADS (NUM_USER_THREADS+1) // Including main thread for next state computation

// FP operator devices to share
#define MANDELBROT_DEVS_ARE_FP_OPS

typedef struct fp_op_inputs_t{
  float l;
  float r;
}fp_op_inputs_t;
float fp_mult_func(fp_op_inputs_t i)
{
  return i.l * i.r;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         fp_mult_dev
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     float
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         fp_mult_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      fp_op_inputs_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_FP_OP_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"
// Extra unwrap of fp_op_inputs_t
float fp_mult(float l, float r){
  fp_op_inputs_t i;
  i.l = l;
  i.r = r;
  float rv = fp_mult_dev(i);
  return rv;
}
// Async start and finish wrappers
void fp_mult_start(float l, float r){
  fp_op_inputs_t i;
  i.l = l;
  i.r = r;
  fp_mult_dev_start(i);
}
float fp_mult_finish(){
  float rv = fp_mult_dev_finish();
  return rv;
}

float fp_add_func(fp_op_inputs_t i)
{
  return i.l + i.r;
}
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         fp_add_dev
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     float
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         fp_add_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      fp_op_inputs_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_FP_OP_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  MANDELBROT_DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"
// Extra unwrap of fp_op_inputs_t
float fp_add(float l, float r){
  fp_op_inputs_t i;
  i.l = l;
  i.r = r;
  float rv = fp_add_dev(i);
  return rv;
}
// Sub is inverted add
float fp_sub(float l, float r){
  float rv = fp_add(l, -r);
  return rv;
}
// Async start and finish wrappers
void fp_add_start(float l, float r){
  fp_op_inputs_t i;
  i.l = l;
  i.r = r;
  fp_add_dev_start(i);
}
float fp_add_finish(){
  float rv = fp_add_dev_finish();
  return rv;
}
void fp_sub_start(float l, float r){
  fp_add_start(l, -r);
}
float fp_sub_finish(){
  float rv = fp_add_finish();
  return rv;
}

//TODO fix syntax for hacky derived fsm?

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
// The pipeline
typedef struct screen_to_complex_in_t{
  uint16_t x;
  uint16_t y;
  screen_state_t state;
}screen_to_complex_in_t;
complex_t screen_to_complex_func(screen_to_complex_in_t inputs)
{
  complex_t c;
  float re_temp0 = fp_mult(((float)inputs.x), (1.0f/(float)FRAME_WIDTH));
  float re_temp1 = fp_mult(re_temp0, inputs.state.re_width);
  c.re = fp_add(inputs.state.re_start, re_temp1);
  float im_temp0 = fp_mult(((float)inputs.y), (1.0f/(float)FRAME_HEIGHT));
  float im_temp1 = fp_mult(im_temp0, inputs.state.im_height);
  c.im = fp_add(inputs.state.im_start, im_temp1);
  return c;
}


// Do Mandelbrot iteration
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

  /*float re_mult_im = */ fp_mult_start(rv.z.re, rv.z.im); /*float re_minus_im = */ fp_sub_start(rv.z_squared.re, rv.z_squared.im);
  float re_mult_im = fp_mult_finish(/*rv.z.re, rv.z.im*/); float re_minus_im = fp_sub_finish(/*rv.z_squared.re, rv.z_squared.im*/);
  /////
  /*rv.z.im = */ fp_add_start(float_lshift(re_mult_im, 1), rv.c.im); /*rv.z.re = */ fp_add_start(re_minus_im, rv.c.re);
  rv.z.im = fp_add_finish(/*float_lshift(re_mult_im, 1), rv.c.im*/); rv.z.re = fp_add_finish(/*re_minus_im, rv.c.re*/);
  /////
  /*rv.z_squared.re = */ fp_mult_start(rv.z.re, rv.z.re); /*rv.z_squared.im = */ fp_mult_start(rv.z.im, rv.z.im); 
  rv.z_squared.re = fp_mult_finish(/*rv.z.re, rv.z.re*/); rv.z_squared.im = fp_mult_finish(/*rv.z.im, rv.z.im*/); 
  /////
  /*float re_plus_im = */ fp_add_start(rv.z_squared.re, rv.z_squared.im); 
  float re_plus_im = fp_add_finish(/*rv.z_squared.re, rv.z_squared.im*/); 

  // Not complex FP ops:
  rv.n = rv.n + 1;
  rv.escaped = re_plus_im > (ESCAPE*ESCAPE);
  return rv;
}


/* COLOR SIMPLE LOOKUP TABLE
https://stackoverflow.com/questions/16500656/which-color-gradient-is-used-to-color-mandelbrot-in-wikipedia
*/
#define MAX_ITER 32
pixel_t iter_to_color_func(uint32_t n)
{
  pixel_t p; // Default black
  if((n < MAX_ITER) & (n > 0)){
    uint4_t index = n; // modulo 16
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


pixel_t mandelbrot_kernel(screen_state_t state, uint16_t x, uint16_t y)
{
  mandelbrot_iter_t iter;

  // Convert pixel coordinate to complex number
  screen_to_complex_in_t stc;
  stc.state = state;
  stc.x = x;
  stc.y = y;
  iter.c = screen_to_complex_func(stc);

  // Do the mandelbrot iters
  iter.z.re = 0.0;
  iter.z.im = 0.0;
  iter.z_squared.re = 0.0;
  iter.z_squared.im = 0.0;
  iter.n = 0;
  iter.escaped = 0;
  while(!iter.escaped & (iter.n < MAX_ITER)){
    mandelbrot_iter_t iter = mandelbrot_iter_func(iter);
  }

  // The color depends on the number of iterations
  pixel_t p = iter_to_color(iter.n);
  return p;
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
  float re_inc = fp_mult(XY_SCALE,state.re_width);
  float im_inc = fp_mult(XY_SCALE,state.im_height);
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
  float incremented_val = fp_add(val_to_inc, inc);
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
    state.re_width = fp_mult(state.re_width, zoom_mult);
    state.im_height = fp_mult(state.im_height, zoom_mult);
  }
  
  return state;
}

screen_state_t get_next_screen_state()
{
  static screen_state_t state_reg;
  static uint1_t power_on_reset = 1;
  // Reset
  if(power_on_reset){
    state_reg = screen_state_t_INIT;
  }
  screen_state_t rv = next_state_func(state_reg);
  power_on_reset = 0;
  return rv;
}