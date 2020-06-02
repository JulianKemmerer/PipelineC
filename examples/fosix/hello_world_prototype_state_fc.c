/*
 This code describes a state machine that writes "Hello, World!\n"
 to STDOUT via user space system calls on a host machine.
*/

#include "../aws-fpga-dma/aws_fpga_dma.c" // FPGA POSIX? AWS DMA msg direct
// Include protocol for how pack and unpack syscalls into dma msgs
#include "protocol.h"

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


// hello world
// State machine to do the steps of
typedef enum state_t { 
  RESET, // State while in reset? Debug...
	OPEN_REQ, // Ask to open the file (starting state)
	OPEN_RESP, // Receive file descriptor
	WRITE_REQ, // Ask to write to file descriptor
	WRITE_RESP, // Receive how many bytes were written
  DONE // Stay here doing nothing until FPGA bitstream reloaded
} state_t;
state_t state;
fd_t stdout_fildes; // File descriptor for stdout
#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper(uint1_t rst)
{
  // Inputs
  uint1_t dma_msg_out_ready;
  dma_msg_s dma_msg_in;
  
  posix_c2h_t c2h; //OUTPUT of MAIN
  
  // Outputs
  uint1_t dma_msg_in_ready;
  dma_msg_s dma_msg_out;
  
  posix_h2c_t h2c; //INPUT OF MAIN
  
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

  // Default output values so each state is easier to write
  h2c = POSIX_H2C_T_NULL();
  dma_msg_in_ready = 0;
  dma_msg_out = DMA_MSG_S_NULL();  
  //////////////////////////////////////////////////////////////////////
  //////////////////////////////////////////////////////////////////////
  
  //                 H2C RESP DRIVEN BY DMA IN
  
  
  // DMA DATA TO RESPONSE DATA PATH
  // Convert incoming dma msg into response
  if(dma_syscall_state == OPEN_STATE)
  {
    h2c.sys_open.resp = dma_to_open_resp(dma_msg_in);
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    h2c.sys_write.resp = dma_to_write_resp(dma_msg_in);
  }
  else if(dma_syscall_state == READ_STATE)
  {
    h2c.sys_read.resp = dma_to_read_resp(dma_msg_in);
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    h2c.sys_close.resp = dma_to_close_resp(dma_msg_in);
  }
  
  //////////////////////////////////////////////////////////////////////
  
  //                  H2C REQ READY DRIVEN
  
  if(dma_syscall_state == OPEN_STATE)
  {
    h2c.sys_open.req_ready = dma_msg_out_ready;
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    h2c.sys_write.req_ready = dma_msg_out_ready;
  }
  else if(dma_syscall_state == READ_STATE)
  {
    h2c.sys_read.req_ready = dma_msg_out_ready;
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    h2c.sys_close.req_ready = dma_msg_out_ready;
  }
  
  //////////////////////////////////////////////////////////////////////
  
  //                  C2H  DRIVEN BY MAIN
  
  // Default output/reset/null values
  //outputs_t o;
  c2h = POSIX_C2H_T_NULL();
  
  // State machine
  if(state==RESET)
  {
    state = OPEN_REQ;
  }
  else if(state==OPEN_REQ)
  {
    // Request to open /dev/stdout (stdout on driver program on host)
    // Hard code bytes for now
    c2h.sys_open.req.path[0]  = '/';
    c2h.sys_open.req.path[1]  = 'd';
    c2h.sys_open.req.path[2]  = 'e';
    c2h.sys_open.req.path[3]  = 'v';
    c2h.sys_open.req.path[4]  = '/';
    c2h.sys_open.req.path[5]  = 's';
    c2h.sys_open.req.path[6]  = 't';
    c2h.sys_open.req.path[7]  = 'd';
    c2h.sys_open.req.path[8]  = 'o';
    c2h.sys_open.req.path[9]  = 'u';
    c2h.sys_open.req.path[10] = 't';
    c2h.sys_open.req.valid = 1;
    // Keep trying to request until finally was ready
    if(h2c.sys_open.req_ready)
    {
      // Then wait for response
      state = OPEN_RESP;
    }
  }
  else if(state==OPEN_RESP)
  {
    // Wait here ready for response
    c2h.sys_open.resp_ready = 1;
    // Until we get valid response
    if(h2c.sys_open.resp.valid)
    { 
      // Save file descriptor
      stdout_fildes = h2c.sys_open.resp.fildes;
      // Move onto writing to file
      state = WRITE_REQ;
    }
  }
  else if(state==WRITE_REQ)
  {
    // Request to write "Hello, World!\n" to the file descriptor
    // Hard code bytes for now
    c2h.sys_write.req.buf[0]  = 'H';
    c2h.sys_write.req.buf[1]  = 'e';
    c2h.sys_write.req.buf[2]  = 'l';
    c2h.sys_write.req.buf[3]  = 'l';
    c2h.sys_write.req.buf[4]  = 'o';
    c2h.sys_write.req.buf[5]  = ',';
    c2h.sys_write.req.buf[6]  = ' ';
    c2h.sys_write.req.buf[7]  = 'W';
    c2h.sys_write.req.buf[8]  = 'o';
    c2h.sys_write.req.buf[9]  = 'r'; 
    c2h.sys_write.req.buf[10] = 'l';
    c2h.sys_write.req.buf[11] = 'd';
    c2h.sys_write.req.buf[12] = '!';
    c2h.sys_write.req.buf[13] = '\n';
    c2h.sys_write.req.nbyte = 14;
    c2h.sys_write.req.fildes = stdout_fildes;
    c2h.sys_write.req.valid = 1;
    // Keep trying to request until finally was ready
    if(h2c.sys_write.req_ready)
    {
      // Then wait for response
      state = WRITE_RESP;
    }
  }
  else if(state==WRITE_RESP)
  {
    // Wait here ready for response
    c2h.sys_write.resp_ready = 1;
    // Until we get valid response
    if(h2c.sys_write.resp.valid)
    { 
      // Would do something based on how many bytes were written
      //    h2c.sys_write.resp.nbyte
      // But for now assume it went well, done
      state = DONE;
    }
  }
  // Reset
  if(rst)
  {
    state = RESET;
  }
  
  //////////////////////////////////////////////////////////////////////
  
  //                  C2H  READ
  
  // REQUEST DATA TO DMA DATA PATH 
  if(dma_syscall_state == OPEN_STATE)
  {
    dma_msg_out = open_req_to_dma(c2h.sys_open.req);
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    dma_msg_out = write_req_to_dma(c2h.sys_write.req);
  }
  else if(dma_syscall_state == READ_STATE)
  {
    dma_msg_out = read_req_to_dma(c2h.sys_read.req);
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    dma_msg_out = close_req_to_dma(c2h.sys_close.req);
  }
  
  //////////////////////////////////////////////////////////////////////
  
  // DMA READY FROM RESPONSE READY PATH
  // Connect DMA msg in flow control driven by C2H resp_ready 
  // Default not ready for DMA input
  dma_msg_in_ready = 0;
  if(dma_syscall_state == OPEN_STATE)
  {
    dma_msg_in_ready = c2h.sys_open.resp_ready;
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    dma_msg_in_ready = c2h.sys_write.resp_ready;
  }
  else if(dma_syscall_state == READ_STATE)
  {
    dma_msg_in_ready = c2h.sys_read.resp_ready;
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    dma_msg_in_ready = c2h.sys_close.resp_ready;
  }
  
  
  //////////////////////////////////////////////////////////////////////
  
  // dma_syscall_state FSM loop
  if(dma_syscall_state == OPEN_STATE)
  {
    dma_syscall_state = WRITE_STATE;
  }
  else if(dma_syscall_state == WRITE_STATE)
  {
    dma_syscall_state = READ_STATE;
  }
  else if(dma_syscall_state == READ_STATE)
  {
    dma_syscall_state = CLOSE_STATE;
  }
  else if(dma_syscall_state == CLOSE_STATE)
  {
    dma_syscall_state = OPEN_STATE;
  }
  
  //////////////////////////////////////////////////////////////////////
  //////////////////////////////////////////////////////////////////////
  // Write driven outputs into other modules
  //
  // Write ready for input message indicator into aws_fpga_dma
  uint1_t_array_1_t in_readys;
	in_readys.data[0] = dma_msg_in_ready;
	aws_in_msg_ready_WRITE(in_readys);
  // Write DMA message bytes into aws_fpga_dma
	dma_msg_s_array_1_t msgs_out;
	msgs_out.data[0] = dma_msg_out;
	aws_out_msg_WRITE(msgs_out);
}
