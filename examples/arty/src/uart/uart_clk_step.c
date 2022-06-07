#include "arrays.h"
// UART top level IO
#include "uart.c"
// Fixed size UART message buffers of N bytes
#include "uart_msg.h"

/* LOOPBACK TEST works: sudo screen /dev/ttyUSB1 115200
MAIN_MHZ(main, UART_CLK_MHZ)
void main()
{
  uint1_t data_in;
  WIRE_READ(uint1_t, data_in, uart_data_in)
  WIRE_WRITE(uint1_t, uart_data_out, data_in)
}*/

// For those who dont like the WIRE macros...
void drive_uart_wire(uint1_t the_bit)
{
  WIRE_WRITE(uint1_t, uart_data_out, the_bit)
}

// TODO 
//  Could make a UART output register stand alone "module" 
//  so its 'set once and wait' as opposed as is below 'drive constantly in while loop'
void transmit_bit(uint1_t the_bit)
{
  // Sending a bit in uart just means
  // setting logic level for a bit period 
  uint16_t clk_counter = 0;
  while(clk_counter < (UART_CLKS_PER_BIT-1))
  {
    drive_uart_wire(the_bit);
    clk_counter += 1;
    __clk();
  }
}

void transmit_byte(uint8_t the_byte)
{
  // Send start bit
  transmit_bit(UART_START);

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
  transmit_bit(UART_STOP);
}
//#include "transmit_byte_SINGLE_INST.h" // If not using msgs at highest level

void transmit_msg(uart_msg_t msg)
{
  // Setup first data byte
  uint8_t the_byte = msg.data[0];
  // Loop sending each byte
  uint16_t i;
  for(i=0;i<UART_MSG_SIZE;i+=1)
  {
    transmit_byte(the_byte);
    // Setup next byte
    ARRAY_SHIFT_DOWN(msg.data, UART_MSG_SIZE, 1)
    the_byte = msg.data[0];
  }
}
// Need to specify single instance so only one driver of uart wire at a time
// Only one "transmit_bit" instance per instance of "transmit_byte", etc
// so single instance can be marked at 'highest level abstraction' possible
#include "transmit_msg_SINGLE_INST.h"

void wait_clks(uint16_t clks)
{
  while(clks > 0)
  {
    clks -= 1;
    __clk();
  }
}
//#include "wait_clks_SINGLE_INST.h" // Wanted?

// For those who dont like the WIRE macros...
uint1_t read_uart_wire()
{
  uint1_t rv;
  WIRE_READ(uint1_t, rv, uart_data_in)
  return rv;
}

uint8_t receive_byte()
{
  // Wait for start bit transition
  // First wait for UART_IDLE
  uint1_t the_bit = !UART_IDLE;
  while(the_bit != UART_IDLE)
  {
    the_bit = read_uart_wire();
    __clk();
  }
  // Then wait for the start bit start
  while(the_bit != UART_START)
  {
    the_bit = read_uart_wire();
    __clk();
  }

  // Wait for 1.5 bit periods to align to center of first data bit
  wait_clks(UART_CLKS_PER_BIT+UART_CLKS_PER_BIT_DIV2);
  
  // Loop sampling each data bit into 8b shift register
  uint8_t the_byte = 0;
  uint16_t i;
  for(i=0;i<8;i+=1)
  {
    // Read the wire
    the_bit = read_uart_wire();
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

uart_msg_t receive_msg()
{
  uart_msg_t msg;
  // Receive the number of bytes for message
  uint16_t i;
  for(i=0;i<UART_MSG_SIZE;i+=1)
  {
    uint8_t the_byte = receive_byte();
    // Shift buffer down to make room for next byte
    ARRAY_SHIFT_DOWN(msg.data, UART_MSG_SIZE, 1)
    // Save byte at top of shift reg [UART_MSG_SIZE-1]
    msg.data[UART_MSG_SIZE-1] = the_byte;
  }
  return msg;
}
//#include "receive_msg_SINGLE_INST.h" // Wanted?

/*
// Do byte level loopback test
void main()
{
  while(1)
  {
    uint8_t the_byte = receive_byte();
    transmit_byte(the_byte);
  }
}
*/

// Use uart msg for loopback test
// Receive a uart msg, and then send it back
void main()
{
  while(1)
  {
    uart_msg_t msg = receive_msg();
    transmit_msg(msg);
  }
}

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
