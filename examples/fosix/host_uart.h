#pragma once
#include "fosix_msg.h"
#include "../arty/src/uart/uart_msg.h"

// Helper logic to cast uart types to fosix types
fosix_msg_t uart_msg_t_to_fosix_msg_t(uart_msg_t uart_msg_in)
{
  fosix_msg_t msg_in;
  uint32_t i;
  for(i=0;i<FOSIX_MSG_SIZE;i+=1)
  {
    msg_in.data[i] = uart_msg_in.data[i];
  }
  return msg_in;
}

uart_msg_t fosix_msg_t_to_uart_msg_t(fosix_msg_t msg_out)
{
  uart_msg_t uart_msg_out;
  uint32_t i;
  for(i=0;i<FOSIX_MSG_SIZE;i+=1)
  {
    uart_msg_out.data[i] = msg_out.data[i];
  }
  return uart_msg_out;
}

#pragma FUNC_WIRES uart_msg_s_to_fosix_msg_s
fosix_msg_s uart_msg_s_to_fosix_msg_s(uart_msg_s uart_msg_in)
{
  fosix_msg_s msg_in;
  msg_in.data = uart_msg_t_to_fosix_msg_t(uart_msg_in.data);
  msg_in.valid = uart_msg_in.valid;
  return msg_in;
}
#pragma FUNC_WIRES fosix_msg_s_to_uart_msg_s
uart_msg_s fosix_msg_s_to_uart_msg_s(fosix_msg_s msg_out)
{
  uart_msg_s uart_msg_out;
  uart_msg_out.data = fosix_msg_t_to_uart_msg_t(msg_out.data);
  uart_msg_out.valid = msg_out.valid;
  return uart_msg_out;
}
