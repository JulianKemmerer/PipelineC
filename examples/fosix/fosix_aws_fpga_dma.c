// Pull in the AWS DMA in and out message hooks
// so we can send and receive dma messages from our fosix_aws_fpga_dma 
#include "../aws-fpga-dma/aws_fpga_dma.c"

// Include protocol for how pack and unpack syscalls into dma msgs
#include "protocol.h"

// Clock cross into fosix
fosix_sys_to_proc_t aws_sys_to_proc;
#include "clock_crossing/aws_sys_to_proc.h"
// Clock cross out of fosix
fosix_proc_to_sys_t aws_proc_to_sys;
#include "clock_crossing/aws_proc_to_sys.h"

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
  fosix_proc_to_sys_t proc_to_sys;
  // Outputs
  fosix_sys_to_proc_t sys_to_proc;
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
  // Read aws proc_to_sys output from fosix
  fosix_proc_to_sys_t_array_1_t proc_to_syss;
  proc_to_syss = aws_proc_to_sys_READ();
  proc_to_sys = proc_to_syss.data[0];
  //
  // Default output values so each state is easier to write
  //////////////////////////////////////////////////////////////////////

  // REQUEST INPUT TO DMA OUTPUT PATH 
  //
  // Start off signaling ready to all syscall requests
  // if ready for DMA msg out
  if(dma_msg_out_ready)
  {
    sys_to_proc = h2c_set_ready(sys_to_proc);
    // Find one system call making a request
    // and invalidate the ready for all other requests
    // Convert incoming request into dma msg out
    // OK to have dumb constant priority 
    // and valid<->ready combinatorial feedback for now
    if(proc_to_sys.sys_open.req.valid)
    {
      sys_to_proc = h2c_clear_ready(sys_to_proc);
      sys_to_proc.sys_open.req_ready = 1;
      dma_msg_out = open_req_to_dma(proc_to_sys.sys_open.req);
    }
    else if(proc_to_sys.sys_write.req.valid)
    {
      sys_to_proc = h2c_clear_ready(sys_to_proc);
      sys_to_proc.sys_write.req_ready = 1;
      dma_msg_out = write_req_to_dma(proc_to_sys.sys_write.req);
    }
    else if(proc_to_sys.sys_read.req.valid)
    {
      sys_to_proc = h2c_clear_ready(sys_to_proc);
      sys_to_proc.sys_read.req_ready = 1;
      dma_msg_out = read_req_to_dma(proc_to_sys.sys_read.req);
    }
    else if(proc_to_sys.sys_close.req.valid)
    {
      sys_to_proc = h2c_clear_ready(sys_to_proc);
      sys_to_proc.sys_close.req_ready = 1;
      dma_msg_out = close_req_to_dma(proc_to_sys.sys_close.req);
    }
  }
  // TODO Break path from dma out ready to dma out valid, unnecessary
  
  // DMA INPUT TO RESPONSE OUTPUT PATH 
  //
  // Default not ready for DMA input
  dma_msg_in_ready = 0;
  // Unless the message is for a syscall that is ready
  // What syscall is the incoming DMA mesage a response to?
  // OK to have dumb valid<->ready combinatorial feedback for now
  // Convert incoming dma msg into response
  // Only one response will be valid, if any
  sys_to_proc.sys_open.resp = dma_to_open_resp(dma_msg_in);
  sys_to_proc.sys_write.resp = dma_to_write_resp(dma_msg_in);
  sys_to_proc.sys_read.resp = dma_to_read_resp(dma_msg_in);
  sys_to_proc.sys_close.resp = dma_to_close_resp(dma_msg_in);
  // and connect flow control
  if(sys_to_proc.sys_open.resp.valid)
  {
    dma_msg_in_ready = proc_to_sys.sys_open.resp_ready;
  }
  else if(sys_to_proc.sys_write.resp.valid)
  {
    dma_msg_in_ready = proc_to_sys.sys_write.resp_ready;
  }
  else if(sys_to_proc.sys_read.resp.valid)
  {
    dma_msg_in_ready = proc_to_sys.sys_read.resp_ready;
  }
  else if(sys_to_proc.sys_close.resp.valid)
  {
    dma_msg_in_ready = proc_to_sys.sys_close.resp_ready;
  }
  
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write aws sys_to_proc into fosix
  fosix_sys_to_proc_t_array_1_t sys_to_procs;
  sys_to_procs.data[0] = sys_to_proc;
  aws_sys_to_proc_WRITE(sys_to_procs);
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = dma_msg_in_ready;
	aws_in_msg_ready_WRITE(in_readys);
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = dma_msg_out;
	aws_out_msg_WRITE(msgs_out);
}

