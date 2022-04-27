#pragma once
// For external, ex. Litex, video consumers 
// Mimic vga_pmod and dvi_pmod but just send video signals to top level outputs
#include "vga_timing.h"
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color

#ifdef __PIPELINEC__
#include "wire.h"
#include "uintN_t.h"

// External vga output global wire
typedef struct external_vga_output_t
{
  vga_signals_t vga_timing;
  pixel_t color;
}external_vga_output_t;
external_vga_output_t external_vga_output;
#include "clock_crossing/external_vga_output.h"

// External vga output global wire connected to top level outputs
#pragma MAIN vga // No associated clock domain yet
external_vga_output_t vga()
{
  external_vga_output_t o;
  WIRE_READ(external_vga_output_t, o, external_vga_output)

  // Drive external vga timing feedback if needed
  #ifdef EXT_VGA_TIMING
  WIRE_WRITE(vga_signals_t, external_vga_timing_feedback, o.vga_timing)
  #endif // ifdef EXT_VGA_TIMING

  return o;
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

// TODO rename pmod_register_outputs everywhere to be register_video_outputs

void pmod_register_outputs(vga_signals_t vga, pixel_t color)
{
  // Registers
  static uint8_t dvi_red_reg;
  static uint8_t dvi_green_reg;
  static uint8_t dvi_blue_reg;
  static vga_signals_t vga_reg;
  
  // Connect regs to to external vga output
  external_vga_output_t o;
  o.vga_timing = vga_reg;
  o.color.r = dvi_red_reg;
  o.color.g = dvi_green_reg;
  o.color.b = dvi_blue_reg;
  WIRE_WRITE(external_vga_output_t, external_vga_output, o)

  // Connect to Verilator debug ports
  vsync(o.vga_timing.vsync);
  hsync(o.vga_timing.hsync);
  dvi_red(o.color.r);
  dvi_green(o.color.g);
  dvi_blue(o.color.b);
  dvi_active(o.vga_timing.active);
  dvi_x(o.vga_timing.pos.x);
  dvi_y(o.vga_timing.pos.y);
  
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
  vga_reg = vga;
}

#endif // ifdef __PIPELINEC__