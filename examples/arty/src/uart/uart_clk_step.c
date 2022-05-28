// UART top level IO
#include "uart.c"
#include "arrays.h"

// DO like bit banged UART 
// TX first
// Then RX

// Them build wrapper functions around bit bang hack

// Then break into two 
// 3 state machines
// RX side prodcuing words, middle FSM doing stuff (loopback), TX side sending words
/*
avoid user needing to count clocks (on mico need asm knowledge)
instead make system clock based wait functions
wait for n clock 
*/
// Not sure FSMs are perfectly clock accurte as eneded
// Write as if then
// Do tx and sim it
// DO rx and sim it attached ot tx

// Function calls sorta like sub state of orig uart mac

// Non blocking, transmit always can occur immediately for UART
void transmit_bit(uint1_t the_bit)
{
  // Sending a bit in uart just means
  // setting logic level for a bit period
  uint16_t clk_counter = 0;
  while(clk_counter < (UART_CLKS_PER_BIT-1))
  {
    WIRE_WRITE(uint1_t, uart_data_out, the_bit)
    clk_counter += 1;
    __clk();
  }
}
#include "transmit_bit_SINGLE_INST.h"

void transmit_start_bit()
{
  transmit_bit(UART_START);
}
//#include "transmit_start_bit_SINGLE_INST.h"

void transmit_stop_bit()
{
  transmit_bit(UART_STOP);
}
//#include "transmit_stop_bit_SINGLE_INST.h"

void transmit_byte(uint8_t the_byte)
{
  // Send start bit
  transmit_start_bit();

  // Setup first data bit
  uint1_t the_bit = the_byte; // Drops msbs

  // Loop sending each data bit
  uint16_t i;
  for(i=0;i<8;i+=1)
  {
    transmit_bit(the_bit);
    // Setup next bit
    the_byte = the_byte >> 1;
    the_bit = the_byte;
  }

  // Send stop bit
  transmit_stop_bit();
}
//#include "transmit_byte_SINGLE_INST.h"

#define TEXT_BUFFER_SIZE 16
void transmit_text(char text[TEXT_BUFFER_SIZE], uint16_t len)
{
  // Setup first data byte
  uint8_t the_byte = text[0];
  // Loop sending each byte
  uint16_t i;
  for(i=0;i<len;i+=1)
  {
    transmit_byte(the_byte);
    // Setup next byte
    ARRAY_SHIFT_DOWN(text, TEXT_BUFFER_SIZE, 1)
    the_byte = text[0];
  }
}

// Main func driving test that sends hello world over and over
void main()
{
  // Text to send
  #define TEXT "Hello World!\n"
  // Send repeatedly
  while(1)
  {
    transmit_text(TEXT, strlen(TEXT));
  }
}

/*UART TX being 101010 etc for easy debug
void main()
{
  while(1)
  {
    transmit_byte(0b01010101);
  }
}*//*
add wave -position end  sim:/top/clk_25p0
add wave -position end  sim:/top/uart_module_return_output(0)
force -freeze sim:/top/clk_25p0 1 0, 0 {50 ps} -r 100
*/

// Derived fsm from main
#include "main_FSM.h"
// Wrap up main FSM as top level
MAIN_MHZ(main_wrapper, UART_CLK_MHZ) // Use uart clock for main
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}

/* LOOPBACK TEST works: sudo screen /dev/ttyUSB1 115200
MAIN_MHZ(main, UART_CLK_MHZ)
void main()
{
  uint1_t data_in;
  WIRE_READ(uint1_t, data_in, uart_data_in)
  WIRE_WRITE(uint1_t, uart_data_out, data_in)
}*/