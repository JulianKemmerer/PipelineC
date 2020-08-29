// Message to pass between C on host and PipelineC on FPGA

#pragma once
#include "uintN_t.h"

#define UART_MSG_SIZE 256
typedef struct uart_msg_t
{
  uint8_t data[UART_MSG_SIZE];
}uart_msg_t;
uart_msg_t UART_MSG_T_NULL()
{
  uart_msg_t rv;
  uint32_t i;
  for(i=0;i<UART_MSG_SIZE;i=i+1)
  {
    rv.data[i] = 0;
  }
  return rv;
}

// Stream version
typedef struct uart_msg_s
{
   uart_msg_t data;
   uint1_t valid;
}uart_msg_s;
uart_msg_s UART_MSG_S_NULL()
{
  uart_msg_s rv;
  rv.data = UART_MSG_T_NULL();
  rv.valid = 0;
  return rv;
}
