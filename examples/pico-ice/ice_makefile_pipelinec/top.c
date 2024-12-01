// See configuration details like top level pin mapping in top.h
#include "top.h"

// Blinky part of demo
#define N 22
#define count_t uint23_t
MAIN_MHZ(blinky_main, PLL_CLK_MHZ)
void blinky_main(){
  static count_t counter;
  led_r = 1;
  led_g = 1;
  led_b = counter >> N;
  counter += 1;
}

// UART part of demo
MAIN_MHZ(uart_main, PLL_CLK_MHZ)
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
}

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


#ifdef LED_8SSD_ENABLED
#error "TODO disable VGA pmod since uses same pins!"
// LED PMOD part of demo
// TODO move this `#define LED_8SSD_` stuff into 
// pipelinec include library for eight digit seven segment display?
//#include "leds/leds_8ssd.h" ? like leds/rgb_led?
// Configure PMOD ports to be used for LED demo
// if pmod is moved, change pmod name used here
#define LED_8SSD_D7 pmod_1b_o4 // ice_28
#define LED_8SSD_D0 pmod_1a_o1 // ice_43
#define LED_8SSD_D5 pmod_1b_o3 // ice_32
#define LED_8SSD_D6 pmod_1a_o4 // ice_31
#define LED_8SSD_D2 pmod_1a_o2 // ice_38
#define LED_8SSD_D3 pmod_1b_o2 // ice_36
#define LED_8SSD_D1 pmod_1b_o1 // ice_42
#define LED_8SSD_D4 pmod_1a_o3 // ice_34
MAIN_MHZ(led_8ssd_main, PLL_CLK_MHZ)
void led_8ssd_main(){
  // Match verilog names
  uint1_t d0;
  uint1_t d1;
  uint1_t d2;
  uint1_t d3;
  uint1_t d4;
  uint1_t d5;
  uint1_t d6;
  uint1_t d7;
  // TODO just make array?
  // ?? uint1_t d[8];

  // TODO insert code here to correctly drive the display
  static uint1_t toggle_dummy_signal; // *See note below
  d0 = toggle_dummy_signal;
  d1 = toggle_dummy_signal;
  d2 = toggle_dummy_signal;
  d3 = toggle_dummy_signal;
  d4 = toggle_dummy_signal;
  d5 = toggle_dummy_signal;
  d6 = toggle_dummy_signal;
  d7 = toggle_dummy_signal;
  toggle_dummy_signal = ~toggle_dummy_signal;

  // Drive the top level pin outputs connect to pmod
  LED_8SSD_D0 = d0;
  LED_8SSD_D1 = d1;
  LED_8SSD_D2 = d2;
  LED_8SSD_D3 = d3;
  LED_8SSD_D4 = d4;
  LED_8SSD_D5 = d5;
  LED_8SSD_D6 = d6;
  LED_8SSD_D7 = d7;
}
// * GHDL BUG?
// When driving an output port with a constant, ex. d0 = 0;
// GHDL says:
//signal assignment not allowed here
//for
//signal port <= variable;
//then says
//warning: no assignment for port [-Wnowrite]
//WEIRD?
#endif
