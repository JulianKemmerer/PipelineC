/*
 This code describes a state machine that writes "Hello, World!\n"
 to STDOUT via user space system calls on a host machine.
*/

//#include "fosix.c" // FPGA POSIX? General
//#include "fosix_aws_fpga_dma.c" // FPGA POSIX? AWS direct
#include "fosix_aws_fpga_dma_state_fc.c" // FPGA POSIX? AWS direct with state flow control

// hello world
//  Uses posix busses for IO
typedef struct inputs_t
{
	 posix_h2c_t h2c;
} inputs_t;
typedef struct outputs_t
{
  posix_c2h_t c2h;
} outputs_t;
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
outputs_t main(inputs_t i, uint1_t rst)
{
  // Default output/reset/null values
  outputs_t o;
  o.c2h = POSIX_C2H_T_NULL();
  
  // State machine
  if(state==RESET)
  {
    state = OPEN_REQ;
  }
  else if(state==OPEN_REQ)
  {
    // Request to open /dev/stdout (stdout on driver program on host)
    // Hard code bytes for now
    o.c2h.sys_open.req.path[0]  = '/';
    o.c2h.sys_open.req.path[1]  = 'd';
    o.c2h.sys_open.req.path[2]  = 'e';
    o.c2h.sys_open.req.path[3]  = 'v';
    o.c2h.sys_open.req.path[4]  = '/';
    o.c2h.sys_open.req.path[5]  = 's';
    o.c2h.sys_open.req.path[6]  = 't';
    o.c2h.sys_open.req.path[7]  = 'd';
    o.c2h.sys_open.req.path[8]  = 'o';
    o.c2h.sys_open.req.path[9]  = 'u';
    o.c2h.sys_open.req.path[10] = 't';
    o.c2h.sys_open.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_open.req_ready)
    {
      // Then wait for response
      state = OPEN_RESP;
    }
  }
  else if(state==OPEN_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_open.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_open.resp.valid)
    { 
      // Save file descriptor
      stdout_fildes = i.h2c.sys_open.resp.fildes;
      // Move onto writing to file
      state = WRITE_REQ;
    }
  }
  else if(state==WRITE_REQ)
  {
    // Request to write "Hello, World!\n" to the file descriptor
    // Hard code bytes for now
    o.c2h.sys_write.req.buf[0]  = 'H';
    o.c2h.sys_write.req.buf[1]  = 'e';
    o.c2h.sys_write.req.buf[2]  = 'l';
    o.c2h.sys_write.req.buf[3]  = 'l';
    o.c2h.sys_write.req.buf[4]  = 'o';
    o.c2h.sys_write.req.buf[5]  = ',';
    o.c2h.sys_write.req.buf[6]  = ' ';
    o.c2h.sys_write.req.buf[7]  = 'W';
    o.c2h.sys_write.req.buf[8]  = 'o';
    o.c2h.sys_write.req.buf[9]  = 'r'; 
    o.c2h.sys_write.req.buf[10] = 'l';
    o.c2h.sys_write.req.buf[11] = 'd';
    o.c2h.sys_write.req.buf[12] = '!';
    o.c2h.sys_write.req.buf[13] = '\n';
    o.c2h.sys_write.req.nbyte = 14;
    o.c2h.sys_write.req.fildes = stdout_fildes;
    o.c2h.sys_write.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_write.req_ready)
    {
      // Then wait for response
      state = WRITE_RESP;
    }
  }
  else if(state==WRITE_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_write.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_write.resp.valid)
    { 
      // Would do something based on how many bytes were written
      //    i.h2c.sys_write.resp.nbyte
      // But for now assume it went well, done
      state = DONE;
    }
  }

  // Reset
  if(rst)
  {
    state = RESET;
  }
    
  return o;
}

// Include wrapper connecting 'main' to fosix 'host'
//#include "main_wrapper.c" // General
#include "main_wrapper_fosix_aws_direct.c" // AWS direct
