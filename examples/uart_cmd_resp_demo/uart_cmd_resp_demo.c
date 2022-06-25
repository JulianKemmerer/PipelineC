// Not fsm style regular HDL version

// UART hooks for receiving and transmitting bytes
// (alternative advanced FSM style functionality in uart_mac_fsm_style.c
//  TODO maybe try using FSM style for UART MAC, but non-FSM style below?)
#include "uart/uart_mac.c"
// LED hooks for output ports
#include "leds/leds_port.c"
// Helper macros for de/serializing bits/bytes/structs
#include "stream/deserializer.h"
#include "stream/serializer.h"

// Include types like command+response uart_cmd_resp_t
#include "uart_cmd_resp_demo.h"
// Auto gen header with to-from bytes conversion funcs (for PipelineC code)
#include "uart_cmd_resp_t_bytes_t.h"

// Declare a module to deserialize UART 1 byte at a time to command struct
type_byte_deserializer(cmd_deser, 1, uart_cmd_resp_t)

// Declare globally visible wires for reading cmd buffer via valid+ready handshake
uart_cmd_resp_t uart_cmd_out;
uint1_t uart_cmd_out_valid;
uint1_t uart_cmd_out_ready;

// Top level module that deserializes UART bytes to commands
// (connects above declared deserializer to UART ports)
#pragma MAIN uart_cmd_deser
void uart_cmd_deser()
{
  // Read inputs from UART receive module
  uart_mac_s rx_stream = uart_rx_mac_word_out;
  // Read inputs from consumer of command, if ready for cmd flag
  uint1_t cmd_out_ready = uart_cmd_out_ready;
  
  // Deserialize byte stream to type
  uint8_t in_bytes[1] = {rx_stream.data}; // 1 byte at a time
  cmd_deser_t to_type = cmd_deser(in_bytes, rx_stream.valid, cmd_out_ready);

  // Write outputs to UART receive module
  // Ready for UART RX byte, if deserializer is ready
  uart_rx_mac_out_ready = to_type.in_data_ready;
  // Write outputs to consumer of commmand, command and valid flag
  uart_cmd_out = to_type.data;
  uart_cmd_out_valid = to_type.valid;
}

// Declare a module to serialize response struct over UART 1 byte at a time
type_byte_serializer(resp_ser, uart_cmd_resp_t, 1)

// Declare globally visible wires for writing response buffer via valid+ready handshake
uart_cmd_resp_t uart_resp_in;
uint1_t uart_resp_in_valid;
uint1_t uart_resp_in_ready;

// Top level module that serializes response struct to UART bytes
// (connects above declared serializer to UART ports)
#pragma MAIN uart_resp_ser
void uart_resp_ser()
{
  // Read inputs from UART transmit module, if UART transmit is ready for serialized byte
  uint1_t resp_byte_out_ready = uart_tx_mac_in_ready;
  // Read inputs from producer of response, response + valid flag
  uart_cmd_resp_t resp_in = uart_resp_in;
  uint1_t resp_in_valid = uart_resp_in_valid;

  // Serialize response struct to byte stream
  resp_ser_t to_bytes = resp_ser(resp_in, resp_in_valid, resp_byte_out_ready);

  // Write outputs to UART transmit module, data and valid
  uart_mac_s tx_stream;
  tx_stream.data = to_bytes.out_data[0]; // 1 byte at a time
  tx_stream.valid = to_bytes.valid;
  uart_tx_mac_word_in = tx_stream;
  // Write outputs to producer of response, ready for response input
  uart_resp_in_ready = to_bytes.in_data_ready;
}

// Top level module written as state machine that
// waits for commands to be received, executes them, produces responses
// (one command in flight at a time)
typedef enum bus_transactor_state_t{
  WAIT_FOR_CMD,
  EXECUTE_CMD,
  SEND_RESP,
} bus_transactor_state_t;
#pragma MAIN bus_transactor
void bus_transactor()
{
  // Read inputs from command deserializer
  uart_cmd_resp_t cmd_in = uart_cmd_out;
  uint1_t cmd_in_valid = uart_cmd_out_valid;
  // Read inputs from response serializer
  uint1_t resp_out_ready = uart_resp_in_ready;

  // Internal signals
  // Outputs to command deserializer
  uint1_t cmd_in_ready; // Default zero, not reading command
  // Outputs to response serializer
  uart_cmd_resp_t resp_out; // Default all zeros response
  uint1_t resp_out_valid; // Default zero, not writing response

  // The demo state machine just for LEDs (static registers)
  static bus_transactor_state_t state;
  static uart_cmd_resp_t cmd_resp_buf;
  static uint4_t leds_reg;
  if(state==WAIT_FOR_CMD)
  {
    // Signal ready for/reading command from buffer
    cmd_in_ready = 1;
    // Wait for valid command to be received, waiting in buffer
    if(cmd_in_valid)
    {
      // Save cmd in buffer
      cmd_resp_buf = cmd_in;
      // Then execute it
      state = EXECUTE_CMD;
    }
  }
  else if(state==EXECUTE_CMD)
  {
    // Default zeros response for bad addr/cmd
    uart_cmd_resp_t resp;
    // Temp demo hardcoded for LEDs
    if(cmd_resp_buf.addr==LEDS_ADDR)
    {
      if(cmd_resp_buf.cmd==WRITE_CMD)
      {
        // Write to LEDs
        leds_reg = cmd_resp_buf.data;
        resp = cmd_resp_buf;
      }
      else if(cmd_in.cmd==READ_CMD)
      {
        // Read from LEDs
        cmd_resp_buf.data = leds_reg;
        resp = cmd_resp_buf;
      }
    }
    // Send response next
    cmd_resp_buf = resp;
    state = SEND_RESP;
  }
  else if(state==SEND_RESP)
  {
    // Signal having valid response to send
    resp_out = cmd_resp_buf;
    resp_out_valid = 1;
    // Wait for ready from serializer
    if(resp_out_ready)
    {
      // Before waiting to receive next command
      state = WAIT_FOR_CMD;
    }
  }

  // Write outputs to command deserializer
  uart_cmd_out_ready = cmd_in_ready;
  // Write outputs to response serializer
  uart_resp_in = resp_out;
  uart_resp_in_valid = resp_out_valid;
  // Write outputs to LEDs
  leds = leds_reg;
}