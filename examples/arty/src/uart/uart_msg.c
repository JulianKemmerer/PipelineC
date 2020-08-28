// Use UART RX and TX MAC to receive and send messages of some N bytes
#pragma once

// Helper macros for global clock cross wires
#include "wire.h"
// Use UART MAC to send/receive 8b words
#include "uart_mac.c"
// Include message type
#include "uart_msg.h"

// Receive messages
// Deserialize bytes into msg
deserializer(uart_rx_msg_deserializer, uint8_t, UART_MSG_SIZE) // macro
// 'Clock crossing' (just a wire in this case) used for backward flowing flow control signal
uint1_t uart_rx_msg_ready; // Flow control
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_rx_msg_ready_clock_crossing.h"
// Output type
typedef struct uart_rx_msg_o_t
{
  uart_msg_s msg_out;
  uint1_t overflow;
}uart_rx_msg_o_t;
// Receive logic
uart_rx_msg_o_t uart_rx_msg(uint1_t mac_data_in, uint1_t msg_out_ready)
{
  uart_rx_msg_o_t output;
  
  // Read flow control 'clock crossing'/'feedback' coming back into this func
  uint1_t_array_1_t deser_readys = uart_rx_msg_ready_READ();
  uint1_t deser_ready = deser_readys.data[0];
  
  // Incoming serial data into rx mac, stream of 8b words output
  uart_rx_mac_o_t rx_mac = uart_rx_mac(mac_data_in, deser_ready);
  output.overflow = rx_mac.overflow;
    
  // Deserialize stream of N bytes into a single N byte message
  uart_rx_msg_deserializer_o_t deser = uart_rx_msg_deserializer(rx_mac.word_out.data, rx_mac.word_out.valid, msg_out_ready);
  output.msg_out.data.data = deser.out_data;
  output.msg_out.valid = deser.out_data_valid;
  
  // Send flow control signal out and back into this func
  uint1_t deser_ready_out = deser.in_data_ready;
  uint1_t_array_1_t deser_readys_out;
  deser_readys_out.data[0] = deser_ready_out;
  uart_rx_msg_ready_WRITE(deser_readys_out);
 
  return output;
}

// Transmit messages
// Serialize messages into bytes
serializer(uart_tx_msg_serializer, uint8_t, UART_MSG_SIZE) // macro
// 'Clock crossing' (just a wire in this case) used for backward flowing flow control signal
uint1_t uart_tx_msg_ready; // Flow control
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_tx_msg_ready_clock_crossing.h"
// Output type
typedef struct uart_tx_msg_o_t
{
  uint1_t mac_data_out;
  uint1_t msg_in_ready;
}uart_tx_msg_o_t;
uart_tx_msg_o_t uart_tx_msg(uart_msg_s msg_in)
{
  uart_tx_msg_o_t output;
  
  // Read flow control 'clock crossing'/'feedback' coming back into this func
  uint1_t_array_1_t mac_readys = uart_tx_msg_ready_READ();
  uint1_t mac_ready = mac_readys.data[0];
  
  // Serialize single N byte message into stream of N bytes
  uart_tx_msg_serializer_o_t ser = uart_tx_msg_serializer(msg_in.data.data, msg_in.valid, mac_ready);
  output.msg_in_ready = ser.in_data_ready;

  // Stream of 8b bytes into tx mac, serial data out
  uart_mac_s mac_in_word;
  mac_in_word.data = ser.out_data;
  mac_in_word.valid = ser.out_data_valid;
  uart_tx_mac_o_t tx_mac = uart_tx_mac(mac_in_word);
  output.mac_data_out = tx_mac.data_out;
  
  // Send flow control signal out and back into this func
  uint1_t mac_ready_out = tx_mac.word_in_ready;
  uint1_t_array_1_t mac_readys_out;
  mac_readys_out.data[0] = mac_ready_out;
  uart_tx_msg_ready_WRITE(mac_readys_out);
  
  return output;  
}


// Main function wrappers around RX and TX that expose message ports as
// globally visible clock cross wires

// RX
// Inputs
uint1_t uart_rx_msg_msg_out_ready;
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_rx_msg_msg_out_ready_clock_crossing.h"
// Outputs
uart_msg_s uart_rx_msg_msg_out;
#include "uart_msg_s_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_rx_msg_msg_out_clock_crossing.h"
void uart_rx_msg_main(uint1_t mac_data_in)
{ 
  // Read input msg out ready flag
  uint1_t msg_out_ready;
  WIRE_READ(uint1_t, msg_out_ready, uart_rx_msg_msg_out_ready)
  
  // Connect to RX module
  uart_rx_msg_o_t uart_rx_msg_o = uart_rx_msg(mac_data_in, msg_out_ready);
  
  // Write message out of this function
  WIRE_WRITE(uart_msg_s, uart_rx_msg_msg_out, uart_rx_msg_o.msg_out)
}

// TX
// Inputs
uart_msg_s uart_tx_msg_msg_in;
#include "uart_msg_s_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_tx_msg_msg_in_clock_crossing.h"
// Outputs
uint1_t uart_tx_msg_msg_in_ready;
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_tx_msg_msg_in_ready_clock_crossing.h"
// Output wire is mac_data_out
uint1_t uart_tx_msg_main()
{ 
  // Read incoming uart msg stream
  uart_msg_s msg_in_stream;
  WIRE_READ(uart_msg_s, msg_in_stream, uart_tx_msg_msg_in)
  
  // Connect to TX module
  uart_tx_msg_o_t uart_tx_msg_o = uart_tx_msg(msg_in_stream);
  
  // Write ready for input message out of this function
  WIRE_WRITE(uint1_t, uart_tx_msg_msg_in_ready, uart_tx_msg_o.msg_in_ready)
  
  // Output mac data
  return uart_tx_msg_o.mac_data_out;
}
