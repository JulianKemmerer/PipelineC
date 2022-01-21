#ifdef __PIPELINEC__
// PiplineC types
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
// Access to board buttons
#include "../buttons/buttons.c"
#include "../switches/switches.c"
// Top level IO wiring + VGA resolution timing logic+types
#include "vga_pmod.c"
// Float shift is built in
#define float_lshift(x,shift) ((x)<<(shift))
// Variable width float stuff
//#define float float_8_23_t
// Looks good
//#define float float_8_14_t
// Fine?
#define float float_8_10_t
// Chonky?
//#define float float_8_9_t
// Pretty bad (dsps not used lots of luts too)
//#define float float_8_8_t

#else // Regular C code (not PipelineC)
float float_lshift(float x, int32_t shift)
{
  return shift > 0 ? x * (1 << shift) : x / (1 << -shift);
}
#endif

// Mandelbrot logic copied from
// https://en.wikipedia.org/wiki/Plotting_algorithms_for_the_Mandelbrot_set#Optimized_escape_time_algorithms
typedef struct complex_t
{
  float re;
  float im;
}complex_t;
#define MAX_ITER 20
#define ESCAPE 2.0
// Optimized
uint32_t mandelbrot(complex_t c)
{
  complex_t z = {0.0, 0.0};
  complex_t z_squared = {0.0, 0.0};
  uint32_t n = 0;
  // Mimic while loop with fixed for loop
  uint1_t not_found_n = 1;
  uint32_t i;
  for(i=0;i<MAX_ITER;i+=1)
  {
    // Mimic while loop
    if(not_found_n) 
    {
      if((z_squared.re+z_squared.im) <= (ESCAPE*ESCAPE))
      {
        z.im = float_lshift((z.re*z.im), 1) + c.im;
        z.re = z_squared.re - z_squared.im + c.re;
        z_squared.re = z.re * z.re;
        z_squared.im = z.im * z.im;
        n += 1;
      }
      else
      {
        not_found_n = 0;
      }
    }
  }
  return n;
}

// State to keep
typedef struct state_t
{
  // Plot window
  float RE_START;
  float RE_END;
  float IM_START;
  float IM_END;
}state_t;

// State to return to at reset
inline state_t reset_values()
{
  state_t state;
  state.RE_START = -2.0;
  state.RE_END = 1.0;
  state.IM_START = -1.0;
  state.IM_END = 1.0;
  return state;
}

// Logic for coloring pixel given state
inline pixel_t render_pixel(vga_pos_t pos, state_t state)
{
  // Default zeros/black background
  pixel_t p;
  p.a = 0;
  p.r = 0;
  p.g = 0;
  p.b = 0;
  
  // Convert pixel coordinate to complex number
  complex_t c = {state.RE_START + ((float)pos.x * (1.0f/(float)FRAME_WIDTH)) * (state.RE_END - state.RE_START),
              state.IM_START + ((float)pos.y * (1.0f/(float)FRAME_HEIGHT)) * (state.IM_END - state.IM_START)};
  // Compute the number of iterations
  uint32_t m = mandelbrot(c);
  // The color depends on the number of iterations
  uint8_t color = 255 - (int32_t)(((float)m *(1.0/(float)MAX_ITER))*255.0);
  
  p.r = color;
  p.g = color;
  p.b = color;

  return p;
}

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
  // Read buttons wire/board IO port
  uint4_t btns;
  WIRE_READ(uint4_t, btns, buttons)
  uint4_t sws;
  WIRE_READ(uint4_t, sws, switches)
  // Select which buttons and switches do what?
  i.up = btns >> 0;
  i.down = btns >> 1;
  i.left = btns >> 2;
  i.right = btns >> 3;
  i.zoom_in = sws >> 0;
  i.zoom_out = sws >> 1;
  #else
  // TODO user IO for running as C code
  i.up = 1;
  i.down = 0;
  i.left = 1;
  i.right = 0;
  i.zoom_in = 1;
  i.zoom_out = 0;
  #endif
  return i;
}

