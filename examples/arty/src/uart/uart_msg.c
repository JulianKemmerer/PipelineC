// Use UART RX and TX MAC to receive and send messages of some N bytes
#pragma once

// Helper macros for global clock cross wires
#include "wire.h"
// Use UART MAC to send/receive 8b words
#include "uart_mac.c"
// Include message type
#include "uart_msg.h"

// Receive messages
// Globally visible ports / wires
// Inputs
uint1_t uart_rx_msg_out_ready;
// Outputs
uart_msg_s uart_rx_msg_out;
#include "clock_crossing/uart_rx_msg_out_ready.h"
#include "clock_crossing/uart_rx_msg_out.h"

// Deserialize bytes into msg
deserializer(uart_rx_msg_deserializer, uint8_t, UART_MSG_SIZE) // macro

// Receive logic
#pragma MAIN_MHZ uart_rx_msg uart_rx_mac // Match freq of MAC module
void uart_rx_msg()
{
  // Read global/virtual input ports
  // Read input port ready flag
  uint1_t msg_out_ready;
  WIRE_READ(uint1_t, msg_out_ready, uart_rx_msg_out_ready)
  // Read stream of 8b words from mac
  uart_mac_s rx_mac_word_out;
  WIRE_READ(uart_mac_s, rx_mac_word_out, uart_rx_mac_word_out)

  // Deserialize stream of N bytes from mac into a stream of N byte messages
  uart_rx_msg_deserializer_o_t deser = uart_rx_msg_deserializer(rx_mac_word_out.data, rx_mac_word_out.valid, msg_out_ready);
  uart_msg_s msg_out;
  msg_out.data.data = deser.out_data;
  msg_out.valid = deser.out_data_valid;
  
  // Write global/virtual output ports
  // Connect msg deser ready output to uart_rx_mac input
  WIRE_WRITE(uint1_t, uart_rx_mac_out_ready, deser.in_data_ready)  
  // Output message stream
  WIRE_WRITE(uart_msg_s, uart_rx_msg_out, msg_out)
}

// Transmit messages
// Globally visible ports / wires
// Inputs
uart_msg_s uart_tx_msg_in;
// Outputs
uint1_t uart_tx_msg_in_ready;
#include "clock_crossing/uart_tx_msg_in.h"
#include "clock_crossing/uart_tx_msg_in_ready.h"

// Serialize messages into bytes
serializer(uart_tx_msg_serializer, uint8_t, UART_MSG_SIZE) // macro

// Transmit logic
#pragma MAIN_MHZ uart_tx_msg uart_tx_mac // Match freq of MAC module
void uart_tx_msg()
{
  // Read global/virtual input ports
  uart_msg_s msg_in;
  WIRE_READ(uart_msg_s, msg_in, uart_tx_msg_in)
  // Read flow control from tx mac
  uint1_t mac_ready;
  WIRE_READ(uint1_t, mac_ready, uart_tx_mac_in_ready)
  
  // Serialize single N byte message into stream of N bytes
  uart_tx_msg_serializer_o_t ser = uart_tx_msg_serializer(msg_in.data.data, msg_in.valid, mac_ready);

  // Write global/virtual output ports
  // Output stream of 8b bytes into tx mac, serial data out
  uart_mac_s mac_in_word;
  mac_in_word.data = ser.out_data;
  mac_in_word.valid = ser.out_data_valid;
  WIRE_WRITE(uart_mac_s, uart_tx_mac_word_in, mac_in_word)
  WIRE_WRITE(uint1_t, uart_tx_msg_in_ready, ser.in_data_ready)
}
