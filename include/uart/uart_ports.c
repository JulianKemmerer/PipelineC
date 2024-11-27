// Top level UART ports

#include "uintN_t.h"
#include "compiler.h"
#include "cdc.h"

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

// Globally visible port/wire names
uint1_t uart_data_in;
uint1_t uart_data_out;

// Delcare as top level module io and connect to internal wires
MAIN_MHZ(uart_module,UART_CLK_MHZ)

uint1_t uart_module(uint1_t data_in)
{
  // Double register async input signal
  uint1_t data_in_registered;
  CDC2(uint1_t, in_cdc, data_in_registered, data_in)
  
  // Connect to ports  
  uart_data_in = data_in_registered;
  uint1_t data_out = uart_data_out;
  return data_out;
}

// TODO delete
uint1_t read_uart_input_wire()
{
  uint1_t rv = uart_data_in;
  return rv;
}

uint1_t get_uart_input()
{
  return read_uart_input_wire();
}
// FSM because using "get" to mean fsm style
#include "get_uart_input_FSM.h"