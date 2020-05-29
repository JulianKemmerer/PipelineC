/*
 This code describes a state machine that 
 reads "/tmp/in" into block ram.
 Then writes "/tmp/out" with contents of block ram.
 "Loopback the file from input to output using BRAM buffer"
*/

#include "fosix.c" // FPGA POSIX?

// Primary state machine to do the steps of
typedef enum state_t {
  STDOUT_OPEN, // For debug open stdout to keep track of progress (starting state)
  PRINT_OPEN_IN, // Print info about opening input file
	IN_OPEN, // Open the input file 
  BRAM_OPEN0, // Open the BRAM file for first time
  PRINT_READ_IN, // Print info about reading input file
  //
  // Input read loop states  
  IN_READ, // Read BRAM_WIDTH bytes at a time from input file
  BRAM_WRITE, // Write BRAM_WIDTH bytes at a time into BRAM
  //
  BRAM_CLOSE, // Close the BRAM file to reset file offset
  PRINT_OPEN_OUT, // Print info about opening output file
  OUT_OPEN, // Open the output file
  BRAM_OPEN1, // Open the BRAM file for second time
  PRINT_WRITE_OUT, // Print info about writing output file
  //
  // Output write loop states
  BRAM_READ, // Read BRAM_WIDTH bytes from BRAM
  OUT_WRITE, // Write BRAM_WIDTH bytes to output file
  //
  PRINT_DONE, // Print info about being done
  DONE // Stays in this state forever (until FPGA bitstream reload) 
} state_t;
state_t state;
fd_t stdout_fd; // File descriptor for /dev/stdout
fd_t in_fd; // File descriptor for /tmp/in
fd_t out_fd; // File descriptor for /tmp/out
fd_t bram_fd; // File descriptor for BRAM

// Subroutine registers for common/repeated functionality
typedef enum subroutine_state_t {
  IDLE,
  OPEN_REQ,
  OPEN_RESP,
  PRINT_REQ,
  PRINT_RESP,
  CLOSE_REQ,
  CLOSE_RESP,
  RETURN
} subroutine_state_t;
subroutine_state_t sub_state; // Subroutine state
state_t sub_return_state; // Primary state machine state to return to
fd_t sub_fd; // File descriptor for subroutine
char sub_path[PATH_SIZE]; // Path buf for open()
uint8_t sub_io_buf[BUF_SIZE]; // IO buf for write+read
size_t sub_io_buf_nbytes; // Input number of bytes
size_t sub_io_buf_nbytes_ret; // Return count of bytes

// Uses posix busses for IO
typedef struct inputs_t
{
	 posix_h2c_t h2c;
} inputs_t;
typedef struct outputs_t
{
  posix_c2h_t c2h;
} outputs_t;

// Some repeated logic would probably benefit from some macros...TODO...

