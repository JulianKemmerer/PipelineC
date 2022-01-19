#ifdef __PIPELINEC__
// PiplineC types
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "float_e_m_t.h"
// Access to board buttons
//#include "../buttons/buttons.c"
// Top level IO wiring + VGA resolution timing logic+types
#include "vga_pmod.c"
// Float is built in
#define float_lshift(x,shift) ((x)<<(shift))
// Variable width float stuff
#define float float_8_23_t
#define uint_to_float float_8_23_t_uint32
#define float_to_uint float_8_23_t_31_0
#define RSQRT_MAGIC 0x5f3759df
/*
#define float float_8_14_t
#define uint_to_float float_8_14_t_uint23
#define float_to_uint float_8_14_t_22_0
#define RSQRT_MAGIC 0x2F9BAC
*/

#else // Regular C code (not PipelineC)
// Software FP32
typedef union fp_tlayout { float f; uint32_t i; struct  { uint32_t mantissa; uint32_t exp; uint32_t sign; } ;} fp_tlayout;
uint32_t float_to_uint(float a)
{
  fp_tlayout conv;
  conv.f = a;
  return conv.i;
}
float uint_to_float(uint32_t a)
{
  fp_tlayout conv;
  conv.i = a;
  return conv.f;
}
float float_lshift(float x, int32_t shift)
{
  return shift > 0 ? x * (1 << shift) : x / (1 << -shift);
}
#define RSQRT_MAGIC 0x5f3759df
#endif

// https://en.wikipedia.org/wiki/Fast_inverse_square_root
float fast_rsqrt(float number)
{
  float x2 = float_lshift(number, -1); // number*.5;
  float conv_f = uint_to_float(RSQRT_MAGIC - (float_to_uint(number) >> 1));
  return conv_f*(1.5 - conv_f*conv_f*x2);
}
float fast_sqrt(float number)
{
  return 1.0 / fast_rsqrt(number);
}

// Complex math
typedef struct complex_t
{
  float re;
  float im;
}complex_t;
float complex_mag(complex_t c)
{
  return fast_sqrt((c.re*c.re)+(c.im*c.im));
}
complex_t complex_mult(complex_t cnum1, complex_t cnum2)
{
  complex_t rv = { (cnum1.re * cnum2.re) - (cnum1.im * cnum2.im),
          (cnum1.re * cnum2.im) + (cnum2.re * cnum1.im) };
  return rv;
}
complex_t complex_square(complex_t c)
{
  return complex_mult(c, c);
}
complex_t complex_add(complex_t x, complex_t y)
{
  complex_t rv = {x.re + y.re, x.im + y.im};
  return rv;
}

// Mandelbrot logic copied from
// https://www.codingame.com/playgrounds/2358/how-to-plot-the-mandelbrot-set/mandelbrot-set
#define MAX_ITER 20
uint32_t mandelbrot(complex_t c)
{
  complex_t z = {0.0, 0.0};
  uint32_t n = 0;
  // Mimic while loop with fixed for loop
  uint1_t not_found_n = 1;
  uint32_t i;
  for(i=0;i<MAX_ITER;i+=1)
  {
    // Mimic while loop
    if(not_found_n) 
    {
      if(complex_mag(z) <= 2.0)
      {
        z = complex_add(complex_square(z), c);
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

// Logic for animating state over time
inline state_t next_state_func(uint1_t reset, state_t state)//, user_input_t user_input)
{
  // Next state starts off as keeping current state  
  state_t next_state = state;
  // Read input controls from user
  //user_input_t user_input = get_user_input();
  
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
