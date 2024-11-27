#include "uintN_t.h"
#include "intN_t.h"
#include "uart.c" // Top level UART ports

// Globally visible port/wire names for output register
uint1_t uart_out_reg_data;
uint1_t uart_out_reg_enable;
#include "clock_crossing/uart_out_reg_data.h"
#include "clock_crossing/uart_out_reg_enable.h"

MAIN_MHZ(uart_out_reg_module, UART_CLK_MHZ)
void uart_out_reg_module()
{
  static uint1_t the_reg;
  WIRE_WRITE(uint1_t, uart_data_out, the_reg)
  uint1_t reg_data;
  uint1_t reg_enable;
  WIRE_READ(uint1_t, reg_data, uart_out_reg_data)
  WIRE_READ(uint1_t, reg_enable, uart_out_reg_enable)
  if(reg_enable)
  {
    the_reg = reg_data;
  }
}

void set_uart_output(uint1_t data)
{
  // Drive the output register for a clock cycle
  WIRE_WRITE(uint1_t, uart_out_reg_data, data)
  // Use loop to signal enable for a cycle, then clear
  // (needs to be loop to work around having two wire write instances in code
  //  PipelineC tool sees it as multiple drivers...)
  int8_t en;
  for(en=1; en>=0; en-=1)
  {
    WIRE_WRITE(uint1_t, uart_out_reg_enable, en)
    __clk();
  }
}