outputs_t main(inputs_t i)
{
  // Default output/reset/null values
  outputs_t o;
  o.c2h = POSIX_C2H_T_NULL();
  
  // Control of subroutine state machine from primary state
  subroutine_state_t sub_start_state = IDLE;
  
  //////////////////////////////////////////////////////////////////////
  // Primary state machine 
  if(state==STDOUT_OPEN)
  {
    // Open /dev/stdout (stdout on driver program on host)
    // Subroutine arguments
    sub_path[0]  = '/';
    sub_path[1]  = 'd';
    sub_path[2]  = 'e';
    sub_path[3]  = 'v';
    sub_path[4]  = '/';
    sub_path[5]  = 's';
    sub_path[6]  = 't';
    sub_path[7]  = 'd';
    sub_path[8]  = 'o';
    sub_path[9]  = 'u';
    sub_path[10] = 't';
    sub_path[11] = 0; // Null term
    sub_start_state = OPEN_REQ;
    // State to return to
    sub_return_state = PRINT_OPEN_IN;
    // Subroutine return values
    stdout_fd = sub_fd; // File descriptor
  }
  else if(state==PRINT_OPEN_IN)
  {
    // Print debug
    // Subroutine arguments
    sub_io_buf[0]  = 'O';
    sub_io_buf[1]  = 'p';
    sub_io_buf[2]  = 'e';
    sub_io_buf[3]  = 'n';
    sub_io_buf[4]  = 'i';
    sub_io_buf[5]  = 'n';
    sub_io_buf[6]  = 'g';
    sub_io_buf[7]  = ' ';
    sub_io_buf[8]  = 'i';
    sub_io_buf[9]  = 'n';
    sub_io_buf[10] = '\n';
    sub_io_buf_nbytes = 11;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    sub_return_state = IN_OPEN;
    // Subroutine return values
    //    not used
  }
  else if(state==IN_OPEN)
  {
    // Open /tmp/in on host
    // Subroutine arguments
    sub_path[0]  = '/';
    sub_path[1]  = 't';
    sub_path[2]  = 'm';
    sub_path[3]  = 'p';
    sub_path[4]  = '/';
    sub_path[5]  = 'i';
    sub_path[6]  = 'n';
    sub_path[7]  = 0; // Null term
    sub_start_state = OPEN_REQ;
    // State to return to
    sub_return_state = BRAM_OPEN0;
    // Subroutine return values
    in_fd = sub_fd; // File descriptor
  }
  else if(state==BRAM_OPEN0 | state==BRAM_OPEN1)
  {
    // Open bram
    // Subroutine arguments
    sub_path[0]  = 'b';
    sub_path[1]  = 'r';
    sub_path[2]  = 'a';
    sub_path[3]  = 'm';
    sub_path[4]  = 0; // Null term
    sub_start_state = OPEN_REQ;
    // State to return to
    if(state==BRAM_OPEN0)
    {
      sub_return_state = PRINT_READ_IN;
    }
    else // BRAM_OPEN1
    {
      sub_return_state = PRINT_WRITE_OUT;
    }
    // Subroutine return values
    bram_fd = sub_fd; // File descriptor
  }
  else if(state==PRINT_READ_IN)
  {
    // Print debug
    // Subroutine arguments
    sub_io_buf[0]  = 'R';
    sub_io_buf[1]  = 'e';
    sub_io_buf[2]  = 'a';
    sub_io_buf[3]  = 'd';
    sub_io_buf[4]  = 'i';
    sub_io_buf[5]  = 'n';
    sub_io_buf[6]  = 'g';
    sub_io_buf[7]  = ' ';
    sub_io_buf[8]  = 'i';
    sub_io_buf[9]  = 'n';
    sub_io_buf[10] = '\n';
    sub_io_buf_nbytes = 11;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    sub_return_state = IN_READ;
    // Subroutine return values
    //    not used
  }
  else if(state==IN_READ)
  {
    // Read from the input file
    // Subroutine arguments
    sub_io_buf_nbytes = BRAM_WIDTH;
    sub_fd = in_fd;
    sub_start_state = READ_REQ;
    // State to return to
    sub_return_state = BRAM_WRITE;
    // Subroutine return values sub_io_buf, io_buf_nbyte_ret
    // Need not be read/modified/saved elsewhere
    // since use those buffers for BRAM write next
  }
  else if(state==BRAM_WRITE)
  {
    // Write to BRAM
    // Subroutine arguments
    // sub_io_buf = sub_io_buf; // buf from IN_READ is buf for write too
    sub_io_buf_nbytes = io_buf_nbyte_ret; // Bytes returned from read is how many to write now
    sub_fd = bram_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    // Close the BRAM if reached end of input file
    if(sub_io_buf_nbytes == 0)
    {
      sub_return_state = BRAM_CLOSE;
    }
    else
    {
      // Otherwise keep reading
      sub_return_state = IN_READ;
    }
    // Subroutine return values
    //    not used
  }
  else if(state==BRAM_CLOSE)
  {
    // Close BRAM file
    // Subroutine arguments
    sub_fd = bram_fd;
    sub_start_state = CLOSE_REQ;
    // State to return to
    sub_return_state = PRINT_OPEN_OUT;
    // Subroutine return values
    //    not used
  }
  else if(state==PRINT_OPEN_OUT)
  {
    // Print debug
    // Subroutine arguments
    sub_io_buf[0]  = 'O';
    sub_io_buf[1]  = 'p';
    sub_io_buf[2]  = 'e';
    sub_io_buf[3]  = 'n';
    sub_io_buf[4]  = 'i';
    sub_io_buf[5]  = 'n';
    sub_io_buf[6]  = 'g';
    sub_io_buf[7]  = ' ';
    sub_io_buf[8]  = 'o';
    sub_io_buf[9]  = 'u';
    sub_io_buf[10] = 't';
    sub_io_buf[11] = '\n';
    sub_io_buf_nbytes = 12;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    sub_return_state = OUT_OPEN;
    // Subroutine return values
    //    not used
  }
  else if(state==OUT_OPEN)
  {
    // Open /tmp/out on host
    // Subroutine arguments
    sub_path[0]  = '/';
    sub_path[1]  = 't';
    sub_path[2]  = 'm';
    sub_path[3]  = 'p';
    sub_path[4]  = '/';
    sub_path[5]  = 'o';
    sub_path[6]  = 'u';
    sub_path[7]  = 't'; 
    sub_path[8]  = 0; // Null term
    sub_start_state = OPEN_REQ;
    // State to return to
    sub_return_state = BRAM_OPEN1;
    // Subroutine return values
    out_fd = sub_fd; // File descriptor
  }
  else if(state==PRINT_WRITE_OUT)
  {
    // Print debug
    // Subroutine arguments
    sub_io_buf[0]  = 'W';
    sub_io_buf[1]  = 'r';
    sub_io_buf[2]  = 'i';
    sub_io_buf[3]  = 't';
    sub_io_buf[4]  = 'i';
    sub_io_buf[5]  = 'n';
    sub_io_buf[6]  = 'g';
    sub_io_buf[7]  = ' ';
    sub_io_buf[8]  = 'o';
    sub_io_buf[9]  = 'u';
    sub_io_buf[10] = 't';
    sub_io_buf[11] = '\n';
    sub_io_buf_nbytes = 12;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    sub_return_state = BRAM_READ;
    // Subroutine return values
    //    not used
  }
  else if(state==BRAM_READ)
  {
    // Read from BRAM file
    // Subroutine arguments
    sub_io_buf_nbytes = BRAM_WIDTH;
    sub_fd = bram_fd;
    sub_start_state = READ_REQ;
    // State to return to
    sub_return_state = OUT_WRITE;
    // Subroutine return values sub_io_buf, io_buf_nbyte_ret
    // Need not be read/modified/saved elsewhere
    // since use those buffers for out write next
  }
  else if(state==OUT_WRITE)
  {
    // Write to output file
    // Subroutine arguments
    // sub_io_buf = sub_io_buf; // buf from BRAM_READ is buf for write too
    sub_io_buf_nbytes = io_buf_nbyte_ret; // Bytes returned from read is how many to write now
    sub_fd = out_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    // Done if reached end of BRAM file
    if(sub_io_buf_nbytes == 0)
    {
      sub_return_state = PRINT_DONE;
    }
    else
    {
      // Otherwise keep reading
      sub_return_state = BRAM_READ;
    }
    // Subroutine return values
    //    not used
  }
  else if(state==PRINT_DONE)
  {
    // Print debug
    // Subroutine arguments
    sub_io_buf[0]  = 'D';
    sub_io_buf[1]  = 'o';
    sub_io_buf[2]  = 'n';
    sub_io_buf[3]  = 'e';
    sub_io_buf[4]  = '\n';
    sub_io_buf_nbytes = 5;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to
    sub_return_state = DONE;
    // Subroutine return values
    //    not used
  }
  
  //////////////////////////////////////////////////////////////////////
  // Subroutine state machine 
  if(sub_state == IDLE)
  {
    // Accept state changes from primary state machine
    sub_state = sub_start_state;
  }
  if(sub_state == OPEN_REQ)
  {
    // Request to open
    o.c2h.sys_open.req.path = sub_path;
    o.c2h.sys_open.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_open.req_ready)
    {
      // Then wait for response
      sub_state = OPEN_RESP;
    }
  }
  else if(sub_state==OPEN_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_open.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_open.resp.valid)
    { 
      // Save file descriptor
      sub_fd = i.h2c.sys_open.resp.fildes;
      // Return to primary state machine
      sub_state = RETURN;
    }
  }
  else if(sub_state == WRITE_REQ)
  {
    // Request to write
    o.c2h.sys_write.req.buf = sub_io_buf;
    o.c2h.sys_write.req.nbytes = sub_io_buf_nbytes;
    o.c2h.sys_write.req.fildes = sub_fd;
    o.c2h.sys_write.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_write.req_ready)
    {
      // Then wait for response
      sub_state = WRITE_RESP;
    }
  }
  else if(sub_state == WRITE_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_write.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_write.resp.valid)
    { 
      // Save num bytes
      sub_io_buf_nbytes_ret = i.h2c.sys_write.resp.nbytes;
      // Return to primary state machine
      sub_state = RETURN;
    }
  }
  else if(sub_state == READ_REQ)
  {
    // Request to read
    o.c2h.sys_read.req.nbytes = sub_io_buf_nbytes;
    o.c2h.sys_read.req.fildes = sub_fd;
    o.c2h.sys_read.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_read.req_ready)
    {
      // Then wait for response
      sub_state = READ_RESP;
    }
  }
  else if(sub_state == READ_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_read.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_read.resp.valid)
    { 
      // Save num bytes and bytes
      sub_io_buf_nbytes_ret = i.h2c.sys_read.resp.nbytes;
      sub_io_buf = i.h2c.sys_read.resp.buf;
      // Return to primary state machine
      sub_state = RETURN;
    }
  }
  else if(sub_state == CLOSE_REQ)
  {
    // Request to close
    o.c2h.sys_close.req.fildes = sub_fd;
    o.c2h.sys_close.req.valid = 1;
    // Keep trying to request until finally was ready
    if(i.h2c.sys_close.req_ready)
    {
      // Then wait for response
      sub_state = CLOSE_RESP;
    }
  }
  else if(sub_state == CLOSE_RESP)
  {
    // Wait here ready for response
    o.c2h.sys_close.resp_ready = 1;
    // Until we get valid response
    if(i.h2c.sys_close.resp.valid)
    { 
      // Not looking at err code
      // Return to primary state machine
      sub_state = RETURN;
    }
  }
  else if(sub_state==RETURN)
  {
    // This state allows primary state machine to get return values
    state = sub_return_state;
    sub_state = IDLE;
  }
  
  return o;
}

// Include wrapper connecting 'main' to fosix 'host'
#include "main_wrapper.c"
