// See top level IO pin config in top.h
#include "top.h"

#define N 22
#define count_t uint23_t

#pragma MAIN_MHZ blinky_main 25.0
void blinky_main(){
  static count_t counter;
  led_r = 0;
  led_g = 0;
  led_b = counter >> N;
  counter += 1;
}

/* TODO TEST UART 
MAIN_MHZ(uart_main, UART_CLK_MHZ)
void uart_main(){
  // Default loopback connect
  uart_tx_mac_word_in = uart_rx_mac_word_out;
  uart_rx_mac_out_ready = uart_tx_mac_in_ready;

  // Override .data to do case change demo
  char in_char = uart_rx_mac_word_out.data;
  char out_char = in_char;
  uint8_t case_diff = 'a' - 'A';
  if(in_char >= 'a' && in_char <= 'z'){
    out_char = in_char - case_diff;
  }else if(in_char >= 'A' && in_char <= 'Z'){
    out_char = in_char + case_diff;
  }
  uart_tx_mac_word_in.data = out_char;
}*/

// VGA pmod part of demo
#include "vga/test_pattern.h"
// vga_timing() and PIXEL_CLK_MHZ from vga_timing.h in top.h
MAIN_MHZ(vga_pmod_main, PIXEL_CLK_MHZ) 
void vga_pmod_main(){
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Test pattern from Digilent of color bars and bouncing box
  test_pattern_out_t test_pattern_out = test_pattern(vga_signals);
  
  // Drive output signals/registers
  vga_r = test_pattern_out.pixel.r;
  vga_g = test_pattern_out.pixel.g;
  vga_b = test_pattern_out.pixel.b;
  vga_hs = test_pattern_out.vga_signals.hsync;
  vga_vs = test_pattern_out.vga_signals.vsync;
}