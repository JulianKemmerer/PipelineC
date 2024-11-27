// Loopback UART with just enough buffering
// as to never overflow with balanced I/O bandwidth

#include "uintN_t.h"

// Each main function is a clock domain
// Only one clock in the design for now 'sys_clk' @ 100MHz
#define SYS_CLK_MHZ 25.0
#define CLKS_PER_SEC (SYS_CLK_MHZ*1000000.0)
#define SEC_PER_CLK (1.0/CLKS_PER_SEC)
_Pragma("MAIN_MHZ sys_clk_main 25.0")
_Pragma("PART xc7a35ticsg324-1l") // xc7a35ticsg324-1l = Arty, xcvu9p-flgb2104-2-i = AWS F1

// UART PHY?MAC?(de)serialize? logic
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
uint1_t uart_rx_bit_buffer[UART_WORD_BITS];
// RX logic
uart_mac_s uart_rx_mac(uint1_t data_in)
{
  // Default no output
  uart_mac_s output;
  output.data = 0;
  output.valid = 0;
  
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
      
      // Shift bit buffer to make room for incoming bit
      uint32_t i;
      for(i=0;i<(UART_WORD_BITS-1);i=i+1)
      {
        uart_rx_bit_buffer[i] = uart_rx_bit_buffer[i+1];
      }
      
      // Sample current bit into back of shift buffer
      uart_rx_bit_buffer[UART_WORD_BITS-1] = data_in;
      uart_rx_bit_counter += 1;
      
      // Last bit of word?
      if(uart_rx_bit_counter==UART_WORD_BITS)
      {
        // Output the full valid word
        output.data = uart_word_from_bits(uart_rx_bit_buffer);
        output.valid = 1;
        // Back to idle waiting for next word
        uart_rx_mac_state = IDLE;
      }
    }
  }
  
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
uart_mac_s uart_tx_word_in_buffer;
uint1_t uart_tx_bit_buffer[UART_WORD_BITS];
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
  
  // Ready for an incoming word to send
  // if dont have valid word_in already (i.e. input buffer empty)
  output.word_in_ready = !uart_tx_word_in_buffer.valid;
  output.overflow = !output.word_in_ready & word_in.valid;
  // Input registers
  if(output.word_in_ready)
  {
    uart_tx_word_in_buffer = word_in;
  }
  
  // State machine for transmitting
  if(uart_tx_mac_state==IDLE)
  {
    // Wait for valid bits in input buffer
    if(uart_tx_word_in_buffer.valid)
    {
      // Save the bits of the word into shift buffer
      for(i=0;i<UART_WORD_BITS;i=i+1)
      {
        uart_tx_bit_buffer[i] = uart_tx_word_in_buffer.data >> i;
      }
      // Start transmitting start bit
      uart_tx_mac_state = SEND_START;
      uart_tx_clk_counter = 0;
      // No longer need data in input buffer
      uart_tx_word_in_buffer.valid = 0;
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
    // Output from front of shift buffer for one bit period
    output.data_out = uart_tx_bit_buffer[0];
    uart_tx_clk_counter += 1;
    if(uart_tx_clk_counter >= (UART_CLKS_PER_BIT-TX_CHEAT_CYCLES))
    {
      // Reset counter for next bit
      uart_tx_clk_counter = 0;
      
      // Shift bit buffer to bring next bit to front
      for(i=0;i<(UART_WORD_BITS-1);i=i+1)
      {
        uart_tx_bit_buffer[i] = uart_tx_bit_buffer[i+1];
      }
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

// Make structs that wrap up the inputs and outputs
typedef struct sys_clk_main_inputs_t
{
  // UART Input
	uint1_t uart_txd_in;
} sys_clk_main_inputs_t;
typedef struct sys_clk_main_outputs_t
{
  // UART Output
	uint1_t uart_rxd_out;
  // LEDs
	uint1_t led[4];
} sys_clk_main_outputs_t;

// Sticky save overflow bit
uint1_t overflow;
// Break path from rx->tx in one clock by having buffer reg
uart_mac_s rx_word_buffer;

// The sys_clk_main function
sys_clk_main_outputs_t sys_clk_main(sys_clk_main_inputs_t inputs)
{
  // Loopback RX to TX without connecting backwards facing flow control/ready
  uart_mac_s rx_word = uart_rx_mac(inputs.uart_txd_in);
  uart_tx_mac_o_t uart_tx_mac_output = uart_tx_mac(rx_word_buffer);
  // Break path from rx->tx in one clock by having buffer reg
  rx_word_buffer = rx_word;
  sys_clk_main_outputs_t outputs;
  outputs.uart_rxd_out = uart_tx_mac_output.data_out;
  
  // Light up all four leds if overflow occurs
  overflow = overflow | uart_tx_mac_output.overflow; // Sticky
  outputs.led[0] = overflow;
  outputs.led[1] = overflow;
  outputs.led[2] = overflow;
  outputs.led[3] = overflow;
  
  return outputs;
}
