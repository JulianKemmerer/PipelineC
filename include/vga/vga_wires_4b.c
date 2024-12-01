#pragma once
#include "compiler.h"

// Glue 24b VGA wires to 12b VGA...

uint8_t vga_r_8b_to_4b;
uint8_t vga_g_8b_to_4b;
uint8_t vga_b_8b_to_4b;

#define VGA_R_WIRE vga_r_8b_to_4b
#define VGA_G_WIRE vga_g_8b_to_4b
#define VGA_B_WIRE vga_b_8b_to_4b
#include "vga/vga_wires.c"

#pragma MAIN vga_4b_connect
void vga_4b_connect(){
  uint4_t r = vga_r_8b_to_4b >> 4;
  uint4_t g = vga_g_8b_to_4b >> 4;
  uint4_t b = vga_b_8b_to_4b >> 4;
  VGA_R0_WIRE = r(0);
  VGA_R1_WIRE = r(1);
  VGA_R2_WIRE = r(2);
  VGA_R3_WIRE = r(3);
  VGA_G0_WIRE = g(0);
  VGA_G1_WIRE = g(1);
  VGA_G2_WIRE = g(2);
  VGA_G3_WIRE = g(3);
  VGA_B0_WIRE = b(0);
  VGA_B1_WIRE = b(1);
  VGA_B2_WIRE = b(2);
  VGA_B3_WIRE = b(3);
}