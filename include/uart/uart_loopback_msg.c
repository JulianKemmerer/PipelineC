// Loopback UART after buffering a 'message' of N bytes

#include "compiler.h" // MAIN_MHZ macro

// Logic to receive and transmit uart messages
#include "uart_msg.c"
// LEDs for status
#include "../leds/leds.c"

// Sticky save overflow bit
uint1_t overflow;

// The main function
#pragma MAIN app
void app()
{ 
  // Read virtual/global input ports/wires
  // Read N byte messages from uart rx output
  uart_msg_s rx_msg;
  WIRE_READ(uart_msg_s, rx_msg, uart_rx_msg_out)
  // And rx overflow flag from MAC
  uint1_t rx_overflow;  
  WIRE_READ(uint1_t, rx_overflow, uart_rx_mac_overflow)
  // Read if uart tx is ready
  uint1_t tx_ready;
  WIRE_READ(uint1_t, tx_ready, uart_tx_msg_in_ready)
  //////////////////////////////////////////////////////////////////
  
  
  
  // Record if overflow occurs
  overflow |= rx_overflow; // |= makes sticky flag
  
  // Loopback RX to TX
  // No other work to be done - loopback drives outputs using inputs
  


  //////////////////////////////////////////////////////////////////
  // Drive virtual/global output ports/wires
  // Output RX is ready if TX is ready
  WIRE_WRITE(uint1_t, uart_rx_msg_out_ready, tx_ready)
  // Output transmit N byte message 
  uart_msg_s tx_msg = rx_msg;
  WIRE_WRITE(uart_msg_s, uart_tx_msg_in, tx_msg)
  // LEDs indicate overflow
  uint1_t led[4];
  led[0] = overflow;
  led[1] = overflow;
  led[2] = overflow;
  led[3] = overflow;
  WIRE_WRITE(uint4_t, leds, uint1_array4_le(led))
}
