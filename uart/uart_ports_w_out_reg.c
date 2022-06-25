#include "uintN_t.h"
#include "intN_t.h"
#include "uart/uart_ports.c" // Top level UART ports

// Globally visible port/wire names for output register
uint1_t uart_out_reg_data;
uint1_t uart_out_reg_enable;

MAIN_MHZ(uart_out_reg_module, UART_CLK_MHZ)
void uart_out_reg_module()
{
  static uint1_t the_reg = UART_IDLE;
  uart_data_out = the_reg;
  uint1_t reg_data = uart_out_reg_data;
  uint1_t reg_enable = uart_out_reg_enable;
  if(reg_enable)
  {
    the_reg = reg_data;
  }
}

void set_uart_out_reg_en(uint1_t en)
{
   uart_out_reg_enable = en;
}
// Single instance FSM because can only be one driver of uart_out_reg_enable
#include "set_uart_out_reg_en_SINGLE_INST.h"

void set_uart_out_reg(uint1_t data)
{
  // Drive the output register for a clock cycle
  // Set both data and enable
  uart_out_reg_data = data;
  set_uart_out_reg_en(1);
  // And then clear enable
  set_uart_out_reg_en(0);
}
// Single instance FSM because can only be one driver of uart_out_reg_data
#include "set_uart_out_reg_SINGLE_INST.h"