// See Arty-A7-35|100-Master.xdc files
#pragma PART "xc7a35ticsg324-1l" // Artix 7 35T (Arty)

/* TODO TEST CHIPKIT HEADER AS UART PINS
// Configure IO direction for each pin used
// UART on ChipKit header pins
#define CK_29_IN
#define CK_30_OUT
*/

// PMODs for VGA demo
// PMOD JB
#define JB_0_OUT
#define JB_1_OUT
#define JB_2_OUT
#define JB_3_OUT
#define JB_4_OUT
#define JB_5_OUT
#define JB_6_OUT
#define JB_7_OUT
// PMOD JC
#define JC_0_OUT
#define JC_1_OUT
#define JC_2_OUT
#define JC_3_OUT
#define JC_4_OUT
#define JC_5_OUT
// UNUSED FOR VGA PMOD #define JC_6_OUT
// UNUSED FOR VGA PMOD #define JC_7_OUT
#include "board/arty.h"

/* TODO TEST CHIPKIT HEADER AS UART PINS
   (personal Arty has broken built in USB UART)
// Configure UART module
#define UART_TX_OUT_WIRE ck_30
#define UART_RX_IN_WIRE ck_29
#define UART_CLK_MHZ 25.0
#define UART_BAUD 115200
#include "uart/uart_mac.c"
*/

// Configure VGA module to use PMOD JB and PMOD JC
// rgb is 8b internally, 4b on pmod
#define VGA_R0_WIRE pmod_jb_a_o1
#define VGA_R1_WIRE pmod_jb_a_o2 
#define VGA_R2_WIRE pmod_jb_a_o3 
#define VGA_R3_WIRE pmod_jb_a_o4 
//
#define VGA_G0_WIRE pmod_jc_a_o1 
#define VGA_G1_WIRE pmod_jc_a_o2 
#define VGA_G2_WIRE pmod_jc_a_o3
#define VGA_G3_WIRE pmod_jc_a_o4 
//
#define VGA_B0_WIRE pmod_jb_b_o1 
#define VGA_B1_WIRE pmod_jb_b_o2 
#define VGA_B2_WIRE pmod_jb_b_o3 
#define VGA_B3_WIRE pmod_jb_b_o4 
//
#define VGA_HS_WIRE pmod_jc_b_o1 
#define VGA_VS_WIRE pmod_jc_b_o2
#include "vga/vga_wires_4b.c"

// Configure the VGA timing to use
// 640x480 is a 25MHz pixel clock
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#include "vga/vga_timing.h"