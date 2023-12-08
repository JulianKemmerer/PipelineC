#pragma once

// Wire 24b DVI signals to pmod
// Need to use high speed pmod ports on Arty JB+JC?
// DVI PMOD J1 = Arty PMOD JB
// DVI PMOD J2 = Arty PMOD JC
// https://digilent.com/reference/_media/arty:arty_sch.pdf
//
// https://github.com/icebreaker-fpga/icebreaker-pmod/blob/master/dvi-24bit/v1.0b/dvi-24bit-sch.pdf
// https://github.com/smunaut/ice40-playground/blob/avi/projects/avi_pmod/rtl/hdmi_phy_ddr_1x.v
// Per hdmi_phy_ddr_1x and @tnt EDGE=0 "Falling edge first (match Sil9022 config!)"
// "On ice 40 the D_OUT_1 is the falling edge and this is what's going to get out first
// since the input to that port is clocked on rising edge 
// and after a rising edge the first thing that occurs is the falling edge and not another rising edge."
//
// However, the schematic shows device as SiI164 with the EDGE input tied to 3V3 = 1
// So this code will use EDGE=1 ...
// Additionally per Xilinx docs ODDR "can forward a copy of the clock to the output...
// by tying the D1 input of the ODDR primitive High, and the D2 input Low"
//  hdmi_phy_ddr_1x uses 
//    .D_OUT_0(~EDGE), .D_OUT_1(EDGE),
//  and
//    .D_OUT_0(in_data[2*DW-1:DW]), .D_OUT_1 (in_data[ DW-1: 0]),
// This seems reversed for this design where EDGE=1
// So this code will swap what hdmi_phy_ddr_1x does and 
// use data0/the first data port for the EDGE=1 and data LSBs inputs
//
// Finally the DDR clock + data needs alignment:
// The SiI164 deskew configuration over I2C pins are not available to use.
// Additionally the deskew DK[3:1] bits have been hard wired on the PMOD pcb.
// Artix 7 FPGAs do not have ODELAY delay modules on outputs, can't use those.
// For those reasons a separate MMCM/PLL is used to produce a phase shifted clock signal.
// Test results regarding phase shift looks like so:
/*
    DEG     Working?
    ===     ========
    0       word order swapped, green glitchy
    22.5    word order swapped, blue glitchy
    45.0    word order swapped, little/none glitch
    67.5    no signal on monitor
    90      no signal on monitor
    112.5   very slight red-blue glitching
    123.75  looks good
    135     looks good
    146.25  looks good
    157.5   looks good
    168.75  looks good
    180     blue-green heavy glitching
*/
// Because of the above results the ~center point in the good region
// around 146.25 degrees phase shift is what is specified below.

// Constants and logic to produce DVI signals at fixed resolution
#include "vga/vga_timing.h" // timing is same as VGA
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color

#ifdef __PIPELINEC__
#include "compiler.h"
#include "wire.h"
#include "uintN_t.h"
#include "io/oddr.h"
#include "io/odelay.h"

// Include Arty specific PMOD ports for now
#include "../examples/arty/src/pmod/pmod_jb.c"
#include "../examples/arty/src/pmod/pmod_jc.c"

// Verilator cannot sim Xilinx ODDRs used below
#ifndef USE_VERILATOR 
// DVI pmod DDR clock signal needs to be separate
// so it can be manually phase aligned with the DDR data 
// Connect output to PMODC[2]: c.jc2 = ddr_clk;
MAIN_MHZ_GROUP(dvi_pmod_shifted_clock, PIXEL_CLK_MHZ, delayed_146p25deg)
uint1_t dvi_pmod_shifted_clock()
{
  uint1_t edge = 1;
  uint1_t ddr_clk = oddr_same_edge(edge, !edge);
  return ddr_clk;
}
#endif // not verilator

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
//#include "clock_crossing/dvi_to_app.h"
app_to_dvi_t app_to_dvi;
#include "clock_crossing/app_to_dvi.h"

