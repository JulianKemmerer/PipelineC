#pragma once
#include "compiler.h"

// Separate wires and MAINs so can be different clock domains

#ifdef VGA_HS_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, VGA_HS_WIRE, vga_hs)
#else
DECL_OUTPUT_REG(uint1_t, vga_hs)
#endif

#ifdef VGA_VS_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, VGA_VS_WIRE, vga_vs)
#else
DECL_OUTPUT_REG(uint1_t, vga_vs)
#endif

#ifdef VGA_R_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint8_t, VGA_R_WIRE, vga_r)
#else
DECL_OUTPUT_REG(uint8_t, vga_r)
#endif

#ifdef VGA_G_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint8_t, VGA_G_WIRE, vga_g)
#else
DECL_OUTPUT_REG(uint8_t, vga_g)
#endif

#ifdef VGA_B_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint8_t, VGA_B_WIRE, vga_b)
#else
DECL_OUTPUT_REG(uint8_t, vga_b)
#endif
