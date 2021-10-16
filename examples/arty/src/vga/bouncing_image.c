// Simple design with fun image bouncing around

#include "compiler.h"
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

typedef struct color_12b_t
{
  uint4_t red;
  uint4_t green;
  uint4_t blue;
}color_12b_t;

// Image rectangle to use
#include "pipelinec_color.h" // See make_image_files.py
// Logic for coloring the rect given rel pos inside rect
color_12b_t get_rect_color(vga_pos_t rel_pos)
{
  // Func from from pipelinec_color.h
  uint32_t pixel_num = pipelinec_color_pixel_num(rel_pos);

  // In pipelineable luts, too slow for pycparser (and probabaly rest of PipelineC too)
  //color_12b_t pipelinec_color[pipelinec_color_W*pipelinec_color_H];
  // return pipelinec_color[pixel_num]; 
  
  // As synthesis tool inferred RAM
  pipelinec_color_DECL // Macro from pipelinec_color.h
  color_12b_t unused_write_data;
  // RAM template function
  return pipelinec_color_RAM_SP_RF_0(pixel_num, unused_write_data, 0);
}

// Moving rectangle module
// Rect should be small enough
// to bounce a little on smallest 640x480 screens
#define RECT_W pipelinec_color_W
#define RECT_H pipelinec_color_H
#define RECT_X_MAX (FRAME_WIDTH - RECT_W)
#define RECT_Y_MAX (FRAME_HEIGHT - RECT_H)
#define RECT_X_MIN 0
#define RECT_Y_MIN 0
#define RECT_X_INIT 0
#define RECT_Y_INIT ((FRAME_HEIGHT/2)-(RECT_H/2))
#define RECT_CLK_DIV 1000000 //MAX=(2^25 - 1)
vga_pos_t moving_rect_logic()
{  
  static uint12_t rect_x_reg = RECT_X_INIT;
  static uint1_t rect_x_dir = 1;
  static uint12_t rect_y_reg = RECT_Y_INIT;
  static uint1_t rect_y_dir = 1;
  static uint25_t rect_cntr_reg;
  
  vga_pos_t rect_pos;
  rect_pos.x = rect_x_reg;
  rect_pos.y = rect_y_reg;
  
  uint1_t update_rect;
  update_rect = 0;
  if(rect_cntr_reg == (RECT_CLK_DIV - 1))
  {
    update_rect = 1;
  }
 
  // Save rect x,y for comparing during direction logic
  uint12_t rect_x_tmp;
  uint12_t rect_y_tmp;
  rect_x_tmp = rect_x_reg;
  rect_y_tmp = rect_y_reg;
  
  if(update_rect == 1)
  {
    if(rect_x_dir == 1)
    {
      rect_x_reg = rect_x_reg + 1;
    }
    else
    {
      rect_x_reg = rect_x_reg - 1;
    }
    if(rect_y_dir == 1)
    {
      rect_y_reg = rect_y_reg + 1;
    }
    else
    {
      rect_y_reg = rect_y_reg - 1;
    }
  }      
                  
  if(update_rect == 1)
  {
    if((rect_x_dir == 1 and (rect_x_tmp == RECT_X_MAX - 1)) | (rect_x_dir == 0 and (rect_x_tmp == RECT_X_MIN + 1)))
    {
      rect_x_dir = !(rect_x_dir);
    }
    if((rect_y_dir == 1 and (rect_y_tmp == RECT_Y_MAX - 1)) | (rect_y_dir == 0 and (rect_y_tmp == RECT_Y_MIN + 1))) 
    {
      rect_y_dir = !(rect_y_dir);
    }
  }

  if(rect_cntr_reg == (RECT_CLK_DIV - 1))
  {
    rect_cntr_reg = 0;
  }
  else
  {
    rect_cntr_reg = rect_cntr_reg + 1;     
  }
  
  return rect_pos;
}

// Logic for coloring pixels
color_12b_t get_pixel_color(uint1_t active, vga_pos_t pos, vga_pos_t rect_pos)
{
  // Default zeros/black background
  color_12b_t c;
  
  // Except for where rectange is
  if(((pos.x >= rect_pos.x) and (pos.x < (rect_pos.x + RECT_W))) and
     ((pos.y >= rect_pos.y) and (pos.y < (rect_pos.y + RECT_H))))
  {
    // Where in rectangle?
    vga_pos_t rect_rel_pos;
    rect_rel_pos.x = pos.x - rect_pos.x;
    rect_rel_pos.y = pos.y - rect_pos.y;
    c = get_rect_color(rect_rel_pos);
  }
  
  return c;
}

// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
// Logic for connecting outputs/sim debug wires
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

// The test pattern driving entity
// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Logic to make a rectangle move
  vga_pos_t rect_pos = moving_rect_logic();
  
  // Color pixel at x,y 
  color_12b_t color = get_pixel_color(vga_signals.active, vga_signals.pos, rect_pos);
  
  // Drive output signals/registers
  register_outputs(vga_signals, color);
}
