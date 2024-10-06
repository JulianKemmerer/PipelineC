#pragma once
// Constants and logic to produce VGA signals at fixed resolution
#include "vga_timing.h"
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color
typedef struct color_12b_t
{
  uint4_t r;
  uint4_t g;
  uint4_t b;
}color_12b_t; // 12bpp color

#ifdef __PIPELINEC__
#include "wire.h"
#include "uintN_t.h"

// Setup for pins like Digilent demo using PMODs B+C
// https://digilent.com/reference/learn/programmable-logic/tutorials/arty-pmod-vga-demo/start
#include "../examples/arty/src/pmod/pmod_jb.c"
#include "../examples/arty/src/pmod/pmod_jc.c"

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
  color_12b_t color;
}app_to_vga_t;

// Globally visible ports/wires
//vga_to_app_t vga_to_app;
app_to_vga_t app_to_vga;
//#include "clock_crossing/vga_to_app.h"
#include "clock_crossing/app_to_vga.h"

// Top level module connecting to globally visible ports
#pragma MAIN vga // No associated clock domain yet
#pragma FUNC_WIRES vga
void vga()
{
  app_to_vga_t vga;
  WIRE_READ(app_to_vga_t, vga, app_to_vga)
  //WIRE_WRITE(vga_to_app_t, vga_to_app, inputs)
  
  // Convert the VGA type to PMOD types
  // i.e. wire VGA to PMOD pins
  // https://github.com/Digilent/Arty-Pmod-VGA/blob/8341f622a13324fc59ab69d595b16e32a9519029/src/constraints/Arty_Master.xdc#L58
  app_to_pmod_jb_t b;
  b.jb0 = vga.color.r >> 0;
  b.jb1 = vga.color.r >> 1;
  b.jb2 = vga.color.r >> 2;
  b.jb3 = vga.color.r >> 3;
  b.jb4 = vga.color.b >> 0;
  b.jb5 = vga.color.b >> 1;
  b.jb6 = vga.color.b >> 2;
  b.jb7 = vga.color.b >> 3;
  app_to_pmod_jc_t c;
  c.jc0 = vga.color.g >> 0;
  c.jc1 = vga.color.g >> 1;
  c.jc2 = vga.color.g >> 2;
  c.jc3 = vga.color.g >> 3;
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
DEBUG_OUTPUT_DECL(uint4_t, vga_red)
DEBUG_OUTPUT_DECL(uint4_t, vga_green)
DEBUG_OUTPUT_DECL(uint4_t, vga_blue)
DEBUG_OUTPUT_DECL(uint1_t, vsync)
DEBUG_OUTPUT_DECL(uint1_t, hsync)
DEBUG_OUTPUT_DECL(uint1_t, vga_active)
DEBUG_OUTPUT_DECL(uint12_t, vga_x)
DEBUG_OUTPUT_DECL(uint12_t, vga_y)
DEBUG_OUTPUT_DECL(uint8_t, vga_overclock_counter)
DEBUG_OUTPUT_DECL(uint1_t, vga_valid)

void pmod_register_outputs(vga_signals_t vga, pixel_t color)
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
  static uint8_t overclock_counter_reg;
  static uint1_t valid_reg;
  
  // Connect to VGA PMOD board IO via app_to_vga wire
  app_to_vga_t o;
  o.hs = h_sync_dly_reg;
  o.vs = v_sync_dly_reg;
  o.color.r = vga_red_reg;
  o.color.g = vga_green_reg;
  o.color.b = vga_blue_reg;
  WIRE_WRITE(app_to_vga_t, app_to_vga, o)
  
  // Connect to Verilator debug ports
  vsync = o.vs;
  hsync = o.hs;
  vga_red = o.color.r;
  vga_green = o.color.g;
  vga_blue = o.color.b;
  vga_active = active_reg;
  vga_x = x_reg;
  vga_y = y_reg;
  vga_overclock_counter = overclock_counter_reg;
  vga_valid = valid_reg;
  
  // Black color when inactive
  color_12b_t active_color;
  if(vga.active)
  {
    // Convert 8b colors ot 4b
    active_color.r = color.r >> 4;
    active_color.g = color.g >> 4;
    active_color.b = color.b >> 4;
  }
  // Output delay regs written when valid
  if(vga.valid){
    vga_red_reg = active_color.r;
    vga_green_reg = active_color.g;
    vga_blue_reg = active_color.b;
    active_reg = vga.active;
    v_sync_dly_reg = vga.vsync;
    h_sync_dly_reg = vga.hsync;
    x_reg = vga.pos.x;
    y_reg = vga.pos.y;
  }
  overclock_counter_reg = vga.overclock_counter;
  valid_reg = vga.valid;
}

#endif // ifdef __PIPELINEC__

#ifndef __PIPELINEC__
// Software versions for Verilator + SDL frame buffer

uint64_t t0;
uint64_t frame = 0;
void pmod_register_outputs(vga_signals_t current_timing, pixel_t current_color)
{
  //printf("color at %d,%d=%d (red)\n", current_timing.pos.x, current_timing.pos.y, current_color.r);

  if(current_timing.active & current_timing.valid)
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
  // 4b colors from hardware
  uint8_t r = g_top->vga_red;
  uint8_t g = g_top->vga_green ;
  uint8_t b = g_top->vga_blue ;
  uint1_t active = g_top->vga_active;
  uint12_t x = g_top->vga_x;
  uint12_t y = g_top->vga_y;
  uint1_t valid = g_top->vga_valid;
  if(active & valid)
  {
    // Shift 4b to 8b colors
    fb_setpixel(x, y, r << 4, g << 4, b<< 4);
    if((x==0) ) // Per line && (y==0)
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
