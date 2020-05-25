// Pull in the AWS DMA in and out message hooks
// so we can send and receive dma messages from our posix_aws_fpga_dma 
#include "../aws-fpga-dma/aws_fpga_dma.c"

// Include protocol for how pack and unpack syscalls into dma msgs
#include "protocol.h"

// Clock cross into main
posix_h2c_t posix_h2c;
#include "posix_h2c_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "posix_h2c_clock_crossing.h"
// Clock cross out of main
posix_c2h_t posix_c2h;
#include "posix_c2h_t_array_N_t.h" // TODO include inside clock_crossing.h?
#include "posix_c2h_clock_crossing.h"

// Simple slow bulky single state machine for now...
// service every syscall individally one at a time
typedef enum posix_aws_fpga_dma_state_t {
  OPEN_STATE,
  WRITE_STATE,
} posix_aws_fpga_dma_state_t;
posix_aws_fpga_dma_state_t posix_aws_fpga_dma_state;
#pragma MAIN_MHZ posix_aws_fpga_dma 150.0
void posix_aws_fpga_dma()
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
  out_readys = out_msg_ready_READ();
  dma_msg_out_ready = out_readys.data[0];
	// Read DMA message bytes from aws_fpga_dma
  dma_msg_s_array_1_t msgs_in;
  msgs_in = in_msg_READ();
  dma_msg_in = msgs_in.data[0];
  // Read posix c2h output from main
  posix_c2h_t_array_1_t c2hs;
  c2hs = posix_c2h_READ();
  c2h = c2hs.data[0];
  //////////////////////////////////////////////////////////////////////
  
  // Default outputs so each state is easier to write
  h2c = POSIX_H2C_T_NULL();
  dma_msg_in_ready = 0;
  dma_msg_out = DMA_MSG_S_NULL();
  
  // Incoming DMA messages are reponses to syscalls
  // And syscall requests are outgoing DMA messages
  // Based on syscall state try and make the bidirectional
  // h2c+c2h single cycle transfer of data

  if(posix_aws_fpga_dma_state==OPEN_STATE)
  {
    // Convert incoming dma msg into response
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
    
    // Go to next state
    posix_aws_fpga_dma_state = WRITE_STATE;
  }
  else if(posix_aws_fpga_dma_state==WRITE_STATE)
  {
    // Convert incoming dma msg into response
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
    
    // Go to next state
    posix_aws_fpga_dma_state = OPEN_STATE;    
  }

  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write posix h2c into main
  posix_h2c_t_array_1_t h2cs;
  h2cs.data[0] = h2c;
  posix_h2c_WRITE(h2cs);
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = dma_msg_in_ready;
	in_msg_ready_WRITE(in_readys);
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = dma_msg_out;
	out_msg_WRITE(msgs_out);
}

