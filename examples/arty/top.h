// See Arty-A7-35|100-Master.xdc files
#pragma PART "xc7a35ticsg324-1l" // Artix 7 35T (Arty)

// Configure IO direction for each pin used
// UART on ChipKit header pins
#define CK_29_IN
#define CK_30_OUT
/*
// PMOD0A
#define ICE_45_OUT
#define ICE_47_OUT
#define ICE_2_OUT
#define ICE_4_OUT
// PMOD0B
#define ICE_44_OUT
#define ICE_46_OUT
#define ICE_48_OUT
#define ICE_3_OUT
// PMOD1A
#define ICE_31_OUT
#define ICE_34_OUT
#define ICE_38_OUT
#define ICE_43_OUT
// PMOD1B
#define ICE_28_OUT
#define ICE_32_OUT
#define ICE_36_OUT
#define ICE_42_OUT
*/
#include "board/arty.h"

// Configure UART module
#define UART_TX_OUT_WIRE ck_30
#define UART_RX_IN_WIRE ck_29
#define UART_CLK_MHZ 12.0
#define UART_BAUD 115200
#include "uart/uart_mac.c"

/*
// Configure PMOD ports
//  A=top/inner row, pin1-6
//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_0a
#define PMOD_O4_WIRE ice_45
#define PMOD_O3_WIRE ice_47
#define PMOD_O2_WIRE ice_2
#define PMOD_O1_WIRE ice_4
#include "pmod/pmod_wires.h"
#define PMOD_NAME pmod_0b
#define PMOD_O4_WIRE ice_44
#define PMOD_O3_WIRE ice_46
#define PMOD_O2_WIRE ice_48
#define PMOD_O1_WIRE ice_3
#include "pmod/pmod_wires.h"
#define PMOD_NAME pmod_1a
#define PMOD_O4_WIRE ice_31
#define PMOD_O3_WIRE ice_34
#define PMOD_O2_WIRE ice_38
#define PMOD_O1_WIRE ice_43
#include "pmod/pmod_wires.h"
#define PMOD_NAME pmod_1b
#define PMOD_O4_WIRE ice_28
#define PMOD_O3_WIRE ice_32
#define PMOD_O2_WIRE ice_36
#define PMOD_O1_WIRE ice_42
#include "pmod/pmod_wires.h"

// Configure VGA module to use PMOD0 and PMOD1
// rgb is 8b internally, 4b on pmod, then 4 single bits IO
// PMOD0 = VGA PMOD J1
// PMOD1 = VGA PMOD J2
#define VGA_R0_WIRE pmod_0a_o1 // J1-1 = 0A IO 1
#define VGA_R1_WIRE pmod_0a_o2 // J1-2 = 0A IO 2
#define VGA_R2_WIRE pmod_0a_o3 // J1-3 = 0A IO 3
#define VGA_R3_WIRE pmod_0a_o4 // J1-4 = 0A IO 4
//
#define VGA_G0_WIRE pmod_1a_o1 // J2-1 = 1A IO 1
#define VGA_G1_WIRE pmod_1a_o2 // J2-2 = 1A IO 2
#define VGA_G2_WIRE pmod_1a_o3 // J2-3 = 1A IO 3
#define VGA_G3_WIRE pmod_1a_o4 // J2-4 = 1A IO 4
//
#define VGA_B0_WIRE pmod_0b_o1 // J1-7 = 0B IO 1
#define VGA_B1_WIRE pmod_0b_o2 // J1-8 = 0B IO 2
#define VGA_B2_WIRE pmod_0b_o3 // J1-9 = 0B IO 3
#define VGA_B3_WIRE pmod_0b_o4 // J1-10 = 0B IO 4
//
#define VGA_HS_WIRE pmod_1b_o1 // J2-7 = 1B IO 1
#define VGA_VS_WIRE pmod_1b_o2 // J2-8 = 1B IO 2
#include "vga/vga_wires_4b.c"

*/