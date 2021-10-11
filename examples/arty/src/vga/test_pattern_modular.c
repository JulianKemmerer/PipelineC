// Simple design mimicing the VHDL VGA test pattern design from Digilent
// https://github.com/Digilent/Arty-Pmod-VGA/blob/master/src/hdl/top.vhd
// https://digilent.com/reference/learn/programmable-logic/tutorials/arty-pmod-vga-demo/start
// And then organized into vga_timing, moving box logic, pixel test pattern coloring

#include "compiler.h"
#include "uintN_t.h"

// Temp hacky introduce 'and'
// https://github.com/JulianKemmerer/PipelineC/issues/24
#ifdef __PIPELINEC__
#define and &
#else
#define and &&
#endif

// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"

// See top level IO wiring in
#include "vga_pmod.c"

////***640x480@60Hz***//  Requires 25 MHz clock
#define PIXEL_CLK_MHZ 25.0
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480

#define H_FP 16 //H front porch width (pixels)
#define H_PW 96 //H sync pulse width (pixels)
#define H_MAX 800 //H total period (pixels)

#define V_FP 10 //V front porch width (lines)
#define V_PW 2 //V sync pulse width (lines)
#define V_MAX 525 //V total period (lines)

#define H_POL 0
#define V_POL 0

////***800x600@60Hz***//  Requires 40 MHz clock
//#define PIXEL_CLK_MHZ 40.0
//#define FRAME_WIDTH 800
//#define FRAME_HEIGHT 600
//
//#define H_FP 40 //H front porch width (pixels)
//#define H_PW 128 //H sync pulse width (pixels)
//#define H_MAX 1056 //H total period (pixels)
//
//#define V_FP 1 //V front porch width (lines)
//#define V_PW 4 //V sync pulse width (lines)
//#define V_MAX 628 //V total period (lines)
//
//#define H_POL 1
//#define V_POL 1

////***1280x720@60Hz***// Requires 74.25 MHz clock
//#define PIXEL_CLK_MHZ 74.25
//#define FRAME_WIDTH 1280
//#define FRAME_HEIGHT 720
//
//#define H_FP 110 //H front porch width (pixels)
//#define H_PW 40 //H sync pulse width (pixels)
//#define H_MAX 1650 //H total period (pixels)
//
//#define V_FP 5 //V front porch width (lines)
//#define V_PW 5 //V sync pulse width (lines)
//#define V_MAX 750 //V total period (lines)
//
//#define H_POL 1
//#define V_POL 1

////***1280x1024@60Hz***// Requires 108 MHz clock
//#define PIXEL_CLK_MHZ 108.0
//#define FRAME_WIDTH 1280
//#define FRAME_HEIGHT 1024

//#define H_FP 48 //H front porch width (pixels)
//#define H_PW 112 //H sync pulse width (pixels)
//#define H_MAX 1688 //H total period (pixels)

//#define V_FP 1 //V front porch width (lines)
//#define V_PW 3 //V sync pulse width (lines)
//#define V_MAX 1066 //V total period (lines)

//#define H_POL 1
//#define V_POL 1

//***1920x1080@60Hz***// Requires 148.5 MHz pxl_clk
/*
#define PIXEL_CLK_MHZ 148.5
#define FRAME_WIDTH 1920
#define FRAME_HEIGHT 1080

#define H_FP 88 //H front porch width (pixels)
#define H_PW 44 //H sync pulse width (pixels)
#define H_MAX 2200 //H total period (pixels)

#define V_FP 4 //V front porch width (lines)
#define V_PW 5 //V sync pulse width (lines)
#define V_MAX 1125 //V total period (lines)

#define H_POL 1
#define V_POL 1
*/

// VGA timing module
typedef struct vga_pos_t
{
  uint12_t x;
  uint12_t y;
}vga_pos_t;
typedef struct vga_signals_t
{
  vga_pos_t pos;
  uint1_t hsync;
  uint1_t vsync;
  uint1_t active;
}vga_signals_t;
vga_signals_t vga_timing()
{
  uint1_t active;
  
  static uint12_t h_cntr_reg;
  static uint12_t v_cntr_reg;
  
  static uint1_t h_sync_reg = !H_POL;
  static uint1_t v_sync_reg = !V_POL;

  vga_signals_t o;
  o.hsync = h_sync_reg;
  o.vsync = v_sync_reg;
  o.pos.x = h_cntr_reg;
  o.pos.y = v_cntr_reg;
  
  if((h_cntr_reg >= (H_FP + FRAME_WIDTH - 1)) and (h_cntr_reg < (H_FP + FRAME_WIDTH + H_PW - 1)))
  {
    h_sync_reg = H_POL;
  }
  else
  {
    h_sync_reg = !(H_POL);
  }

  if((v_cntr_reg >= (V_FP + FRAME_HEIGHT - 1)) and (v_cntr_reg < (V_FP + FRAME_HEIGHT + V_PW - 1)))
  {
    v_sync_reg = V_POL;
  }
  else
  {
    v_sync_reg = !(V_POL);
  }

  if((h_cntr_reg == (H_MAX - 1)) and (v_cntr_reg == (V_MAX - 1)))
  {
    v_cntr_reg = 0;
  }
  else if(h_cntr_reg == (H_MAX - 1))
  {
    v_cntr_reg = v_cntr_reg + 1;
  }

  if(h_cntr_reg == (H_MAX - 1))
  {
    h_cntr_reg = 0;
  }
  else
  {
    h_cntr_reg = h_cntr_reg + 1;
  }
  
  active = 0;
  if((h_cntr_reg < FRAME_WIDTH) and (v_cntr_reg < FRAME_HEIGHT))
  {
    active = 1;
  }
  o.active = active;
  
  return o;
}

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
