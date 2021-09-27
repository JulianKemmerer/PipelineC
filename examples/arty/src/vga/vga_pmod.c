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
  b.jb0 = vga.g >> 0;
  b.jb1 = vga.g >> 1;
  b.jb2 = vga.g >> 2;
  b.jb3 = vga.g >> 3;
  b.jb4 = vga.r >> 0;
  b.jb5 = vga.r >> 1;
  b.jb6 = vga.r >> 2;
  b.jb7 = vga.r >> 3;
  app_to_pmod_jc_t c;
  c.jc0 = vga.b >> 0;
  c.jc1 = vga.b >> 1;
  c.jc2 = vga.b >> 2;
  c.jc3 = vga.b >> 3;
  c.jc4 = vga.hs;
  c.jc5 = vga.vs;

  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jb, b)
  WIRE_WRITE(app_to_pmod_jb_t, app_to_pmod_jc, c)
}

