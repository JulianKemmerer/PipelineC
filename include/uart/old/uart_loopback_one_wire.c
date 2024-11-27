// Loopback the single wire serial connection

#include "uintN_t.h"

// Each main function is a clock domain
_Pragma("MAIN_MHZ sys_clk_main 25.0") // 25MHz clock
_Pragma("PART xc7a35ticsg324-1l") // xc7a35ticsg324-1l = Arty, xcvu9p-flgb2104-2-i = AWS F1

// Make structs that wrap up the inputs and outputs
typedef struct sys_clk_main_inputs_t
{
	uint1_t uart_txd_in;
} sys_clk_main_inputs_t;
typedef struct sys_clk_main_outputs_t
{
	uint1_t uart_rxd_out;
} sys_clk_main_outputs_t;


// The sys_clk_main function
sys_clk_main_outputs_t sys_clk_main(sys_clk_main_inputs_t inputs)
{
  // Loopback
  sys_clk_main_outputs_t outputs;
  outputs.uart_rxd_out = inputs.uart_txd_in;
  return outputs;
}
