#pragma once

// Wire 24b DVI signals to pmod
// https://digilent.com/reference/_media/arty:arty_sch.pdf
// https://github.com/icebreaker-fpga/icebreaker-pmod/blob/master/dvi-24bit/v1.0b/dvi-24bit-sch.pdf
// DVI PMOD J1 = Arty PMOD JD
// DVI PMOD J2 = Arty PMOD JC

// Constants and logic to produce DVI signals at fixed resolution
#include "vga/vga_timing.h" // timing is same as VGA
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color

#ifdef __PIPELINEC__
#include "wire.h"
#include "uintN_t.h"
#include "io/oddr.h"

// Include Arty specific PMOD ports for now
#include "../examples/arty/src/pmod/pmod_jc.c"
#include "../examples/arty/src/pmod/pmod_jd.c"

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct dvi_to_app_t
{
  // No inputs from DVI - is output
}app_to_dvi_t;*/
// Outputs
typedef struct app_to_dvi_t
{
  vga_signals_t vga_timing;
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

  // Convert 8b rgb values to 24b
  uint24_t color_data;
  color_data = uint24_uint8_16(color_data, dvi.color.r); // [23:16] = r
  color_data = uint24_uint8_8(color_data, dvi.color.g); // [15:8] = g
  color_data = uint24_uint8_0(color_data, dvi.color.b); // [7:0] = b
  
  // ~"Convert" 24b color data to double data rate 12b
  //uint12_t data0 = color_data >> 12; // MSBs R[7:0] G[7:4]
  //uint12_t data1 = color_data;       // LSBs G[3:0] B[7:0]  
  uint12_t data0 = color_data;       // LSBs G[3:0] B[7:0] 
  uint12_t data1 = color_data >> 12; // MSBs R[7:0] G[7:4]
  uint1_t ddr_data[12];
  uint32_t i;
  for(i=0;i<12;i+=1)
  {
    ddr_data[i] = oddr_same_edge(data0>>i, data1>>i);
  }

  // ~"Convert" hsync, vsync, and active/valid/enable signal to double data rate
  uint1_t ddr_hsync = oddr_same_edge(dvi.vga_timing.hsync, dvi.vga_timing.hsync);
  uint1_t ddr_vsync = oddr_same_edge(dvi.vga_timing.vsync, dvi.vga_timing.vsync);
  uint1_t ddr_active = oddr_same_edge(dvi.vga_timing.active, dvi.vga_timing.active);

  // Make a double rate clock signal using an ODDR and constant toggled data bits
  uint1_t edge = 0;
  uint1_t ddr_clk = oddr_same_edge(!edge, edge);

  // Connect double data rate signals to PMOD connector
  // A layer of tracing schematic wires here:
  // Arty PMOD JD = DVI PMOD J1
  app_to_pmod_jd_t d;
  // pmod pin1: dvi pmod sch d3 -> arty sch jd1 -> jd0
  d.jd0 = ddr_data[3];
  // pmod pin2: dvi pmod sch d1 -> arty sch jd2 -> jd1
  d.jd1 = ddr_data[1];
  // pmod pin3: dvi pmod sch clk -> arty sch jd3 -> jd2
  d.jd2 = ddr_clk;
  // pmod pin4: dvi pmod sch hs -> arty sch jd4 -> jd3
  d.jd3 = ddr_hsync;
  // pmod pin7: dvi pmod sch d2 -> arty sch jd7 -> jd4
  d.jd4 = ddr_data[2];
  // pmod pin8: dvi pmod sch d0 -> arty sch jd8 -> jd5
  d.jd5 = ddr_data[0];
  // pmod pin9: dvi pmod sch de -> arty sch jd9 -> jd6
  d.jd6 = ddr_active;
  // pmod pin10: dvi pmod sch vs -> arty sch jd10 -> jd7
  d.jd7 = ddr_vsync;
  // Arty PMOD JC = DVI PMOD J2
  app_to_pmod_jc_t c;
  // pmod pin1: dvi pmod sch d11 -> arty sch jc1_p -> jc0
  c.jc0 = ddr_data[11];
  // pmod pin2: dvi pmod sch d9 -> arty sch jc1_n -> jc1
  c.jc1 = ddr_data[9];
  // pmod pin3: dvi pmod sch d7 -> arty sch jc2_p -> jc2
  c.jc2 = ddr_data[7];
  // pmod pin4: dvi pmod sch d5 -> arty sch jc2_n -> jc3
  c.jc3 = ddr_data[5];
  // pmod pin7: dvi pmod sch d10 -> arty sch jc3_p -> jc4
  c.jc4 = ddr_data[10];
  // pmod pin8: dvi pmod sch d8 -> arty sch jc3_n -> jc5
  c.jc5 = ddr_data[8];
  // pmod pin9: dvi pmod sch d6 -> arty sch jc4_p -> jc6
  c.jc6 = ddr_data[6];
  // pmod pin10: dvi pmod sch d4 -> arty sch jc4_n -> jc7
  c.jc7 = ddr_data[4];

  WIRE_WRITE(app_to_pmod_jc_t, app_to_pmod_jc, c)
  WIRE_WRITE(app_to_pmod_jd_t, app_to_pmod_jd, d)
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

// TODO organize to use vga_signals_t reg type instead
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
  o.vga_timing.hsync = h_sync_dly_reg;
  o.vga_timing.vsync = v_sync_dly_reg;
  o.vga_timing.active = active_reg;
  o.color.r = dvi_red_reg;
  o.color.g = dvi_green_reg;
  o.color.b = dvi_blue_reg;
  WIRE_WRITE(app_to_dvi_t, app_to_dvi, o)
  
  // Connect to Verilator debug ports
  vsync(o.vga_timing.vsync);
  hsync(o.vga_timing.hsync);
  dvi_red(o.color.r);
  dvi_green(o.color.g);
  dvi_blue(o.color.b);
  dvi_active(o.vga_timing.active);
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
