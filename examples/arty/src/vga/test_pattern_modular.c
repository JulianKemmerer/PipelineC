// Organized and modular version of test_pattern.c
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

// Moving box module
#define BOX_WIDTH 8
#define BOX_CLK_DIV 1000000 //MAX=(2^25 - 1)
#define BOX_X_MAX (512 - BOX_WIDTH)
#define BOX_Y_MAX (FRAME_HEIGHT - BOX_WIDTH)
#define BOX_X_MIN 0
#define BOX_Y_MIN 256
#define BOX_X_INIT 0
#define BOX_Y_INIT 400
vga_pos_t moving_box_logic()
{  
  static uint12_t box_x_reg = BOX_X_INIT;
  static uint1_t box_x_dir = 1;
  static uint12_t box_y_reg = BOX_Y_INIT;
  static uint1_t box_y_dir = 1;
  static uint25_t box_cntr_reg;
  
  vga_pos_t box_pos;
  box_pos.x = box_x_reg;
  box_pos.y = box_y_reg;
  
  uint1_t update_box;
  update_box = 0;
  if(box_cntr_reg == (BOX_CLK_DIV - 1))
  {
    update_box = 1;
  }
 
  // Save box x,y for comparing during direction logic
  uint12_t box_x_tmp;
  uint12_t box_y_tmp;
  box_x_tmp = box_x_reg;
  box_y_tmp = box_y_reg;
  
  if(update_box == 1)
  {
    if(box_x_dir == 1)
    {
      box_x_reg = box_x_reg + 1;
    }
    else
    {
      box_x_reg = box_x_reg - 1;
    }
    if(box_y_dir == 1)
    {
      box_y_reg = box_y_reg + 1;
    }
    else
    {
      box_y_reg = box_y_reg - 1;
    }
  }      
                  
  if(update_box == 1)
  {
    if((box_x_dir == 1 and (box_x_tmp == BOX_X_MAX - 1)) | (box_x_dir == 0 and (box_x_tmp == BOX_X_MIN + 1)))
    {
      box_x_dir = !(box_x_dir);
    }
    if((box_y_dir == 1 and (box_y_tmp == BOX_Y_MAX - 1)) | (box_y_dir == 0 and (box_y_tmp == BOX_Y_MIN + 1))) 
    {
      box_y_dir = !(box_y_dir);
    }
  }

  if(box_cntr_reg == (BOX_CLK_DIV - 1))
  {
    box_cntr_reg = 0;
  }
  else
  {
    box_cntr_reg = box_cntr_reg + 1;     
  }
  
  return box_pos;
}

// Logic for coloring pixels
typedef struct color_12b_t
{
  uint4_t red;
  uint4_t green;
  uint4_t blue;
}color_12b_t;
color_12b_t get_pixel_color(uint1_t active, vga_pos_t pos, vga_pos_t box_pos)
{
  uint4_t vga_red;
  uint4_t vga_green;
  uint4_t vga_blue;
  
  uint1_t pixel_in_box;
  pixel_in_box = 0;
  if(((pos.x >= box_pos.x) and (pos.x < (box_pos.x + BOX_WIDTH))) and
     ((pos.y >= box_pos.y) and (pos.y < (box_pos.y + BOX_WIDTH))))
  {
    pixel_in_box = 1;
  }  
  
  vga_red = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and uint12_8_8(pos.x) == 1))
  {
    vga_red = uint12_5_2(pos.x);
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1)))
  {
    vga_red = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1))))
  {
    vga_red = 0b1111;
  }
     
  vga_blue = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and  uint12_6_6(pos.x) == 1))
  {
    vga_blue = uint12_5_2(pos.x); 
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1)))
  {
    vga_blue = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1))))
  {
    vga_blue = 0b1111;
  }                      
                         
  vga_green = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and uint12_7_7(pos.x) == 1))
  {
    vga_green = uint12_5_2(pos.x); 
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1))) 
  {
    vga_green = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1)))) 
  {
    vga_green = 0b1111;
  }
  
  color_12b_t c;
  c.red = vga_red;
  c.green = vga_green;
  c.blue = vga_blue;
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
  
  // Logic to make a box move
  vga_pos_t box_pos = moving_box_logic();
  
  // Color pixel at x,y 
  color_12b_t color = get_pixel_color(vga_signals.active, vga_signals.pos, box_pos);
  
  // Drive output signals/registers
  register_outputs(vga_signals, color);
}
