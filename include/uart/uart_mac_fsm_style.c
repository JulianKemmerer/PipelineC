#include "arrays.h"
// UART top level IO
#include "uart_ports_w_out_reg.c"

// Helper func to wait n clock cycles
void wait_clks(uint16_t clks)
{
  while(clks > 0)
  {
    clks -= 1;
    __clk();
  }
}
//#include "wait_clks_SINGLE_INST.h" // Wanted?

void transmit_byte(uint8_t the_byte)
{
  // Send start bit
  set_uart_out_reg(UART_START);
  wait_clks(UART_CLKS_PER_BIT);

  // Setup first data bit
  uint1_t the_bit = the_byte; // Drops msbs

  // Loop sending each data bit
  uint16_t i;
  for(i=0;i<8;i+=1)
  {
    // Transmit bit
    set_uart_out_reg(the_bit);
    wait_clks(UART_CLKS_PER_BIT);
    // Setup next bit
    the_byte = the_byte >> 1;
    the_bit = the_byte;
  }

  // Send stop bit
  set_uart_out_reg(UART_STOP);
  wait_clks(UART_CLKS_PER_BIT);
}
#include "transmit_byte_SINGLE_INST.h"

uint8_t receive_byte()
{
  // Wait for start bit transition
  // First wait for UART_IDLE
  uint1_t the_bit = !UART_IDLE;
  while(the_bit != UART_IDLE)
  {
    the_bit = get_uart_input();
  }
  // Then wait for the start bit start
  while(the_bit != UART_START)
  {
    the_bit = get_uart_input();
  }

  // Wait for 1.5 bit periods to align to center of first data bit
  wait_clks(UART_CLKS_PER_BIT+UART_CLKS_PER_BIT_DIV2);
  
  // Loop sampling each data bit into 8b shift register
  uint8_t the_byte = 0;
  uint16_t i;
  for(i=0;i<8;i+=1)
  {
    // Read the wire
    the_bit = get_uart_input();
    // Shift buffer down to make room for next bit
    the_byte = the_byte >> 1;
    // Save sampled bit at top of shift reg [7]
    the_byte |= ( (uint8_t)the_bit << 7 );
    // And wait a full bit period so next bit is ready to receive next
    wait_clks(UART_CLKS_PER_BIT);
  }

  // Dont need to wait for stop bit
  return the_byte;
}
//#include "receive_byte_SINGLE_INST.h" // Wanted?


// Do byte level loopback test
// sudo screen /dev/ttyUSB1 115200
void main()
{
  while(1)
  {
    uint8_t the_byte = receive_byte();
    transmit_byte(the_byte);
  }
}
// Derived fsm from main
#include "main_FSM.h"
// Wrap up main FSM as top level
#pragma MAIN main_wrapper
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}