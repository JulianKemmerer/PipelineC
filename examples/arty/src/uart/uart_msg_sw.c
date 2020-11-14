// Code wrapping the file (UART) interface to a common 'message'

// PipelineC header
#include "uart_sw.c"
#include "uart_msg.h"

// Wrapper around uart write for this example
int msg_write(uart_msg_t* msg)
{
  return uart_write(&(msg->data[0]), UART_MSG_SIZE);
}

// Wrapper around uart read for this example
int msg_read(uart_msg_t* msg)
{
  return uart_read(&(msg->data[0]), UART_MSG_SIZE);
}

int init_msgs()
{
  return init_uart();
}

void close_msgs()
{
	return close_uart();
}


