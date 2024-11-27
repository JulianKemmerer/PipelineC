
// Expose the uart message clock crossing wires/ async fifo functions/modules as globally visible wires
#pragma once
#include "wire.h"
#include "uart_msg_fifos.c"

// RX Globally visible ports
// Inputs
uint1_t uart_rx_msg_fifo_read_en; 
// Outputs 
uart_msg_s uart_rx_msg_fifo_msg;
#include "clock_crossing/uart_rx_msg_fifo_read_en.h"
#include "clock_crossing/uart_rx_msg_fifo_msg.h"
#pragma MAIN uart_rx_msg_fifo_wires_module
void uart_rx_msg_fifo_wires_module()
{
  // Read inputs
  uint1_t rd_en;
  WIRE_READ(uint1_t, rd_en, uart_rx_msg_fifo_read_en)
  
  // The fifo function/module to be wrapped
  uart_rx_msg_fifo_read_t read = uart_rx_msg_fifo_READ_1(rd_en);
  
  // Drive outputs
  uart_msg_s out_msg;
  out_msg.data = read.data[0];
  out_msg.valid = read.valid;
  WIRE_WRITE(uart_msg_s, uart_rx_msg_fifo_msg, out_msg)
}

// TX Globally visible ports
// Inputs
uart_msg_s uart_tx_msg_fifo_msg;
// Outputs 
uint1_t uart_tx_msg_fifo_ready; 
#include "clock_crossing/uart_tx_msg_fifo_msg.h"
#include "clock_crossing/uart_tx_msg_fifo_ready.h"
#pragma MAIN uart_tx_msg_fifo_wires_module
void uart_tx_msg_fifo_wires_module()
{
  // Read inputs
  uart_msg_s in_msg;
  WIRE_READ(uart_msg_s, in_msg, uart_tx_msg_fifo_msg)
  
  // The fifo function/module to be wrapped
  uart_msg_t wr_data[1];
  wr_data[0] = in_msg.data;
  uint1_t wr_en = in_msg.valid;
  uart_tx_msg_fifo_write_t write = uart_tx_msg_fifo_WRITE_1(wr_data, wr_en);
  
  // Drive outputs
  WIRE_WRITE(uart_msg_s, uart_tx_msg_fifo_ready, write.ready)
}
