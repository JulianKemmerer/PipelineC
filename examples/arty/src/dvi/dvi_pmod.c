#pragma once
// Constants and logic to produce DVI signals at fixed resolution
#include "../vga/vga_timing.h"
#include "../vga/pixel.h" // 24bpp color

#ifdef __PIPELINEC__
#include "wire.h"
#include "uintN_t.h"

// Include PMOD IO (FAKED FOR NOW)
#include "../pmod/pmod_ja.c"
#include "../pmod/pmod_jb.c"
#include "../pmod/pmod_jc.c"

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct dvi_to_app_t
{
  // No inputs from DVI - is output
}app_to_dvi_t;*/
// Outputs
typedef struct app_to_dvi_t
{
  uint1_t hs;
  uint1_t vs;
  pixel_t color;
}app_to_dvi_t;

// Globally visible ports/wires
//dvi_to_app_t dvi_to_app;
app_to_dvi_t app_to_dvi;
//#include "clock_crossing/dvi_to_app.h"
#include "clock_crossing/app_to_dvi.h"

// Top level module connecting to globally visible ports
#pragma MAIN dvi // No associated clock domain yet
void dvi()
{
  app_to_dvi_t dvi;
  WIRE_READ(app_to_dvi_t, dvi, app_to_dvi)
  //WIRE_WRITE(dvi_to_app_t, dvi_to_app, inputs)
  
  // Convert the DVI type to PMOD types
  // FAKED FOR NOW
  app_to_pmod_ja_t a;
  a.ja0 = dvi.color.r >> 0;
  a.ja1 = dvi.color.r >> 1;
  a.ja2 = dvi.color.r >> 2;
  a.ja3 = dvi.color.r >> 3;
  a.ja4 = dvi.color.r >> 4;
  a.ja5 = dvi.color.r >> 5;
  a.ja6 = dvi.color.r >> 6;
  a.ja7 = dvi.color.r >> 7;
  app_to_pmod_jb_t b;
  b.jb0 = dvi.color.g >> 0;
  b.jb1 = dvi.color.g >> 1;
  b.jb2 = dvi.color.g >> 2;
  b.jb3 = dvi.color.g >> 3;
  b.jb4 = dvi.color.g >> 4;
  b.jb5 = dvi.color.g >> 5;
  b.jb6 = dvi.color.g >> 6;
  b.jb7 = dvi.color.g >> 7;
  app_to_pmod_jc_t c;
  c.jc0 = dvi.color.b >> 0;
  c.jc1 = dvi.color.b >> 1;
  c.jc2 = dvi.color.b >> 2;
  c.jc3 = dvi.color.b >> 3;
  c.jc4 = dvi.color.b >> 4;
  c.jc5 = dvi.color.b >> 5;
  c.jc6 = dvi.color.b >> 6;
  c.jc7 = dvi.color.b >> 7;
  // FAKED NO HS VS CONNECTED

  WIRE_WRITE(app_to_pmod_ja_t, app_to_pmod_ja, a)
  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jb, b)
  WIRE_WRITE(app_to_pmod_jc_t, app_to_pmod_jc, c)
}

// Logic for connecting outputs/sim debug wires
// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
// Verilator Debug wires
#include "clock_crossing/dvi_red_DEBUG.h"
DEBUG_OUTPUT_DECL(uint8_t, dvi_red)
#include "clock_crossing/dvi_green_DEBUG.h"
DEBUG_OUTPUT_DECL(uint8_t, dvi_green)
#include "clock_crossing/dvi_blue_DEBUG.h"
DEBUG_OUTPUT_DECL(uint8_t, dvi_blue)
#include "clock_crossing/vsync_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, vsync)
#include "clock_crossing/hsync_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, hsync)
#include "clock_crossing/dvi_active_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, dvi_active)
#include "clock_crossing/dvi_x_DEBUG.h"
DEBUG_OUTPUT_DECL(uint12_t, dvi_x)
#include "clock_crossing/dvi_y_DEBUG.h"
DEBUG_OUTPUT_DECL(uint12_t, dvi_y)

void pmod_register_outputs(vga_signals_t vga, pixel_t color)
{
  // Registers
  static uint8_t dvi_red_reg;
  static uint8_t dvi_green_reg;
  static uint8_t dvi_blue_reg;
  static uint1_t h_sync_dly_reg = !H_POL;
  static uint1_t v_sync_dly_reg = !V_POL;
  static uint1_t active_reg;
  static uint12_t x_reg;
  static uint12_t y_reg;
  
  // Connect to DVI PMOD board IO via app_to_dvi wire
  app_to_dvi_t o;
  o.hs = h_sync_dly_reg;
  o.vs = v_sync_dly_reg;
  o.color.r = dvi_red_reg;
  o.color.g = dvi_green_reg;
  o.color.b = dvi_blue_reg;
  WIRE_WRITE(app_to_dvi_t, app_to_dvi, o)
  
  // Connect to Verilator debug ports
  vsync(o.vs);
  hsync(o.hs);
  dvi_red(o.color.r);
  dvi_green(o.color.g);
  dvi_blue(o.color.b);
  dvi_active(active_reg);
  dvi_x(x_reg);
  dvi_y(y_reg);
  
  // Black color when inactive
  pixel_t active_color;
  if(vga.active)
  {
    active_color = color;
  }
  // Output delay regs
  dvi_red_reg = active_color.r;
  dvi_green_reg = active_color.g;
  dvi_blue_reg = active_color.b;
  active_reg = vga.active;
  v_sync_dly_reg = vga.vsync;
  h_sync_dly_reg = vga.hsync;
  x_reg = vga.pos.x;
  y_reg = vga.pos.y;
}

#endif // ifdef __PIPELINEC__

#ifndef __PIPELINEC__
// Software versions for Verilator + SDL frame buffer

uint64_t t0;
uint64_t frame = 0;
void pmod_register_outputs(vga_signals_t current_timing, pixel_t current_color)
{
  //printf("color at %d,%d=%d (red)\n", current_timing.pos.x, current_timing.pos.y, current_color.r);

  if(current_timing.active)
  {
    fb_setpixel(current_timing.pos.x, current_timing.pos.y,
     current_color.r, current_color.g, current_color.b);

    if(current_timing.pos.x==0 && current_timing.pos.y==0)
    {
      fb_update();
      frame += 1;
    }
  }
  
  if(fb_should_quit())
  {
    float elapsed = float(higres_ticks()-t0)/higres_ticks_freq();
    printf("FPS: %f\n", frame/elapsed);
    exit(1);
  }
}

#ifdef USE_VERILATOR
void verilator_output(Vtop* g_top)
{
  // 8b colors from hardware
  uint8_t r = g_top->dvi_red;
  uint8_t g = g_top->dvi_green;
  uint8_t b = g_top->dvi_blue;
  uint1_t active = g_top->dvi_active;
  uint12_t x = g_top->dvi_x;
  uint12_t y = g_top->dvi_y;
  if(active)
  {
    fb_setpixel(x, y, r, g, b);
    if((x==0) && (y==0))
    {
      fb_update();
      frame += 1;
    }
  }
  
  if(fb_should_quit())
  {
    float elapsed = float(higres_ticks()-t0)/higres_ticks_freq();
    printf("FPS: %f\n", frame/elapsed);
    exit(1);
  }
}
#endif
#endif
