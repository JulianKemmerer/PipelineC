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

// Need to arbitrate valid and ready signals to and from the 
// appropriate syscalls and messages
// 1 syscall incoming, 1 syscall outgoing per iteration since only
// have one dma msg buffer outgoing, and one dma msg buffer incoming
// to/from AWS DMA engine right now

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

  // REQUEST INPUT TO DMA OUTPUT PATH 
  //
  // Start off signaling ready to all syscall requests
  // if ready for DMA msg out
  if(dma_msg_out_ready)
  {
    h2c = h2c_set_ready(h2c);
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Convert incoming request into dma msg out
    // OK to have dumb constant priority 
    // and valid<->ready combinatorial feedback for now
    if(c2h.sys_open.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_open.req_ready = 1;
      dma_msg_out = open_req_to_dma(c2h.sys_open.req);
    }
    else if(c2h.sys_write.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_write.req_ready = 1;
      dma_msg_out = write_req_to_dma(c2h.sys_write.req);
    }
    else if(c2h.sys_read.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_read.req_ready = 1;
      dma_msg_out = read_req_to_dma(c2h.sys_read.req);
    }
    else if(c2h.sys_close.req.valid)
    {
      h2c = h2c_clear_ready(h2c);
      h2c.sys_close.req_ready = 1;
      dma_msg_out = close_req_to_dma(c2h.sys_close.req);
    }
  }
  // TODO Break path from dma out ready to dma out valid, unnecessary
  
  // DMA INPUT TO RESPONSE OUTPUT PATH 
  //
  // Default not ready for DMA input
  dma_msg_in_ready = 0;
  // Unless the message is for a syscall that is ready
  // What syscall is the incoming DMA mesage a response to?
  // OK to have dumb constant priority 
  // and valid<->ready combinatorial feedback for now
  syscall_t resp_id = decode_syscall_id(dma_msg_in.data);
  // Convert incoming dma msg into response
  // and connect flow control
  if(resp_id == POSIX_OPEN)
  {
    h2c.sys_open.resp = dma_to_open_resp(dma_msg_in);
    dma_msg_in_ready = c2h.sys_open.resp_ready;
  }
  else if(resp_id == POSIX_WRITE)
  {
    h2c.sys_write.resp = dma_to_write_resp(dma_msg_in);
    dma_msg_in_ready = c2h.sys_write.resp_ready;
  }
  else if(resp_id == POSIX_READ)
  {
    h2c.sys_read.resp = dma_to_read_resp(dma_msg_in);
    dma_msg_in_ready = c2h.sys_read.resp_ready;
  }
  else if(resp_id == POSIX_CLOSE)
  {
    h2c.sys_close.resp = dma_to_close_resp(dma_msg_in);
    dma_msg_in_ready = c2h.sys_close.resp_ready;
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

