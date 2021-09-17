// Connect the 'System' device over uart to a host OS

// Host device (UART based)
#pragma once

#include "compiler.h"
// Helper macros for global clock cross wires
#include "wire.h"

// Pull in the logic to send and receive messages
#include "../arty/src/uart/uart_msg.c"

// Include protocol for how pack and unpack syscalls into messages
#include "fosix_msg_hw.h"
#include "host_uart.h"

// Clock cross wire to into fosix router thing
fosix_sys_to_proc_t host_sys_to_proc;
#include "clock_crossing/host_sys_to_proc.h"
// Clock cross out of fosix
fosix_proc_to_sys_t host_proc_to_sys;
#include "clock_crossing/host_proc_to_sys.h"

MAIN_MHZ(sys_host, UART_CLK_MHZ)
void sys_host()
{
  // Read inputs driven from other modules
  //
	// Read ready for output msg flag from tx logic
  uint1_t msg_out_ready;
  WIRE_READ(uint1_t, msg_out_ready,  uart_tx_msg_in_ready)
	// Read message bytes from rx msg logic
  uart_msg_s uart_msg_in;
  WIRE_READ(uart_msg_s, uart_msg_in, uart_rx_msg_out)
  // Convert to fosix type
  fosix_msg_s msg_in = uart_msg_s_to_fosix_msg_s(uart_msg_in);
  // Read proc_to_sys output from fosix router thing
  fosix_proc_to_sys_t proc_to_sys;
  WIRE_READ(fosix_proc_to_sys_t, proc_to_sys, host_proc_to_sys)
  
  // Outputs
  // Default output values so each state is easier to write
  fosix_sys_to_proc_t sys_to_proc;
  uint1_t msg_in_ready = 0;
  fosix_msg_s msg_out;
  //////////////////////////////////////////////////////////////////////

  // PROC_TO_SYS MSG OUTPUT PATH
  sys_to_proc.proc_to_sys_msg_ready = msg_out_ready;
  msg_out = proc_to_sys.msg;
  
  // MSG SYS_TO_PROC INPUT PATH 
  msg_in_ready = proc_to_sys.sys_to_proc_msg_ready;
  sys_to_proc.msg = msg_in;
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write sys_to_proc into fosix router thing
  WIRE_WRITE(fosix_sys_to_proc_t, host_sys_to_proc, sys_to_proc)
  // Write ready for input message indicator into msg rx logic
  WIRE_WRITE(uint1_t, uart_rx_msg_out_ready, msg_in_ready)
  // Write message bytes into TX logic 
  // Convert from fosix type
  uart_msg_s uart_msg_out = fosix_msg_s_to_uart_msg_s(msg_out);
  WIRE_WRITE(uart_msg_s, uart_tx_msg_in, uart_msg_out)
}

