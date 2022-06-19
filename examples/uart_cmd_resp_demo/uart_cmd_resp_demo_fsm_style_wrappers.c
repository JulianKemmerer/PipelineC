// All the verbose extra stuff needed for experimental FSM style functions as top level MAIN, etc
// TODO some kind of _MAIN_FSM.h include instead?

#include "uart_cmd_deser_FSM.h"
// Wrap up uart_cmd_deser FSM as top level
#pragma MAIN uart_cmd_deser_wrapper
void uart_cmd_deser_wrapper()
{
  uart_cmd_deser_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  uart_cmd_deser_OUTPUT_t o = uart_cmd_deser_FSM(i);
}

#include "uart_resp_ser_FSM.h"
// Wrap up uart_resp_ser FSM as top level
#pragma MAIN uart_resp_ser_wrapper
void uart_resp_ser_wrapper()
{
  uart_resp_ser_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  uart_resp_ser_OUTPUT_t o = uart_resp_ser_FSM(i);
}

#include "bus_transactor_FSM.h"
// Wrap up bus_transactor FSM as top level
#pragma MAIN bus_transactor_wrapper
void bus_transactor_wrapper()
{
  bus_transactor_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  bus_transactor_OUTPUT_t o = bus_transactor_FSM(i);
}