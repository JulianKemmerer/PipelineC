// Pull in the AWS DMA in and out message hooks
// so we can send and receive dma messages from our fosix_aws_fpga_dma 
#include "../aws-fpga-dma/aws_fpga_dma.c"

// Include protocol for how pack and unpack syscalls into dma msgs
#include "protocol.h"

// Clock cross into fosix
posix_h2c_t aws_h2c;
#include "posix_h2c_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "aws_h2c_clock_crossing.h"
// Clock cross out of fosix
posix_c2h_t aws_c2h;
#include "posix_c2h_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "aws_c2h_clock_crossing.h"

// FLOW CONTROL WITH STATE / NO VALID+READY LOOPS POSSIBLE?
// Fuck... try something super simple?
// Single state per syscall, looping
// Based on syscall state try and make the bidirectional
// h2c+c2h single cycle transfer of data
typedef enum dma_syscall_state_t { 
 OPEN_STATE,
 WRITE_STATE,
 READ_STATE,
 CLOSE_STATE
} dma_syscall_state_t;
dma_syscall_state_t dma_syscall_state;

#pragma MAIN_MHZ fosix_aws_fpga_dma 150.0
void fosix_aws_fpga_dma()
{
  // Inputs
  uint1_t dma_msg_out_ready;
  dma_msg_s dma_msg_in;
  posix_c2h_t c2h;
  // Outputs
  posix_h2c_t h2c;
  uint1_t dma_msg_in_ready;
  dma_msg_s dma_msg_out;
  
  // Read inputs driven from other modules
  //
	// Read ready for output msg flag from aws_fpga_dma
  uint1_t_array_1_t out_readys;
  out_readys = aws_out_msg_ready_READ();
  dma_msg_out_ready = out_readys.data[0];
	// Read DMA message bytes from aws_fpga_dma
  dma_msg_s_array_1_t msgs_in;
  msgs_in = aws_in_msg_READ();
  dma_msg_in = msgs_in.data[0];
  // Read aws c2h output from fosix
  posix_c2h_t_array_1_t c2hs;
  c2hs = aws_c2h_READ();
  c2h = c2hs.data[0];
  //
  // Default output values so each state is easier to write
  h2c = POSIX_H2C_T_NULL();
  dma_msg_in_ready = 0;
  dma_msg_out = DMA_MSG_S_NULL();  
  //////////////////////////////////////////////////////////////////////

  if(dma_syscall_state == OPEN_STATE)
  {
    // Connect incoming dma msg to outgoing request
    h2c.sys_open.resp = dma_to_open_resp(dma_msg_in);
    // Connect flow control if valid response
    if(h2c.sys_open.resp.valid)
    {
      dma_msg_in_ready = c2h.sys_open.resp_ready;
    }
    // Convert incoming request into dma msg
    dma_msg_out = open_req_to_dma(c2h.sys_open.req);
    // Connect flow control
    h2c.sys_open.req_ready = dma_msg_out_ready;
    // Next state
    dma_syscall_state = WRITE_STATE;
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    // Connect incoming dma msg to outgoing request
    h2c.sys_write.resp = dma_to_write_resp(dma_msg_in);
    // Connect flow control if valid response
    if(h2c.sys_write.resp.valid)
    {
      dma_msg_in_ready = c2h.sys_write.resp_ready;
    }
    // Convert incoming request into dma msg
    dma_msg_out = write_req_to_dma(c2h.sys_write.req);
    // Connect flow control
    h2c.sys_write.req_ready = dma_msg_out_ready;
    // Next state
    dma_syscall_state = READ_STATE;
  }
  else if(dma_syscall_state == READ_STATE)
  {
    // Connect incoming dma msg to outgoing request
    h2c.sys_read.resp = dma_to_read_resp(dma_msg_in);
    // Connect flow control if valid response
    if(h2c.sys_read.resp.valid)
    {
      dma_msg_in_ready = c2h.sys_read.resp_ready;
    }
    // Convert incoming request into dma msg
    dma_msg_out = read_req_to_dma(c2h.sys_read.req);
    // Connect flow control
    h2c.sys_read.req_ready = dma_msg_out_ready;
    // Next state
    dma_syscall_state = CLOSE_STATE;
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    // Connect incoming dma msg to outgoing request
    h2c.sys_close.resp = dma_to_close_resp(dma_msg_in);
    // Connect flow control if valid response
    if(h2c.sys_close.resp.valid)
    {
      dma_msg_in_ready = c2h.sys_close.resp_ready;
    }
    // Convert incoming request into dma msg
    dma_msg_out = close_req_to_dma(c2h.sys_close.req);
    // Connect flow control
    h2c.sys_close.req_ready = dma_msg_out_ready;
    // Next state
    dma_syscall_state = OPEN_STATE;
  }

  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write aws h2c into fosix
  posix_h2c_t_array_1_t h2cs;
  h2cs.data[0] = h2c;
  aws_h2c_WRITE(h2cs);
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = dma_msg_in_ready;
	aws_in_msg_ready_WRITE(in_readys);
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = dma_msg_out;
	aws_out_msg_WRITE(msgs_out);
}

