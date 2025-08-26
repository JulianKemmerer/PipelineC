// See Arty-A7-35|100-Master.xdc files
#pragma PART "xc7a100tcsg324-1"

/* TODO TEST CHIPKIT HEADER AS UART PINS
// Configure IO direction for each pin used
// UART on ChipKit header pins
#define CK_29_IN
#define CK_30_OUT
*/

// I2S on PMOD JA
/*
tx_mclk  ja[0] a o1
tx_lrck  ja[1] a o2
tx_sclk  ja[2] a o3
tx_data  ja[3] a o4
rx_mclk  ja[4] b o1
rx_lrck  ja[5] b o2
rx_sclk  ja[6] b o3
rx_data  ja[7] b i4
*/
/*
#define JA_0_OUT
#define I2S_TX_MCLK_WIRE pmod_ja_a_o1
#define JA_1_OUT
#define I2S_TX_LRCK_WIRE pmod_ja_a_o2
#define JA_2_OUT
#define I2S_TX_SCLK_WIRE pmod_ja_a_o3
#define JA_3_OUT
#define I2S_TX_DATA_WIRE pmod_ja_a_o4
#define JA_4_OUT
#define I2S_RX_MCLK_WIRE pmod_ja_b_o1
#define JA_5_OUT
#define I2S_RX_LRCK_WIRE pmod_ja_b_o2
#define JA_6_OUT
#define I2S_RX_SCLK_WIRE pmod_ja_b_o3
#define JA_7_IN
#define I2S_RX_DATA_WIRE pmod_ja_b_i4
*/
// Configure VGA module to use PMODs
// rgb is 8b internally, 4b on pmod
// PMOD JA
#define JA_0_OUT
#define JA_1_OUT
#define JA_2_OUT
#define JA_3_OUT
#define VGA_R0_WIRE pmod_ja_a_o1
#define VGA_R1_WIRE pmod_ja_a_o2 
#define VGA_R2_WIRE pmod_ja_a_o3 
#define VGA_R3_WIRE pmod_ja_a_o4 
#define JA_4_OUT
#define JA_5_OUT
#define JA_6_OUT
#define JA_7_OUT
#define VGA_B0_WIRE pmod_ja_b_o1 
#define VGA_B1_WIRE pmod_ja_b_o2 
#define VGA_B2_WIRE pmod_ja_b_o3 
#define VGA_B3_WIRE pmod_ja_b_o4 
// PMOD JB
#define JB_0_OUT
#define JB_1_OUT
#define JB_2_OUT
#define JB_3_OUT
#define VGA_G0_WIRE pmod_jb_a_o1 
#define VGA_G1_WIRE pmod_jb_a_o2 
#define VGA_G2_WIRE pmod_jb_a_o3
#define VGA_G3_WIRE pmod_jb_a_o4 
#define JB_4_OUT
#define JB_5_OUT
#define VGA_HS_WIRE pmod_jb_b_o1 
#define VGA_VS_WIRE pmod_jb_b_o2
// UNUSED FOR VGA PMOD #define JB_6_OUT
// UNUSED FOR VGA PMOD #define JB_7_OUT
#include "board/arty.h"
//#include "i2s/i2s_regs.c"
#include "vga/vga_wires_4b.c"

/* TODO TEST CHIPKIT HEADER AS UART PINS
   (personal Arty has broken built in USB UART)
// Configure UART module
#define UART_TX_OUT_WIRE ck_30
#define UART_RX_IN_WIRE ck_29
#define UART_CLK_MHZ 25.0
#define UART_BAUD 115200
#include "uart/uart_mac.c"
*/

// Configure the VGA timing to use
// 640x480 is a 25MHz pixel clock
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#include "vga/vga_timing.h"
