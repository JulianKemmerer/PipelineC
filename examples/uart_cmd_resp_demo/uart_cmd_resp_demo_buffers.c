// Fancy shared 'single instance' derived state machine helper functions
// Need two separate function names since need to mark each as separate single instance
// (can later make macro single both funcs have same body code)

// Command buffer func
uart_cmd_resp_buf_t uart_cmd_buf_read_write(uart_cmd_resp_t in_data, uint1_t write)
{
  static uart_cmd_resp_buf_t buf;
  uart_cmd_resp_buf_t rd; // Output read data, zeroed
  if(write)
  {
    // Write over existing entry
    // No check for overflow
    buf.cmd_resp = in_data;
    buf.valid = 1;
  }
  else
  {
    // Read buffer entry
    rd = buf;
    // Clears valid bit upon read
    buf.valid = 0;
  }
  return rd;
}
#include "uart_cmd_buf_read_write_SINGLE_INST.h"
// Helper FSM function to wait for command to arrive and read it, returning it
uart_cmd_resp_t wait_uart_cmd_read()
{
  uart_cmd_resp_buf_t cmd_buf;
  while(!cmd_buf.valid)
  {
    uart_cmd_resp_t unused_write_data;
    cmd_buf = uart_cmd_buf_read_write(unused_write_data, 0);
  }
  return cmd_buf.cmd_resp;
}

// Response buffer func
uart_cmd_resp_buf_t uart_resp_buf_read_write(uart_cmd_resp_t in_data, uint1_t write)
{
  static uart_cmd_resp_buf_t buf;
  uart_cmd_resp_buf_t rd; // Output read data, zeroed
  if(write)
  {
    // Write over existing entry
    // No check for overflow
    buf.cmd_resp = in_data;
    buf.valid = 1;
  }
  else
  {
    // Read buffer entry
    rd = buf;
    // Clears valid bit upon read
    buf.valid = 0;
  }
  return rd;
}
#include "uart_resp_buf_read_write_SINGLE_INST.h"
// Helper FSM function to wait for resp to arrive and read it, returning it
uart_cmd_resp_t wait_uart_resp_read()
{
  uart_cmd_resp_buf_t resp_buf;
  while(!resp_buf.valid)
  {
    uart_cmd_resp_t unused_write_data;
    resp_buf = uart_resp_buf_read_write(unused_write_data, 0);
  }
  return resp_buf.cmd_resp;
}



