// Logic to receive and transmit 1 byte UART words
// UART PHY?MAC?(de)serialize? logic
#pragma once

#include "uintN_t.h"
#include "uart.c"

// Convert framed async serial data to sync data+valid word stream
// rule of thumb name "_s" 'stream' if has .valid and .data
typedef struct uart_mac_s
{
  uart_word_t data;
  uint1_t valid;
}uart_mac_s;

// RX side
// Globally visible ports / wires
// Inputs
uint1_t uart_rx_mac_out_ready;
// Outputs
uart_mac_s uart_rx_mac_word_out;
// Volatile overflow since is not part of cycle-by-cycle signaling,
// can read by another process with latency,datapath width adjustments
volatile uint1_t uart_rx_mac_overflow;
#include "clock_crossing/uart_rx_mac_out_ready.h"
#include "clock_crossing/uart_rx_mac_word_out.h"
#include "clock_crossing/uart_rx_mac_overflow.h"

// Deserialize eight bits into one 8b byte
#include "deserializer.h"
deserializer(uart_deserializer, uint1_t, UART_WORD_BITS) 

// RX logic
typedef enum uart_rx_mac_state_t
{
  IDLE,
  WAIT_START,
  RECEIVE
}uart_rx_mac_state_t;
#pragma MAIN_MHZ uart_rx_mac uart_module // Match freq of uart module
void uart_rx_mac()
{
  // Static locals (like global vars)
  static uart_rx_mac_state_t state;
  static uart_clk_count_t clk_counter;
  static uart_bit_count_t bit_counter;
  
  // Read uart data_in input port
  uint1_t data_in;
  WIRE_READ(uint1_t, data_in, uart_data_in)
  
  // Read output ready input port
  uint1_t out_ready;
  WIRE_READ(uint1_t, out_ready, uart_rx_mac_out_ready)
  
  // Output wires
  uart_mac_s word_out;
  uint1_t overflow;

  // Sampling bits from the async serial data frame
  uint1_t data_sample = 0;
  uint1_t data_sample_valid = 0;
  
  // State machine for receiving
  if(state==IDLE)
  {
    // Wait for line to be high, idle, powered, etc
    if(data_in==UART_IDLE)
    {
      // Then wait for the start bit
      state = WAIT_START;
      clk_counter = 0;
    }
  }
  else if(state==WAIT_START)
  {
    // Wait for the start bit=0
    if(data_in==UART_START)
    {
      // Wait half a bit period to align to center of clk period
      clk_counter += 1;      
      if(clk_counter >= UART_CLKS_PER_BIT_DIV2)
      {
        // Begin loop of sampling each bit
        state = RECEIVE;
        clk_counter = 0;
        bit_counter = 0;
      }
    }
  }
  else if(state==RECEIVE)
  {
    // Count a full bit period and then sample
    clk_counter += 1;
    if(clk_counter >= UART_CLKS_PER_BIT)
    {
      // Reset counter for next bit
      clk_counter = 0;
      
      // Sample current data into deserializer
      data_sample = data_in;
      data_sample_valid = 1;
      bit_counter += 1;
      
      // Last bit of word?
      if(bit_counter==UART_WORD_BITS)
      {
        // Back to idle waiting for next word
        state = IDLE;
      }
    }
  }
  
  // Input 1 bit 8 times to get to get 1 byte out
  uart_deserializer_o_t deser = uart_deserializer(data_sample, data_sample_valid, out_ready);
  word_out.data = uart_word_from_bits(deser.out_data);
  word_out.valid = deser.out_data_valid;
  overflow = data_sample_valid & !deser.in_data_ready;
  
  // Drive output ports
  WIRE_WRITE(uart_mac_s, uart_rx_mac_word_out, word_out) //uart_rx_mac_word_out = word_out
  // Volatile, wider width overflow port // uart_rx_mac_overflow = overflow
  uart_rx_mac_overflow_write_t overflow_data;
  uint32_t i;
  for(i=0;i<uart_rx_mac_overflow_RATIO;i+=1)
  {
    overflow_data.data[i] = overflow;
  }
  uart_rx_mac_overflow_WRITE(overflow_data);
}

