#pragma once
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

// Constants and logic to produce VGA signals at fixed resolution
#include "vga_timing.h"

typedef struct color_12b_t
{
  uint4_t red;
  uint4_t green;
  uint4_t blue;
}color_12b_t;
// TODO make above use these types^?

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
void vga_pmod_register_outputs(vga_signals_t vga, color_12b_t color)
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
