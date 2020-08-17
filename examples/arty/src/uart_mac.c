// Logic to receive and transmit 1 byte UART words
// UART PHY?MAC?(de)serialize? logic
#pragma once

#include "uintN_t.h"

#define UART_BAUD 115200
#define UART_WORD_BITS 8
#define uart_word_t uint8_t
#define uart_bit_count_t uint4_t
#define uart_word_from_bits uint1_array8_le // PipelineC built in func
#define UART_SEC_PER_BIT (1.0/UART_BAUD)
#define UART_CLKS_PER_BIT_FLOAT (UART_SEC_PER_BIT/SEC_PER_CLK)
#define UART_CLKS_PER_BIT ((uart_clk_count_t)UART_CLKS_PER_BIT_FLOAT)
#define UART_CLKS_PER_BIT_DIV2 ((uart_clk_count_t)(UART_CLKS_PER_BIT_FLOAT/2.0))
#define uart_clk_count_t uint16_t
#define UART_IDLE 1
#define UART_START 0
#define UART_STOP UART_IDLE

// Simple serdes logic
#include "deserializer.c"
deserializer(uart_deserializer, uint1_t, UART_WORD_BITS)  
#include "serializer.c"
serializer(uart_serializer, uint1_t, UART_WORD_BITS)

// Convert framed async serial data to sync data+valid word stream
// rule of thumb name "_s" 'stream' if has .valid and .data
typedef struct uart_mac_s
{
  uart_word_t data;
  uint1_t valid;
}uart_mac_s;

// RX side
// Global regs
typedef enum uart_rx_mac_state_t
{
  IDLE,
  WAIT_START,
  RECEIVE
}uart_rx_mac_state_t;
uart_rx_mac_state_t uart_rx_mac_state;
uart_clk_count_t uart_rx_clk_counter;
uart_bit_count_t uart_rx_bit_counter;
// Output type
typedef struct uart_rx_mac_o_t
{
  uart_mac_s word_out;
  uint1_t overflow;
}uart_rx_mac_o_t;
// RX logic
uart_rx_mac_o_t uart_rx_mac(uint1_t data_in, uint1_t out_ready)
{
  uart_rx_mac_o_t output;

  // Sampling bits from the async serial data frame
  uint1_t data_sample = 0;
  uint1_t data_sample_valid = 0;
  
  // State machine for receiving
  if(uart_rx_mac_state==IDLE)
  {
    // Wait for line to be high, idle, powered, etc
    if(data_in==UART_IDLE)
    {
      // Then wait for the start bit
      uart_rx_mac_state = WAIT_START;
      uart_rx_clk_counter = 0;
    }
  }
  else if(uart_rx_mac_state==WAIT_START)
  {
    // Wait for the start bit=0
    if(data_in==UART_START)
    {
      // Wait half a bit period to align to center of clk period
      uart_rx_clk_counter += 1;      
      if(uart_rx_clk_counter >= UART_CLKS_PER_BIT_DIV2)
      {
        // Begin loop of sampling each bit
        uart_rx_mac_state = RECEIVE;
        uart_rx_clk_counter = 0;
        uart_rx_bit_counter = 0;
      }
    }
  }
  else if(uart_rx_mac_state==RECEIVE)
  {
    // Count a full bit period and then sample
    uart_rx_clk_counter += 1;
    if(uart_rx_clk_counter >= UART_CLKS_PER_BIT)
    {
      // Reset counter for next bit
      uart_rx_clk_counter = 0;
      
      // Sample current data into deserializer
      data_sample = data_in;
      data_sample_valid = 1;
      uart_rx_bit_counter += 1;
      
      // Last bit of word?
      if(uart_rx_bit_counter==UART_WORD_BITS)
      {
        // Back to idle waiting for next word
        uart_rx_mac_state = IDLE;
      }
    }
  }
  
  // Input 1 bit 8 times to get to get 1 byte out
  uart_deserializer_o_t deser = uart_deserializer(data_sample, data_sample_valid, out_ready);
  output.word_out.data = uart_word_from_bits(deser.out_data);
  output.word_out.valid = deser.out_data_valid;
  output.overflow = deser.overflow;
  
  return output;
}

