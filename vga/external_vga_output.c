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

// Logic for connecting outputs/sim debug wires
// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
// Output top level ports
DEBUG_OUTPUT_DECL(uint8_t, dvi_red)
DEBUG_OUTPUT_DECL(uint8_t, dvi_green)
DEBUG_OUTPUT_DECL(uint8_t, dvi_blue)
DEBUG_OUTPUT_DECL(uint1_t, vsync)
DEBUG_OUTPUT_DECL(uint1_t, hsync)
DEBUG_OUTPUT_DECL(uint1_t, dvi_active)
DEBUG_OUTPUT_DECL(uint12_t, dvi_x)
DEBUG_OUTPUT_DECL(uint12_t, dvi_y)
DEBUG_OUTPUT_DECL(uint8_t, dvi_overclock_counter)
DEBUG_OUTPUT_DECL(uint1_t, dvi_valid)

// TODO rename pmod_register_outputs everywhere to be register_video_outputs

void pmod_register_outputs(vga_signals_t vga, pixel_t color)
{
  // Registers
  static uint8_t dvi_red_reg;
  static uint8_t dvi_green_reg;
  static uint8_t dvi_blue_reg;
  static vga_signals_t vga_reg;
  
  // Drive external vga timing feedback if needed
  #ifdef EXT_VGA_TIMING
  WIRE_WRITE(vga_signals_t, external_vga_timing_feedback, vga_reg)
  #endif // ifdef EXT_VGA_TIMING
  
  // Connect to external outputs
  vsync = vga_reg.vsync;
  hsync = vga_reg.hsync;
  dvi_red = dvi_red_reg;
  dvi_green = dvi_green_reg;
  dvi_blue = dvi_blue_reg;
  dvi_active = vga_reg.active;
  dvi_x = vga_reg.pos.x;
  dvi_y = vga_reg.pos.y;
  dvi_overclock_counter = vga_reg.overclock_counter;
  dvi_valid = vga_reg.valid;

  // Register inputs to be output next cycle
  // Black color when inactive
  pixel_t active_color;
  if(vga.active)
  {
    active_color = color;
  }
  // Output delay regs written when valid
  if(vga.valid){
    dvi_red_reg = active_color.r;
    dvi_green_reg = active_color.g;
    dvi_blue_reg = active_color.b;
    vga_reg = vga;
  }
  vga_reg.overclock_counter = vga.overclock_counter;
  vga_reg.valid = vga.valid;
}

#endif // ifdef __PIPELINEC__