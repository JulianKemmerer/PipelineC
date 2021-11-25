#pragma once
// Constants and logic to produce VGA signals at fixed resolution
#include "vga_timing.h"
#include "color_12b.h"

#ifdef __PIPELINEC__
#include "wire.h"
#include "uintN_t.h"

// Setup for pins like Digilent demo using PMODs B+C
// https://digilent.com/reference/learn/programmable-logic/tutorials/arty-pmod-vga-demo/start
#include "../pmod/pmod_jb.c"
#include "../pmod/pmod_jc.c"

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct vga_to_app_t
{
  // No inputs from VGA - is output
}app_to_vga_t;*/
// Outputs
typedef struct app_to_vga_t
{
  uint1_t hs;
  uint1_t vs;
  uint4_t r;
  uint4_t g;
  uint4_t b;
}app_to_vga_t;

// Globally visible ports/wires
//vga_to_app_t vga_to_app;
app_to_vga_t app_to_vga;
//#include "clock_crossing/vga_to_app.h"
#include "clock_crossing/app_to_vga.h"

// Top level module connecting to globally visible ports
#pragma MAIN vga // No associated clock domain yet
void vga()
{
  app_to_vga_t vga;
  WIRE_READ(app_to_vga_t, vga, app_to_vga)
  //WIRE_WRITE(vga_to_app_t, vga_to_app, inputs)
  
  // Convert the VGA type to PMOD types
  // i.e. wire VGA to PMOD pins
  // https://github.com/Digilent/Arty-Pmod-VGA/blob/8341f622a13324fc59ab69d595b16e32a9519029/src/constraints/Arty_Master.xdc#L58
  app_to_pmod_jb_t b;
  b.jb0 = vga.r >> 0;
  b.jb1 = vga.r >> 1;
  b.jb2 = vga.r >> 2;
  b.jb3 = vga.r >> 3;
  b.jb4 = vga.b >> 0;
  b.jb5 = vga.b >> 1;
  b.jb6 = vga.b >> 2;
  b.jb7 = vga.b >> 3;
  app_to_pmod_jc_t c;
  c.jc0 = vga.g >> 0;
  c.jc1 = vga.g >> 1;
  c.jc2 = vga.g >> 2;
  c.jc3 = vga.g >> 3;
  c.jc4 = vga.hs;
  c.jc5 = vga.vs;

  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jb, b)
  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jc, c)
}
// TODO make above use vga color types?

// Logic for connecting outputs/sim debug wires
// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
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
#include "clock_crossing/vga_active_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, vga_active)
#include "clock_crossing/vga_x_DEBUG.h"
DEBUG_OUTPUT_DECL(uint12_t, vga_x)
#include "clock_crossing/vga_y_DEBUG.h"
DEBUG_OUTPUT_DECL(uint12_t, vga_y)

void vga_pmod_register_outputs(vga_signals_t vga, color_12b_t color)
{
  // Registers
  static uint4_t vga_red_reg;
  static uint4_t vga_green_reg;
  static uint4_t vga_blue_reg;
  static uint1_t h_sync_dly_reg = !H_POL;
  static uint1_t v_sync_dly_reg = !V_POL;
  static uint1_t active_reg;
  static uint12_t x_reg;
  static uint12_t y_reg;
  
  // Connect to VGA PMOD board IO via app_to_vga wire
  app_to_vga_t o;
  o.hs = h_sync_dly_reg;
  o.vs = v_sync_dly_reg;
  o.r = vga_red_reg;
  o.g = vga_green_reg;
  o.b = vga_blue_reg;
  WIRE_WRITE(app_to_vga_t, app_to_vga, o)
  
  // Connect to Verilator debug ports
  vsync(o.vs);
  hsync(o.hs);
  vga_red(o.r);
  vga_green(o.g);
  vga_blue(o.b);
  vga_active(active_reg);
  vga_x(x_reg);
  vga_y(y_reg);
  
  // Black color when inactive
  color_12b_t active_color;
  if(vga.active)
  {
    active_color = color;
  }
  // Output delay regs
  vga_red_reg = active_color.red;
  vga_green_reg = active_color.green;
  vga_blue_reg = active_color.blue;
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
void vga_pmod_register_outputs(vga_signals_t current_timing, color_12b_t current_color)
{
  if(current_timing.active)
  {
    /*if(current_timing.pos.x==0 && current_timing.pos.y==0 && current_color.blue>0) 
      printf("frame %lu color at %d,%d=%d (blue)\n", frame, current_timing.pos.x, current_timing.pos.y, current_color.blue);*/
    
    fb_setpixel(current_timing.pos.x, current_timing.pos.y,
     current_color.red << 4, current_color.green << 4, current_color.blue << 4);
    if(current_timing.pos.x==0 && current_timing.pos.y==0)
    {
      fb_update();
      frame += 1;
      if(fb_should_quit())
      {
        float elapsed = float(higres_ticks()-t0)/higres_ticks_freq();
        printf("FPS: %f\n", frame/elapsed);
        exit(1);
      }
    }
  }
}

#ifdef USE_VERILATOR
void verilator_vga_output(Vtop* g_top)
{
  uint8_t r = g_top->vga_red;
  uint8_t g = g_top->vga_green;
  uint8_t b = g_top->vga_blue;
  uint1_t active = g_top->vga_active;
  uint12_t x = g_top->vga_x;
  uint12_t y = g_top->vga_y;
  if(active)
  {
    /*if((x==0) && (y==0) && (b>0))
      printf("frame %lu color at %d,%d=%d (blue)\n", frame, x, y, b);*/
    
    fb_setpixel(x, y, r << 4, g << 4, b << 4);
    if((x==0) && (y==0))
    {
      fb_update();
      frame += 1;
      if(fb_should_quit())
      {
        exit(1);
      }
      float elapsed = float(higres_ticks()-t0)/higres_ticks_freq();
      printf("frame %lu FPS: %f\n", frame, frame/elapsed);
    }
  }
}
#endif
#endif