// TX side
// Slight clock differences between RX and TX sides can occur.
// Do a hacky off by one fewer clock cycles to ensure TX bandwidth
// is always slighty greater than RX bandwidth to avoid overflow
#define TX_CHEAT_CYCLES 1
// Global regs
typedef enum uart_tx_mac_state_t
{
  IDLE,
  SEND_START,
  TRANSMIT,
  SEND_STOP
}uart_tx_mac_state_t;
uart_tx_mac_state_t uart_tx_mac_state;
uart_clk_count_t uart_tx_clk_counter;
uart_bit_count_t uart_tx_bit_counter;
// Output type
typedef struct uart_tx_mac_o_t
{
  uint1_t word_in_ready;
  uint1_t data_out;
  uint1_t overflow;
}uart_tx_mac_o_t;
// TX logic
uart_tx_mac_o_t uart_tx_mac(uart_mac_s word_in)
{
  // Default no output
  uart_tx_mac_o_t output;
  output.word_in_ready = 0;
  output.data_out = UART_IDLE; // UART high==idle
  uint32_t i = 0;
  
  // Calculate condition for shifting buffer/next bit each bit period
  uint1_t do_next_bit_stuff = 0;
  // Transmitting
  if(uart_tx_mac_state==TRANSMIT)
  {
    // And about to roll over
    if(uart_tx_clk_counter >= (UART_CLKS_PER_BIT-TX_CHEAT_CYCLES-1)) //-1 since pre increment
    {
      do_next_bit_stuff = 1;
    }
  }
  
  // Input one 8b word into serializer buffer and get eight single bits
  uint1_t ser_out_data_ready = do_next_bit_stuff;
  // Hacky loop to get bits from uint8_t 
  uint1_t ser_in_data[UART_WORD_BITS];
  for(i=0;i<UART_WORD_BITS;i=i+1)
  {
    ser_in_data[i] = word_in.data >> i;
  }
  uart_serializer_o_t ser = uart_serializer(ser_in_data, word_in.valid, ser_out_data_ready);
  output.word_in_ready = ser.in_data_ready;
  output.overflow = ser.overflow;
  uint1_t tx_bit = ser.out_data;
  uint1_t tx_bit_valid = ser.out_data_valid;
  
  // State machine for transmitting
  if(uart_tx_mac_state==IDLE)
  {
    // Wait for valid bit(s) from serializer buffer
    if(tx_bit_valid)
    {
      // Start transmitting start bit
      uart_tx_mac_state = SEND_START;
      uart_tx_clk_counter = 0;
    }
  }
  // Pass through single cycle low latency from IDLE to SEND_START since if()
  if(uart_tx_mac_state==SEND_START)
  {
    // Output start bit for one bit period
    output.data_out = UART_START;
    uart_tx_clk_counter += 1;
    if(uart_tx_clk_counter >= (UART_CLKS_PER_BIT-TX_CHEAT_CYCLES))
    {
      // Then move onto transmitting word bits
      uart_tx_mac_state = TRANSMIT;
      uart_tx_clk_counter = 0;
      uart_tx_bit_counter = 0;
    }
  }
  else if(uart_tx_mac_state==TRANSMIT)
  {
    // Output tx_bit from serializer for one bit period
    output.data_out = tx_bit;
    uart_tx_clk_counter += 1;
    if(do_next_bit_stuff)
    {
      // Reset counter for next bit
      uart_tx_clk_counter = 0;
      uart_tx_bit_counter += 1;
      // Last bit of word?
      if(uart_tx_bit_counter==UART_WORD_BITS)
      {
        // Send the final stop bit
        uart_tx_mac_state = SEND_STOP;
        uart_tx_clk_counter = 0;
      }
    }
  }
  else if(uart_tx_mac_state==SEND_STOP)
  {
    // Output stop bit for one bit period
    output.data_out = UART_STOP;
    uart_tx_clk_counter += 1;
    if(uart_tx_clk_counter>=(UART_CLKS_PER_BIT-TX_CHEAT_CYCLES))
    {
      // Then back to idle
      uart_tx_mac_state = IDLE;
    }
  }
  
  return output;
}

