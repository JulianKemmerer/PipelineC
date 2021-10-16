// Simple design with some fun images bouncing around and changing colors

#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

// Temp hacky introduce 'and'
// https://github.com/JulianKemmerer/PipelineC/issues/24
#ifdef __PIPELINEC__
#define and &
#else
#define and &&
#endif

// See top level IO wiring in
#include "vga_pmod.c"

// Constants and logic to produce VGA signals at fixed resolution
#include "vga_timing.h"

// Logic for putting an image rectangle on screen
#include "image_rect.h"

// Logic for connecting outputs/sim debug wires
// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
#ifndef SKIP_DEBUG_OUTPUT
// Verilator Debug wires
#include "clock_crossing/vga_red_DEBUG.h"
DEBUG_OUTPUT_DECL(uint4_t, vga_red)
#include "clock_crossing/vga_green_DEBUG.h"
DEBUG_OUTPUT_DECL(uint4_t, vga_green)
#include "clock_crossing/vga_blue_DEBUG.h"
DEBUG_OUTPUT_DECL(uint4_t, vga_blue)
#include "clock_crossing/vsync_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, vsync)
#include "clock_crossing/hsync_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, hsync)
#endif
void register_outputs(vga_signals_t vga, color_12b_t color)
{
  // Registers
  static uint4_t vga_red_reg;
  static uint4_t vga_green_reg;
  static uint4_t vga_blue_reg;
  static uint1_t h_sync_dly_reg = !H_POL;
  static uint1_t v_sync_dly_reg = !V_POL;
  
  // Connect to VGA PMOD board IO via app_to_vga wire
  app_to_vga_t o;
  o.hs = h_sync_dly_reg;
  o.vs = v_sync_dly_reg;
  o.r = vga_red_reg;
  o.g = vga_green_reg;
  o.b = vga_blue_reg;
  WIRE_WRITE(app_to_vga_t, app_to_vga, o)
  
  // Connect to simulation debug
#ifndef SKIP_DEBUG_OUTPUT
  // Connect to Verilator debug ports
  vsync(o.vs);
  hsync(o.hs);
  vga_red(o.r);
  vga_green(o.g);
  vga_blue(o.b);
#else
  debug_vsync = o.vs;
  debug_hsync = o.hs;
  debug_vga_red = o.r;
  debug_vga_green = o.g;
  debug_vga_blue = o.b;
#endif
  
  // Output delay regs
  v_sync_dly_reg = vga.vsync;
  h_sync_dly_reg = vga.hsync;
  vga_red_reg = color.red;
  vga_green_reg = color.green;
  vga_blue_reg = color.blue;
}

// Logic for coloring pixels
#define NUM_IMAGES NUM_COLOR_MODES // One image per color mode
color_12b_t get_pixel_color(uint1_t active, vga_pos_t pos, rect_t rects[NUM_IMAGES])
{
  // Default zeros/black background
  color_12b_t c;
  
  // Except for where rectanges are
  // Which rectangle is on top?
  // rectangle, 0 on top of 1, on top of 2, etc
  rect_t rect;
  vga_pos_t rel_pos;
  uint1_t rel_pos_valid;
  int32_t i;
  for(i=(NUM_IMAGES-1);i>=0;i-=1)
  {
    if(rect_contains(rects[i], pos))
    {
      rect = rects[i];
      rel_pos = rect_rel_pos(rect, pos);
      rel_pos_valid = 1;
    }
  }
  // What color for the rel pos inside the top rect?
  if(rel_pos_valid)
  {
    c = rect_color(rel_pos, rect.color_mode);
  }
  
  return c;
}

// The test pattern driving entity
// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // N image rectangles all moving in parallel
  // Initial state values
  rect_t start_states[NUM_IMAGES];
  RECT_INIT(start_states) // Constants macro
  
  // Rectangle moving animation func/module outputs current state
  rect_t rects[NUM_IMAGES];
  uint32_t i;
  for(i=0;i<NUM_IMAGES;i+=1)
  {
    // Logic to make a rectangle move
    rects[i] = rect_move(start_states[i]);
  }
  
  // Color pixel at x,y
  color_12b_t color = get_pixel_color(vga_signals.active, vga_signals.pos, rects);
  
  // Drive output signals/registers
  register_outputs(vga_signals, color);
}
