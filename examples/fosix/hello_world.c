/*
 This code describes a state machine that prints hello world to std_out
 STDIN and STDOUT tied to user space actual stdin and out! -Cool
 * TODO: BRAM as file, off chip DDR, PCIM AXI as file
*/

#include "fosix.c" // FPGA POSIX?

// hello world
//  Uses posix busses for IO
typedef struct inputs_t
{
	 posix_h2c_t posix_h2c;
} inputs_t;
typedef struct outputs_t
{
  posix_c2h_t posix_c2h;
} outputs_t;
// State machine to do the steps of
typedef enum state_t {
	OPEN_REQ, // Ask to open the file
	OPEN_RESP, // Receive file descriptor
	WRITE_REQ, // Ask to write to file descriptor
	WRITE_RESP // Receive how many bytes were written
} state_t;
state_t state;
fd_t fildes; // File descriptor for stdin
outputs_t main(inputs_t i)
{
  // Default output/reset/null values
  outputs_t o;
  o.posix_c2h = POSIX_C2H_T_NULL();
  
  // State machine
  if(state==OPEN_REQ)
  {
    // Request to open /dev/stdout (stdout on driver program on host)
    // Hard code bytes for now
    o.posix_c2h.sys_open.req.path[0]  = '/';
    o.posix_c2h.sys_open.req.path[1]  = 'd';
    o.posix_c2h.sys_open.req.path[2]  = 'e';
    o.posix_c2h.sys_open.req.path[3]  = 'v';
    o.posix_c2h.sys_open.req.path[4]  = '/';
    o.posix_c2h.sys_open.req.path[5]  = 's';
    o.posix_c2h.sys_open.req.path[6]  = 't';
    o.posix_c2h.sys_open.req.path[7]  = 'd';
    o.posix_c2h.sys_open.req.path[8]  = 'o';
    o.posix_c2h.sys_open.req.path[9]  = 'u';
    o.posix_c2h.sys_open.req.path[10] = 't';
    o.posix_c2h.sys_open.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.posix_h2c.sys_open.req_ready)
    {
      // Then wait for response
      state = OPEN_RESP;
    }
  }
  else if(state==OPEN_RESP)
  {
    // Wait here ready for response
    o.posix_c2h.sys_open.resp_ready = 1;
    // Until we get valid response
    if(i.posix_h2c.sys_open.resp.valid)
    { 
      // Save file descriptor
      fildes = i.posix_h2c.sys_open.resp.fildes;
      // Move onto writing to file
      state = WRITE_REQ;
    }
  }
  else if(state==WRITE_REQ)
  {
    // Request to write "Hello, World!\n" to the file descriptor
    // Hard code bytes for now
    o.posix_c2h.sys_write.req.buf[0]  = 'H';
    o.posix_c2h.sys_write.req.buf[1]  = 'e';
    o.posix_c2h.sys_write.req.buf[2]  = 'l';
    o.posix_c2h.sys_write.req.buf[3]  = 'l';
    o.posix_c2h.sys_write.req.buf[4]  = 'o';
    o.posix_c2h.sys_write.req.buf[5]  = ',';
    o.posix_c2h.sys_write.req.buf[6]  = ' ';
    o.posix_c2h.sys_write.req.buf[7]  = 'W';
    o.posix_c2h.sys_write.req.buf[8]  = 'o';
    o.posix_c2h.sys_write.req.buf[9]  = 'r'; 
    o.posix_c2h.sys_write.req.buf[10] = 'l';
    o.posix_c2h.sys_write.req.buf[11] = 'd';
    o.posix_c2h.sys_write.req.buf[12] = '!';
    o.posix_c2h.sys_write.req.buf[13] = '\n';
    o.posix_c2h.sys_write.req.nbyte = 14;
    o.posix_c2h.sys_write.req.fildes = fildes;
    o.posix_c2h.sys_write.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.posix_h2c.sys_write.req_ready)
    {
      // Then wait for response
      state = WRITE_RESP;
    }
  }
  else if(state==WRITE_RESP)
  {
    // Wait here ready for response
    o.posix_c2h.sys_write.resp_ready = 1;
    // Until we get valid response
    if(i.posix_h2c.sys_write.resp.valid)
    { 
      // Would do something based on how many bytes were written
      //    i.posix_h2c.sys_write.resp.nbyte
      // But for now assume it went well, try to write again now
      state = WRITE_REQ;
    }
  }
  
  return o;
}

// Include wrapper connecting 'main' to fosix 'host'
#include "main_wrapper.c"
