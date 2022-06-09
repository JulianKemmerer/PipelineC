// Message to pass between C on host and PipelineC on FPGA

#pragma once
#include "uintN_t.h"

#define UART_MSG_SIZE 64
#define UART_MSG_SIZE_MULT(x) ((x)<<6)
typedef struct uart_msg_t
{
  uint8_t data[UART_MSG_SIZE];
}uart_msg_t;
