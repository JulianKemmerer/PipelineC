// Loopback UART after buffering a 'message' of N bytes

#include "compiler.h" // MAIN_MHZ macro

// Logic to receive and transmit uart messages
#include "uart_msg.c"

// Each main function is a clock domain, use the UART clock for main
MAIN_MHZ(sys_clk_main, UART_CLK_MHZ) // helper pragma macro
_Pragma("PART xc7a35ticsg324-1l") // xc7a35ticsg324-1l = Arty, xcvu9p-flgb2104-2-i = AWS F1

// Make structs that wrap up the inputs and outputs
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

// Sticky save overflow bit
uint1_t overflow;

// 'Clock crossing' (just a wire in this case) used for backward flowing flow control signal
uint1_t uart_tx_ready; // Flow control (tx only, cant push back on rx for now)
#include "uint1_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "uart_tx_ready_clock_crossing.h"

// The main function
sys_clk_main_outputs_t sys_clk_main(sys_clk_main_inputs_t inputs)
{
  // Loopback RX to TX
  
  // Read flow control 'clock crossing'/'feedback' coming back into this func
  uint1_t_array_1_t tx_readys_in = uart_tx_ready_READ();
  uint1_t tx_ready_in = tx_readys_in.data[0];
  
  // Receive N byte messages
  uart_rx_msg_o_t uart_rx_msg_output = uart_rx_msg(inputs.uart_txd_in, tx_ready_in);
  // Transmit N byte messages  
  uart_tx_msg_o_t uart_tx_msg_output = uart_tx_msg(uart_rx_msg_output.msg_out);

  // Sent transmit flow control signal out and back into this func
  uint1_t tx_ready_out = uart_tx_msg_output.msg_in_ready;
  uint1_t_array_1_t tx_readys_out;
  tx_readys_out.data[0] = tx_ready_out;
  uart_tx_ready_WRITE(tx_readys_out);
  
  // Drive outputs
  sys_clk_main_outputs_t outputs;
  outputs.uart_rxd_out = uart_tx_msg_output.mac_data_out;
  
  // Light up leds if overflow occurs
  overflow |= uart_rx_msg_output.overflow;
  outputs.led[0] = overflow;
  outputs.led[1] = overflow;
  outputs.led[2] = overflow;
  outputs.led[3] = overflow;
  
  return outputs;
}
