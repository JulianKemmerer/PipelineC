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
#include "transmit_bit_SINGLE_INST.h"

void transmit_start_bit()
{
  transmit_bit(UART_START);
}
//#include "transmit_start_bit_SINGLE_INST.h" // Needed? Wanted?

void transmit_stop_bit()
{
  transmit_bit(UART_STOP);
}
//#include "transmit_stop_bit_SINGLE_INST.h" // Needed? Wanted?

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
//#include "transmit_byte_SINGLE_INST.h" // Needed? Wanted?

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
//#include "transmit_msg_SINGLE_INST.h" // Needed? Wanted?

void wait_clks(uint16_t clks)
{
  while(clks > 0)
  {
    clks -= 1;
    __clk();
  }
}

// For those who dont like the WIRE macros...
uint1_t read_uart_wire()
{
  uint1_t rv;
  WIRE_READ(uint1_t, rv, uart_data_in)
  return rv;
}

// Returns once the entire start bit period has elapsed
// (cycle after return is start of first data bit)
void receive_start_bit()
{
  // Wait for UART_IDLE
  uint1_t the_bit = !UART_IDLE;
  while(the_bit != UART_IDLE)
  {
    the_bit = read_uart_wire();
    __clk();
  }

  // Then wait for the start bit
  while(the_bit != UART_START)
  {
    the_bit = read_uart_wire();
    __clk();
  }

  // Then wait entire start bit period
  wait_clks(UART_CLKS_PER_BIT);
}
//#include "receive_start_bit_SINGLE_INST.h" // Needed? Wanted?

uint1_t receive_bit()
{
  // Just read the wire
  uint1_t the_bit = read_uart_wire();
  // And wait a full bit period so next bit is ready to receive next
  wait_clks(UART_CLKS_PER_BIT);
  return the_bit;
}
#include "receive_bit_SINGLE_INST.h"


uint8_t receive_byte()
{
  // Wait for start bit
  receive_start_bit();

  // Wait for half of bit period to align to center of data
  wait_clks(UART_CLKS_PER_BIT/2);
  
  // Loop sampling each data bit into 8b shift register
  uint8_t the_byte = 0;
  uint16_t i;
  for(i=0;i<8;i+=1)
  {
    uint1_t the_bit = receive_bit();
    // Shift buffer down to make room for next bit
    the_byte = the_byte >> 1;
    // Save bit at top of shift reg [7]
    the_byte |= ( (uint8_t)the_bit << 7 );
  }

  // Dont need to wait for stop bit
  return the_byte;
}
//#include "receive_byte_SINGLE_INST.h" // Needed? Wanted?

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
//#include "receive_msg_SINGLE_INST.h" // Needed? Wanted?

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
