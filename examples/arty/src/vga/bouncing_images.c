// Simple design with some fun images bouncing around and changing colors

#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

// See top level IO wiring + VGA resolution timing logic in
#include "vga_pmod.c"

// Logic for putting an image rectangle on screen
#include "image_rect.h"

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
  pixel_t pixel;
  pixel.r = color.r << 4;
  pixel.g = color.g << 4;
  pixel.b = color.b << 4;
  pmod_register_outputs(vga_signals, pixel);
}
