// Uses UART message module to present globally visible async msg fifos
#pragma once
#include "wire.h"
#include "uart_msg.c"

// Globally visible port/clock crossing/fifo
uart_msg_t uart_rx_msg_fifo[1]; // As small as possible for now
#include "clock_crossing/uart_rx_msg_fifo.h"
#pragma MAIN_MHZ uart_rx_msg_fifo_module uart_rx_msg // Match freq of messages module
void uart_rx_msg_fifo_module()
{
  // Read message stream from RX module
  uart_msg_s rx_msg;
  WIRE_READ(uart_msg_s, rx_msg, uart_rx_msg_out)
  
  // Write message stream into fifo
  uart_msg_t wr_data[1];
  wr_data[0] = rx_msg.data;
  uint1_t write_en = rx_msg.valid;
  uart_rx_msg_fifo_write_t write = uart_rx_msg_fifo_WRITE_1(wr_data, write_en);
  
  // Drive ready for messages from fifo
  WIRE_WRITE(uint1_t, uart_rx_msg_out_ready, write.ready)
}

// Globally visible port/clock crossing/fifo
uart_msg_t uart_tx_msg_fifo[1]; // As small as possible for now
#include "clock_crossing/uart_tx_msg_fifo.h"
#pragma MAIN_MHZ uart_tx_msg_fifo_module uart_tx_msg // Match freq of messages module
void uart_tx_msg_fifo_module()
{
  // Read ready for input messages flag from tx msg module
  uint1_t tx_msg_ready;
  WIRE_READ(uint1_t, tx_msg_ready, uart_tx_msg_in_ready)
  
  // Read message stream from fifo if ready
  uint1_t rd_en = tx_msg_ready;
  uart_tx_msg_fifo_read_t read = uart_tx_msg_fifo_READ_1(rd_en);
  
  // Send message stream into tx msg module
  uart_msg_s tx_msg;
  tx_msg.data = read.data[0];
  tx_msg.valid = read.valid;
  WIRE_WRITE(uart_msg_s, uart_tx_msg_in, tx_msg)
}

// Helper state machines

// State machine to wait to receive valid message
// in fifo and return it when done (reading it out of fifo)
typedef struct uart_rx_msg_fifo_receiver_t
{
  uint1_t ready;
  uint1_t done;
  uart_msg_t msg;
}uart_rx_msg_fifo_receiver_t;
uart_rx_msg_fifo_receiver_t uart_rx_msg_fifo_receiver(uint1_t start)
{
  static uint1_t started;
  uart_rx_msg_fifo_receiver_t o;
  o.ready = !started;
  if(o.ready)
  {
    started = start;
  }
  
  uint1_t rd_en = started;
  uart_rx_msg_fifo_read_t read = uart_rx_msg_fifo_READ_1(rd_en);
  o.done = read.valid;
  o.msg = read.data[0];
  
  if(o.done)
  {
    started = 0;
  }
  
  return o;
}

// State machine to keep trying to write a message
// into fifo and signalling when done (having written it into fifo)
typedef struct uart_tx_msg_fifo_sender_t
{
  uint1_t ready;
  uint1_t done;
}uart_tx_msg_fifo_sender_t;
uart_tx_msg_fifo_sender_t uart_tx_msg_fifo_sender(uint1_t start, uart_msg_t msg)
{
  static uint1_t started;
  
  // Drive leds
  WIRE_WRITE(uint1_t, led3, started)
  
  uart_tx_msg_fifo_sender_t o;
  o.ready = !started;
  if(o.ready)
  {
    started = start;
  }
  
  uart_msg_t wr_data[1];
  wr_data[0] = msg;
  uint1_t wr_en = started;
  uart_tx_msg_fifo_write_t write = uart_tx_msg_fifo_WRITE_1(wr_data, wr_en);
  o.done = write.ready;
  
  if(o.done)
  {
    started = 0;
  }
  
  return o;
}
