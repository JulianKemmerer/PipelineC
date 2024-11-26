// Logic to receive(deserialize) and transmit(serialize) 1 UART words
#include "uintN_t.h"
#include "arrays.h"
#include "stream/stream.h"
#include "stream/deserializer.h"
#include "stream/serializer.h"

#ifndef UART_CLK_MHZ
#define UART_CLK_MHZ 25.0
#endif
#ifndef UART_BAUD
#define UART_BAUD 115200
#endif

#define UART_CLKS_PER_SEC (UART_CLK_MHZ*1000000.0)
#define SEC_PER_UART_CLK (1.0/UART_CLKS_PER_SEC)
#define UART_WORD_BITS 8
#define uart_bit_count_t uint4_t
#define uart_word_from_bits uint1_array8_le // PipelineC built in func
#define UART_SEC_PER_BIT (1.0/(float)UART_BAUD)
#define UART_CLKS_PER_BIT_FLOAT (UART_SEC_PER_BIT/SEC_PER_UART_CLK)
#define UART_CLKS_PER_BIT ((uart_clk_count_t)UART_CLKS_PER_BIT_FLOAT)
#define UART_CLKS_PER_BIT_DIV2 ((uart_clk_count_t)(UART_CLKS_PER_BIT_FLOAT/2.0))
#define uart_clk_count_t uint16_t
#define UART_IDLE 1
#define UART_START 0
#define UART_STOP UART_IDLE

// Convert framed async serial data to sync data+valid word stream
DECL_STREAM_TYPE(uint8_t)
DECL_STREAM_TYPE(uint1_t)

// Logic to receive a UART bit stream
typedef enum uart_rx_state_t
{
  IDLE,
  WAIT_START,
  RECEIVE
}uart_rx_state_t;
typedef struct uart_rx_1b_t{
  stream(uint1_t) bit_stream;
  uint1_t overflow;
}uart_rx_1b_t;
uart_rx_1b_t uart_rx_1b(
 uint1_t input_wire, 
 uint1_t ready_for_bit_stream
){
  // Static local registers
  static uart_rx_state_t state;
  static uart_clk_count_t clk_counter;
  static uart_bit_count_t bit_counter;
  // Output wires
  uart_rx_1b_t o;
  // State machine for receiving
  if(state==IDLE)
  {
    // Wait for line to be high, idle, powered, etc
    if(input_wire==UART_IDLE)
    {
      // Then wait for the start bit
      state = WAIT_START;
      clk_counter = 0;
    }
  }
  else if(state==WAIT_START)
  {
    // Wait for the start bit=0
    if(input_wire==UART_START)
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
      
      // Output current data
      o.bit_stream.data = input_wire;
      o.bit_stream.valid = 1;
      bit_counter += 1;
      
      // Last bit of word?
      if(bit_counter==UART_WORD_BITS)
      {
        // Back to idle waiting for next word
        state = IDLE;
      }
    }
  }
  o.overflow = o.bit_stream.valid & ~ready_for_bit_stream;
  return o;
}

// Slight clock differences between RX and TX sides can occur.
// Do a hacky off by one fewer clock cycles to ensure TX bandwidth
// is always slighty greater than RX bandwidth to avoid overflow
#define UART_TX_CHEAT_CYCLES 1

typedef enum uart_tx_state_t
{
  IDLE,
  SEND_START,
  TRANSMIT,
  SEND_STOP
}uart_tx_state_t;
typedef struct uart_tx_1b_t{
  uint1_t output_wire;
  uint1_t ready_for_bit_stream;
}uart_tx_1b_t;
uart_tx_1b_t uart_tx_1b(
 stream(uint1_t) bit_stream
){
  static uart_tx_state_t state;
  static uart_clk_count_t clk_counter;
  static uart_bit_count_t bit_counter;
  uart_tx_1b_t o;
  // State machine for transmitting
  if(state==IDLE)
  {
    // Wait for valid bit(s) from serializer buffer
    o.output_wire = UART_IDLE;
    if(bit_stream.valid)
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
    o.output_wire = UART_START;
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
    // Output bit from serializer for one bit period
    o.output_wire = bit_stream.data;
    clk_counter += 1;
    if(clk_counter >= (UART_CLKS_PER_BIT-UART_TX_CHEAT_CYCLES-1))
    {
      // signal ready done with currenty bit now
      // (next bit will be available next cycle)
      o.ready_for_bit_stream = 1;
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
    o.output_wire = UART_STOP;
    clk_counter += 1;
    if(clk_counter>=(UART_CLKS_PER_BIT-UART_TX_CHEAT_CYCLES))
    {
      // Then back to idle
      state = IDLE;
    }
  }
  return o;
}

// Deserialize eight bits into one 8b byte
deserializer(uart_deserializer, uint1_t, UART_WORD_BITS)

// Serialize one 8b byte into eight single bits
serializer(uart_serializer, uint1_t, UART_WORD_BITS)