// TX side
// Globally visible ports / wires
// Inputs
uart_mac_s uart_tx_mac_word_in;
// Outputs
uint1_t uart_tx_mac_in_ready;
#include "clock_crossing/uart_tx_mac_word_in.h"
#include "clock_crossing/uart_tx_mac_in_ready.h"

// Slight clock differences between RX and TX sides can occur.
// Do a hacky off by one fewer clock cycles to ensure TX bandwidth
// is always slighty greater than RX bandwidth to avoid overflow
#define UART_TX_CHEAT_CYCLES 1
// Serialize one 8b byte into eight single bits
#include "serializer.h"
serializer(uart_serializer, uint1_t, UART_WORD_BITS)

// TX logic
typedef enum uart_tx_mac_state_t
{
  IDLE,
  SEND_START,
  TRANSMIT,
  SEND_STOP
}uart_tx_mac_state_t;
#pragma MAIN_MHZ uart_tx_mac uart_module // Match freq of uart module
void uart_tx_mac()
{
  // Static locals (like global vars)
  static uart_tx_mac_state_t state;
  static uart_clk_count_t clk_counter;
  static uart_bit_count_t bit_counter;
  
  // Read input port
  uart_mac_s word_in;
  WIRE_READ(uart_mac_s, word_in, uart_tx_mac_word_in)
 
  // Default no output
  uint1_t word_in_ready = 0;
  uint1_t data_out = UART_IDLE; // UART high==idle
  uint32_t i = 0;
  
  // Calculate condition for shifting buffer/next bit each bit period
  uint1_t do_next_bit_stuff = 0;
  // Transmitting
  if(state==TRANSMIT)
  {
    // And about to roll over
    if(clk_counter >= (UART_CLKS_PER_BIT-UART_TX_CHEAT_CYCLES-1)) //-1 since pre increment
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
  word_in_ready = ser.in_data_ready;
  uint1_t tx_bit = ser.out_data;
  uint1_t tx_bit_valid = ser.out_data_valid;
  
  // State machine for transmitting
  if(state==IDLE)
  {
    // Wait for valid bit(s) from serializer buffer
    if(tx_bit_valid)
    {
      // Start transmitting start bit
      state = SEND_START;
      clk_counter = 0;
    }
  }
  // Pass through single cycle low latency from IDLE to SEND_START since if()
  if(state==SEND_START)
  {
    // Output start bit for one bit period
    data_out = UART_START;
    clk_counter += 1;
    if(clk_counter >= (UART_CLKS_PER_BIT-UART_TX_CHEAT_CYCLES))
    {
      // Then move onto transmitting word bits
      state = TRANSMIT;
      clk_counter = 0;
      bit_counter = 0;
    }
  }
  else if(state==TRANSMIT)
  {
    // Output tx_bit from serializer for one bit period
    data_out = tx_bit;
    clk_counter += 1;
    if(do_next_bit_stuff)
    {
      // Reset counter for next bit
      clk_counter = 0;
      bit_counter += 1;
      // Last bit of word?
      if(bit_counter==UART_WORD_BITS)
      {
        // Send the final stop bit
        state = SEND_STOP;
        clk_counter = 0;
      }
    }
  }
  else if(state==SEND_STOP)
  {
    // Output stop bit for one bit period
    data_out = UART_STOP;
    clk_counter += 1;
    if(clk_counter>=(UART_CLKS_PER_BIT-UART_TX_CHEAT_CYCLES))
    {
      // Then back to idle
      state = IDLE;
    }
  }
  
  // Write output ports
  WIRE_WRITE(uint1_t, uart_tx_mac_in_ready, word_in_ready)
  WIRE_WRITE(uint1_t, uart_data_out, data_out)
}