// Top level module connecting to globally visible ports
#pragma MAIN dvi // No associated clock domain yet
void dvi()
{
  app_to_dvi_t dvi;
  WIRE_READ(app_to_dvi_t, dvi, app_to_dvi)
  //WIRE_WRITE(dvi_to_app_t, dvi_to_app, inputs)

  // Verilator cannot sim Xilinx ODDRs used below
  #ifndef USE_VERILATOR 
  
  // Convert 8b rgb values to 24b
  uint24_t color_data;
  color_data = uint24_uint8_16(color_data, dvi.color.r); // [23:16] = r
  color_data = uint24_uint8_8(color_data, dvi.color.g); // [15:8] = g
  color_data = uint24_uint8_0(color_data, dvi.color.b); // [7:0] = b

  // Per SiI164 datasheet first data on the wire is LSBs
  uint12_t data0 = color_data;       // LSBs G[3:0] B[7:0]
  uint12_t data1 = color_data >> 12; // MSBs R[7:0] G[7:4]
  
  // Convert two words to double rate 12 bits
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

  // Connect double data rate signals to PMOD connector
  // A layer of tracing schematic wires here:
  // Arty PMOD JC = DVI PMOD J1
  app_to_pmod_jc_t c;
  // pmod pin1: dvi pmod sch d3 -> arty sch jc1_p -> jc0
  c.jc0 = ddr_data[3];
  // pmod pin2: dvi pmod sch d1 -> arty sch jc1_n -> jc1
  c.jc1 = ddr_data[1];
  // pmod pin3: dvi pmod sch clk -> arty sch jc2_p -> jc2
  // Double rate clock signal is separate since needs special phase alignment
  // pmod pin4: dvi pmod sch hs -> arty sch jc2_n -> jc3
  c.jc3 = ddr_hsync;
  // pmod pin7: dvi pmod sch d2 -> arty sch jc3_p -> jc4
  c.jc4 = ddr_data[2];
  // pmod pin8: dvi pmod sch d0 -> arty sch jc3_n -> jc5
  c.jc5 = ddr_data[0];
  // pmod pin9: dvi pmod sch de -> arty sch jc4_p -> jc6
  c.jc6 = ddr_active;
  // pmod pin10: dvi pmod sch vs -> arty sch jc4_n -> jc7
  c.jc7 = ddr_vsync;
  // Arty PMOD JB = DVI PMOD J2
  app_to_pmod_jb_t b;
  // pmod pin1: dvi pmod sch d11 -> arty sch jb1_p -> jb0
  b.jb0 = ddr_data[11];
  // pmod pin2: dvi pmod sch d9 -> arty sch jb1_n -> jb1
  b.jb1 = ddr_data[9];
  // pmod pin3: dvi pmod sch d7 -> arty sch jb2_p -> jb2
  b.jb2 = ddr_data[7];
  // pmod pin4: dvi pmod sch d5 -> arty sch jb2_n -> jb3
  b.jb3 = ddr_data[5];
  // pmod pin7: dvi pmod sch d10 -> arty sch jb3_p -> jb4
  b.jb4 = ddr_data[10];
  // pmod pin8: dvi pmod sch d8 -> arty sch jb3_n -> jb5
  b.jb5 = ddr_data[8];
  // pmod pin9: dvi pmod sch d6 -> arty sch jb4_p -> jb6
  b.jb6 = ddr_data[6];
  // pmod pin10: dvi pmod sch d4 -> arty sch jb4_n -> jb7
  b.jb7 = ddr_data[4];
  #else
  // Verilator dummy connections
  app_to_pmod_jc_t c;
  app_to_pmod_jb_t b;
  #endif // not verilator
  
  WIRE_WRITE(app_to_pmod_jc_t, app_to_pmod_jc, c)
  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jb, b)
}

// Logic for connecting outputs/sim debug wires
// Generate top level debug ports with associated pipelinec_verilator.h
#include "debug_port.h"
// Verilator Debug wires
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
  static uint8_t overclock_counter_reg;
  static uint1_t valid_reg;
  
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
  vsync = o.vga_timing.vsync;
  hsync = o.vga_timing.hsync;
  dvi_red = o.color.r;
  dvi_green = o.color.g;
  dvi_blue = o.color.b;
  dvi_active = o.vga_timing.active;
  dvi_x = x_reg;
  dvi_y = y_reg;
  dvi_overclock_counter = overclock_counter_reg;
  dvi_valid = valid_reg;
  
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
  // 8b colors from hardware
  uint8_t r = g_top->dvi_red;
  uint8_t g = g_top->dvi_green;
  uint8_t b = g_top->dvi_blue;
  uint1_t active = g_top->dvi_active;
  uint12_t x = g_top->dvi_x;
  uint12_t y = g_top->dvi_y;
  uint1_t valid = g_top->dvi_valid;
  if(active & valid)
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
