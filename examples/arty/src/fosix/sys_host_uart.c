// Host device (UART based)
#pragma once

#include "compiler.h"
// Helper macros for global clock cross wires
#include "wire.h"

// Pull in the logic to send and receive messages
#include "../uart/uart_msg.c"
// Marking the main wrappers as main functions
MAIN_MHZ(uart_rx_msg_main, UART_CLK_MHZ)
MAIN_MHZ(uart_tx_msg_main, UART_CLK_MHZ)

// Include protocol for how pack and unpack syscalls into messages
#include "fosix_msg.h"
#include "host_uart.h"

// Clock cross wire to into fosix router thing
fosix_sys_to_proc_t host_sys_to_proc;
#include "fosix_sys_to_proc_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "host_sys_to_proc_clock_crossing.h"
// Clock cross out of fosix
fosix_proc_to_sys_t host_proc_to_sys;
#include "fosix_proc_to_sys_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "host_proc_to_sys_clock_crossing.h"

// Need to arbitrate valid and ready signals to and from the 
// appropriate syscalls and messages
// 1 syscall incoming, 1 syscall outgoing per iteration since only
// have one msg buffer outgoing, and one msg buffer incoming
// to/from message logic right now

MAIN_MHZ(sys_host, UART_CLK_MHZ)
void sys_host()
{
  // Read inputs driven from other modules
  //
	// Read ready for output msg flag from tx logic
  uint1_t msg_out_ready;
  WIRE_READ(uint1_t, msg_out_ready,  uart_tx_msg_msg_in_ready)
	// Read message bytes from rx msg logic
  uart_msg_s uart_msg_in;
  WIRE_READ(uart_msg_s, uart_msg_in, uart_rx_msg_msg_out)
  // Convert to fosix type
  fosix_msg_s msg_in = uart_msg_s_to_fosix_msg_s(uart_msg_in);
  // Read proc_to_sys output from fosix router thing
  fosix_proc_to_sys_t proc_to_sys;
  WIRE_READ(fosix_proc_to_sys_t, proc_to_sys, host_proc_to_sys)
  
  // Outputs
  // Default output values so each state is easier to write
  fosix_sys_to_proc_t sys_to_proc = POSIX_SYS_TO_PROC_T_NULL();
  uint1_t msg_in_ready = 0;
  fosix_msg_s msg_out = FOSIX_MSG_S_NULL();
  //////////////////////////////////////////////////////////////////////

  // PROC_TO_SYS MSG OUTPUT PATH 
  //
  // Start off signaling ready to all process requests
  // if output msg ready
  if(msg_out_ready)
  {
    sys_to_proc = sys_to_proc_set_ready(sys_to_proc);
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Convert incoming request into dma msg out
    // OK to have dumb constant priority 
    // and valid<->ready combinatorial feedback for now
    if(proc_to_sys.sys_open.req.valid)
    {
      sys_to_proc = sys_to_proc_clear_ready(sys_to_proc);
      sys_to_proc.sys_open.req_ready = 1;
      msg_out = open_req_to_msg(proc_to_sys.sys_open.req);
    }
    else if(proc_to_sys.sys_write.req.valid)
    {
      sys_to_proc = sys_to_proc_clear_ready(sys_to_proc);
      sys_to_proc.sys_write.req_ready = 1;
      msg_out = write_req_to_msg(proc_to_sys.sys_write.req);
    }
    else if(proc_to_sys.sys_read.req.valid)
    {
      sys_to_proc = sys_to_proc_clear_ready(sys_to_proc);
      sys_to_proc.sys_read.req_ready = 1;
      msg_out = read_req_to_msg(proc_to_sys.sys_read.req);
    }
    else if(proc_to_sys.sys_close.req.valid)
    {
      sys_to_proc = sys_to_proc_clear_ready(sys_to_proc);
      sys_to_proc.sys_close.req_ready = 1;
      msg_out = close_req_to_msg(proc_to_sys.sys_close.req);
    }
  }
  // TODO Break path from msg out ready to msg out valid, unnecessary
  
  // MSG SYS_TO_PROC INPUT PATH 
  //
  // Default not ready for msg input
  msg_in_ready = 0;
  // Unless the message is for a syscall that is ready
  // What syscall is the incoming mesage a response to?
  // OK to have dumb valid<->ready combinatorial feedback for now
  // Convert incoming msg into response
  // Only one response will be valid, if any
  sys_to_proc.sys_open.resp = msg_to_open_resp(msg_in);
  sys_to_proc.sys_write.resp = msg_to_write_resp(msg_in);
  sys_to_proc.sys_read.resp = msg_to_read_resp(msg_in);
  sys_to_proc.sys_close.resp = msg_to_close_resp(msg_in);
  // and connect flow control
  if(sys_to_proc.sys_open.resp.valid)
  {
    msg_in_ready = proc_to_sys.sys_open.resp_ready;
  }
  else if(sys_to_proc.sys_write.resp.valid)
  {
    msg_in_ready = proc_to_sys.sys_write.resp_ready;
  }
  else if(sys_to_proc.sys_read.resp.valid)
  {
    msg_in_ready = proc_to_sys.sys_read.resp_ready;
  }
  else if(sys_to_proc.sys_close.resp.valid)
  {
    msg_in_ready = proc_to_sys.sys_close.resp_ready;
  }
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write sys_to_proc into fosix router thing
  WIRE_WRITE(fosix_sys_to_proc_t, host_sys_to_proc, sys_to_proc)
  // Write ready for input message indicator into msg rx logic
  WIRE_WRITE(uint1_t, uart_rx_msg_msg_out_ready, msg_in_ready)
  // Write message bytes into TX logic 
  // Convert from fosix type
  uart_msg_s uart_msg_out = fosix_msg_s_to_uart_msg_s(msg_out);
  WIRE_WRITE(uart_msg_s, uart_tx_msg_msg_in, uart_msg_out)
}