// Logic for animating state each frame
inline state_t next_state_func(uint1_t reset, state_t state)//, user_input_t user_input)
{
  // Next state starts off as keeping current state  
  state_t next_state = state;
  // Read input controls from user
  user_input_t i = get_user_input();
  
  float XY_SCALE = 0.001; // X-Y movement
  float Z_SCALE = 0.001; // Zoom movement
  
  // Move window right left (flipped)
  float re_dist = (state.RE_END - state.RE_START);
  float re_inc = (XY_SCALE*re_dist);
  // Negate to use single adder instead of add+sub
  if(i.right)
  {
    re_inc = -re_inc;
  }
  if(i.left|i.right)
  {
    next_state.RE_START += re_inc;
    next_state.RE_END += re_inc;
  }
  
  // Move window up down
  float im_dist = (state.IM_END - state.IM_START);
  float im_inc = (XY_SCALE*im_dist);
  // Negate to use single adder instead of add+sub
  if(i.down)
  {
    im_inc = -im_inc;
  }
  if(i.up|i.down)
  {
    next_state.IM_START += im_inc;
    next_state.IM_END += im_inc;
  }
  
  // Move window in and out
  float zoom_mult;
  if(i.zoom_in)
  {
    zoom_mult = (1.0-Z_SCALE);
  }
  else
  {
    zoom_mult = Z_SCALE;
  }
  if(i.zoom_in|i.zoom_out)
  {
    next_state.RE_START *= zoom_mult;
    next_state.RE_END *= zoom_mult;
    next_state.IM_START *= zoom_mult;
    next_state.IM_END *= zoom_mult;
  }
  
  return next_state;
}

// Helper func with isolated local static var to hold state
// while do_state_update local volatile static state is updating.
state_t curr_state_buffer(state_t updated_state, uint1_t update_valid)
{
  // State reg
  static state_t state;
  state_t rv = state;
  // Updated occassionally
  if(update_valid)
  {
    state = updated_state;
  }
  return rv;
}

// Logic to update the state in a multiple cycle volatile feedback pipeline
inline state_t do_state_update(uint1_t reset, uint1_t end_of_frame)
{
  // Volatile state registers
  #ifdef __PIPELINEC__ // Not same as software volatile
  volatile 
  #endif
  static state_t state;
  
  // Use 'slow' end of frame pulse as 'now' valid flag occuring 
  // every N cycles > pipeline depth/latency
  uint1_t update_now = end_of_frame | reset;

  // Update state
  if(reset)
  {
    // Reset condition?
    state = reset_values();
  }
  else if(end_of_frame)
  {
    // Normal next state update
    state = next_state_func(reset, state);//, user_input);
  }  
  
  // Buffer/save state as it periodically is updated/output from above
  state_t curr_state = curr_state_buffer(state, update_now);
  
  // Overwrite potententially invalid volatile 'state' circulating in feedback
  // replacing it with always valid buffered curr state. 
  // This way state will be known good when the next frame occurs
  state = curr_state;
         
  return curr_state;
}

// Logic to start in reset and exit reset after first frame
uint1_t reset_ctrl(uint1_t end_of_frame)
{
  // Reset register
  static uint1_t reset = 1; // Start in reset
  uint1_t rv = reset;
  if(end_of_frame)
  {
    reset = 0; // Out of reset after first frame
  }
  return rv;
}

// Set design main top level to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Per clock logic:
  
  // Get reset state/status
  uint1_t reset = reset_ctrl(vga_signals.end_of_frame);
  
  // Do state updating cycle (part of volatile multi cycle pipeline w/ state)
  state_t curr_state = do_state_update(reset, vga_signals.end_of_frame);

  // Render the pixel at x,y pos given buffered state
  pixel_t color = render_pixel(vga_signals.pos, curr_state);
  
  // Drive output signals/registers
  pmod_register_outputs(vga_signals, color);
}
