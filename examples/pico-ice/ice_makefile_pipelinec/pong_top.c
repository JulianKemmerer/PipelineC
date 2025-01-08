// See configuration details like top level pin mapping in top.h
#include "top.h"

// Pong stuff like user_input_t and render state machine
#include "examples/pong/pong.h"

// Use UART chars from typing in the terminal
// ex. WASD up left down right to move paddles
// pong code works on 'was the button pressed this frame'
// fake button up and down 
// not seeing a char for fraction of section = button up
user_input_t uart_rx_to_buttons(){
  // Output reg for button state
  static user_input_t out_reg;
  user_input_t o = out_reg;
  // Timeout counter
  static uint32_t counter;
  uint32_t ONE_SEC = (uint32_t)(PLL_CLK_MHZ * 1000000.0 * 0.25);

  // If counter elapsed then reset output register and reset counter
  counter += 1;
  if(counter >= ONE_SEC){
    user_input_t user_input_t_NULL = {0};
    out_reg = user_input_t_NULL;
    counter = 0;
  }

  // Always ready to receive a char
  uart_rx_mac_out_ready = 1;

  // If receiving valid uart char this cycle
  // then update output register and reset counter
  if(uart_rx_mac_word_out.valid){
    char c = uart_rx_mac_word_out.data;
    if(c == 'w'){
      out_reg.paddle_l_up = 1;
    }else if(c == 's'){
      out_reg.paddle_l_down = 1;
    }else if(c == 'i'){
      out_reg.paddle_r_up = 1;
    }else if(c == 'k'){
      out_reg.paddle_r_down = 1;
    }
    counter = 0;
  }

  return o;
}

// VGA pmod PONG part of demo
MAIN_MHZ(pong_vga_datapath, PIXEL_CLK_MHZ) 
void pong_vga_datapath(){
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // State machine that animates pong game based on user input
  // and outputs VGA color signals for given pixel
  user_input_t user_input = uart_rx_to_buttons();
  pixel_t color = render_state_machine(user_input, vga_signals);

  // Drive output signals/registers
  vga_r = color.r;
  vga_g = color.g;
  vga_b = color.b;
  vga_hs = vga_signals.hsync;
  vga_vs = vga_signals.vsync;
}

// Blinky part of demo // TODO make related to pong somehow?
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
