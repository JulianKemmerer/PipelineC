// Each main function is a clock domain
// Only one clock in the design for now 'sys_clk' @ 100MHz
#define SYS_CLK_MHZ 100.0
#pragma MAIN_MHZ sys_clk_main 100.0

// Logic to receive and transmit uart messages
#include "../uart/uart_msg.c"

// Definition of work related stuff
#include "work.h"
// Helper functions to convert uart bytes to/from 'work' inputs/outputs
// TODO gen includes all inside work_in|output_t_bytes_t.h
#include "uint8_t_array_N_t.h" 
#include "uint8_t_bytes_t.h"
#include "int16_t_bytes_t.h"
#include "work_inputs_t_bytes_t.h"
#include "work_outputs_t_bytes_t.h"

// Separate out overflow state in its own global func 
// so sys_clk_main (specifcally work()) can pipelined
uint1_t overflow_reg;
uint1_t overflow_func(uint1_t overflow_now)
{
  overflow_reg |= overflow_now;
  return overflow_reg;
}

// Make structs that wrap up the input and output ports
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


// The main function
sys_clk_main_outputs_t sys_clk_main(sys_clk_main_inputs_t inputs)
{
  sys_clk_main_outputs_t outputs;
  uint32_t i;
  
  // Receive N byte messages
  uint1_t rx_msg_ready = 1; // Assume ready and overflow detected downstream
  uart_rx_msg_o_t uart_rx_msg_output = uart_rx_msg(inputs.uart_txd_in, rx_msg_ready);
  uart_msg_s in_msg = uart_rx_msg_output.msg_out;
  
  // Convert bytes to inputs
  work_inputs_t_bytes_t input_bytes;
  for(i=0; i<sizeof(work_inputs_t); i=i+1)
  {
    input_bytes.data[i] = in_msg.data.data[i];
  }
  work_inputs_t work_inputs = bytes_to_work_inputs_t(input_bytes);
  
  // Do work on inputs, get outputs
  work_outputs_t work_outputs = work(work_inputs);
  
  // Convert output to bytes
  work_outputs_t_bytes_t output_bytes = work_outputs_t_to_bytes(work_outputs);
  uart_msg_s out_msg = UART_MSG_S_NULL();
  out_msg.valid = in_msg.valid;
  for(i=0; i<sizeof(work_outputs_t); i=i+1)
  {
    out_msg.data.data[i] = output_bytes.data[i];
  }
  
  // Transmit N byte messages  
  uart_tx_msg_o_t uart_tx_msg_output = uart_tx_msg(out_msg);
  outputs.uart_rxd_out = uart_tx_msg_output.mac_data_out;
  // Overflow detected here, transmit must always be ready for msg
  uint1_t overflow_now = out_msg.valid & !uart_tx_msg_output.msg_in_ready;
  
  // Save overflow flag
  uint1_t overflow = overflow_func(overflow_now);
  
  // Light up leds with overflow flag
  outputs.led[0] = overflow;
  outputs.led[1] = overflow;
  outputs.led[2] = overflow;
  outputs.led[3] = overflow;
  
  return outputs;
}
