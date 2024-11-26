#pragma once
#include "compiler.h"
#include "uart_mac.h"
// UART PHY?MAC?(de)serialize? logic
// Single global instance wired up to uart_wires.c
// TODO make version that can live in .h and be reinstantiated
#include "uart_wires.c"

// RX side
// Globally visible ports / wires
// Inputs
uint1_t uart_rx_mac_out_ready;
// Outputs
stream(uint8_t) uart_rx_mac_word_out;
uint1_t uart_rx_mac_overflow;
#pragma MAIN uart_rx_mac
//MAIN_MHZ(uart_rx_mac, UART_CLK_MHZ)
void uart_rx_mac()
{
  // Receive bit stream from input wire
  // Fake always ready since need to overflow
  // on per byte level after deserializer
  uint1_t ready_uart_rx_bit_stream = 1;
  uart_rx_1b_t uart_rx_1b_out = uart_rx_1b(
    uart_rx, // input physical bit
    ready_uart_rx_bit_stream
  );
  // uart_rx_1b_out.overflow unused, never occurs
  
  // Input 1 bit 8 times to get to get 1 byte out
  uint1_t ready_for_uart_rx_byte_stream = 1;
  uart_deserializer_o_t deser = uart_deserializer(
    uart_rx_1b_out.bit_stream.data, 
    uart_rx_1b_out.bit_stream.valid, 
    ready_for_uart_rx_byte_stream
  );
  uart_rx_mac_word_out.data = uart_word_from_bits(deser.out_data);
  uart_rx_mac_word_out.valid = deser.out_data_valid;

  // Per byte overflow logic based on deser output handshake
  uart_rx_mac_overflow = 
    uart_rx_mac_word_out.valid & ~uart_rx_mac_out_ready; 
}

// TX side
// Globally visible ports / wires
// Inputs
stream(uint8_t) uart_tx_mac_word_in;
// Outputs
uint1_t uart_tx_mac_in_ready;
#pragma MAIN uart_tx_mac
//MAIN_MHZ(uart_tx_mac, UART_CLK_MHZ)
void uart_tx_mac()
{
  // Input one 8b word into serializer buffer and get eight single bits
  uint1_t word_in[UART_WORD_BITS];
  UINT_TO_BIT_ARRAY(word_in, UART_WORD_BITS, uart_tx_mac_word_in.data)
  // Ready is FEEDBACK doesnt get a value until later
  uint1_t ready_for_bit_stream;
  #pragma FEEDBACK ready_for_bit_stream
  uart_serializer_o_t ser = uart_serializer(
    word_in, 
    uart_tx_mac_word_in.valid,
    ready_for_bit_stream
  );
  uart_tx_mac_in_ready = ser.in_data_ready;
  stream(uint1_t) bit_stream;
  bit_stream.data = ser.out_data;
  bit_stream.valid = ser.out_data_valid;

  // Transmit bit stream onto output wire
  uart_tx_1b_t uart_tx_1b_out = uart_tx_1b(
    bit_stream
  );
  uart_tx = uart_tx_1b_out.output_wire;
  // Finally have FEEDBACK ready for serializer
  ready_for_bit_stream = uart_tx_1b_out.ready_for_bit_stream; 
}

/*
// Do byte level loopback test
#pragma MAIN main
void main()
{
  uart_tx_mac_word_in = uart_rx_mac_word_out;
  uart_rx_mac_out_ready = uart_tx_mac_in_ready;
}
*/