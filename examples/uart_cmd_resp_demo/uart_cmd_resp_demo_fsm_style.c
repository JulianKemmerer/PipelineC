
// Helper macros for arrays
#include "arrays.h"
// UART hooks for receiving and transmitting bytes
// (alternative hdl-style functionality in uart_mac.c)
#include "uart/uart_mac_fsm_style.c" 
// LED hooks for output regs w helper funcs
#include "leds/leds_port_w_out_reg.c" 

// Include types like command+response uart_cmd_resp_t
#include "uart_cmd_resp_demo.h"
// Auto gen header with to-from bytes conversion funcs (for PipelineC code)
#include "uart_cmd_resp_t_bytes_t.h"

// As opposed to FIFOs for now, have single cmd/resp buffers
// one for receive, one for transmit 
typedef struct uart_cmd_resp_buf_t{
    uart_cmd_resp_t cmd_resp;
    uint1_t valid;
} uart_cmd_resp_buf_t;
// Allow UART logic and demo 'bus_transactor' to share buffers
// Defines the buffer and helper functions like 'uart_cmd_buf_read_write'
// and a few others that are sorta verbose to have here
#include "uart_cmd_resp_demo_buffers.c"

// Top level FSM that deserializes UART bytes to commands, writes to shared cmd buffer
void uart_cmd_deser()
{
  while(1)
  {
    // Receive bytes in loop
    uart_cmd_resp_t_bytes_t cmd_bytes;
    uint16_t byte_count = 0;
    while(byte_count < uart_cmd_resp_t_SIZE)
    {
      uint8_t the_byte = receive_byte();
      byte_count += 1;
      // Shift buffer down to make room for next byte
      ARRAY_SHIFT_DOWN(cmd_bytes.data, uart_cmd_resp_t_SIZE, 1)
      // Save byte at top of shift reg [UART_MSG_SIZE-1]
      cmd_bytes.data[uart_cmd_resp_t_SIZE-1] = the_byte;  
    }
    // Cast bytes to cmd
    uart_cmd_resp_t cmd = bytes_to_uart_cmd_resp_t(cmd_bytes);
    // Write to shared buffer (w/ helper func)
    uart_cmd_buf_read_write(cmd, 1);
  }
}

// Top level FSM that reads from shared response buffer and serializes to UART bytes
void uart_resp_ser()
{
  while(1)
  {
    // Read from shared buffer (w/ helper func)
    uart_cmd_resp_t resp = wait_uart_resp_read();
    // Serialize response to bytes
    uart_cmd_resp_t_bytes_t resp_bytes = uart_cmd_resp_t_to_bytes(resp);
    // Setup first data byte
    uint8_t the_byte = resp_bytes.data[0];
    uint16_t byte_count = 0;
    while(byte_count < uart_cmd_resp_t_SIZE)
    {
      // Transmit byte
      transmit_byte(the_byte);
      byte_count += 1;
      // Setup next byte
      ARRAY_SHIFT_DOWN(resp_bytes.data, uart_cmd_resp_t_SIZE, 1)
      the_byte = resp_bytes.data[0];
    }
  }
}

// LEDs ~controller helper FSM
uart_cmd_resp_t leds_execute_cmd(uart_cmd_resp_t cmd)
{
  uart_cmd_resp_t resp; // Zeroed out
  if(cmd.cmd == READ_CMD)
  {
    resp = cmd;
    resp.data = get_leds_out_reg();
  }
  else if(cmd.cmd == WRITE_CMD)
  {
    resp = cmd;
    set_leds_out_reg(cmd.data);
  }
  return resp;
}

// Bus ~address decoder helper FSM
uart_cmd_resp_t execute_bus_cmd(uart_cmd_resp_t cmd)
{
  uart_cmd_resp_t resp;
  if(cmd.addr == LEDS_ADDR)
  {
    resp = leds_execute_cmd(cmd);
  }
  return resp;
}

// Top level FSM that waits for commands to be received, executes them, transmits responses
// (sequential, FSM style, one command in flight at a time)
void bus_transactor()
{
  while(1)
  {
    // Wait for command in receive buffer (w/ helper func)
    uart_cmd_resp_t cmd = wait_uart_cmd_read();

    // Execute command, produce response
    uart_cmd_resp_t resp = execute_bus_cmd(cmd);

    // Write resp into transmit buffer (w/ helper func)
    uart_resp_buf_read_write(resp, 1);
  }
}

// All the verbose extra stuff needed for using
// experimental FSM style functions as top level MAIN, etc
#include "uart_cmd_resp_demo_fsm_style_wrappers.c"