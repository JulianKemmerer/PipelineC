/*
 This code describes a state machine that 
 reads "/tmp/in" from the host into FPGA block ram.
 Then writes "/tmp/out" on the host with contents of that block ram.
 "Loopback the file from input to output using BRAM buffer on FPGA"
*/

#include "fosix.c" // FPGA POSIX?

// Primary state machine to do the steps of
typedef enum state_t {
  RESET, // Starting state
  STDOUT_OPEN, // For debug open stdout to keep track of progress 
  PRINT_OPEN_IN, // Print info about opening input file
  IN_OPEN, // Open the input file
  PRINT_OPEN_BRAM, // Print info about opening bram file
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
size_t num_bytes; // Temp holder for number of bytes
fd_t stdout_fd; // File descriptor for /dev/stdout
fd_t in_fd; // File descriptor for /tmp/in
fd_t out_fd; // File descriptor for /tmp/out
fd_t bram_fd; // File descriptor for BRAM

// Subroutine registers for common/repeated functionality
typedef enum subroutine_state_t {
  IDLE,
  OPEN_REQ,
  OPEN_RESP,
  WRITE_REQ,
  WRITE_RESP,
  READ_REQ,
  READ_RESP,
  CLOSE_REQ,
  CLOSE_RESP,
  RETURN_STATE
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

outputs_t main(inputs_t i, uint1_t rst)
{
  // Default output/reset/null values
  outputs_t o;
  o.c2h = POSIX_C2H_T_NULL();
  
  // Control of subroutine state machine from primary state
  subroutine_state_t sub_start_state = IDLE;
  
  //////////////////////////////////////////////////////////////////////
  // Primary state machine 
  if(state==RESET)
  {
    state = STDOUT_OPEN;
  }
  else if(state==STDOUT_OPEN)
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
    // State to return to from subroutine
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
    // State to return to from subroutine
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
    // State to return to from subroutine
    sub_return_state = PRINT_OPEN_BRAM;
    // Subroutine return values
    in_fd = sub_fd; // File descriptor
  }
  else if(state==PRINT_OPEN_BRAM)
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
    sub_io_buf[8]  = 'b';
    sub_io_buf[9]  = 'r';
    sub_io_buf[10] = 'a';
    sub_io_buf[11] = 'm';
    sub_io_buf[12] = '\n';
    sub_io_buf[13] = 0; // Null term
    sub_io_buf_nbytes = 14;
    sub_fd = stdout_fd;
    sub_start_state = WRITE_REQ;
    // State to return to from subroutine
    sub_return_state = BRAM_OPEN0;
    // Subroutine return values
    //    not used
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
    // State to return to from subroutine
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
    // State to return to from subroutine
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
    // State to return to from subroutine
    sub_return_state = BRAM_WRITE;
    // Subroutine return buffer sub_io_buf 
    // need not be read/modified/saved elsewhere
    // output from read is input to write next
    // Can only do since no syscalls dont have BOTH input and output buffers
    // Save number of bytes to write next
    num_bytes = sub_io_buf_nbytes_ret;
  }
  else if(state==BRAM_WRITE)
  {
    // Write to BRAM num_bytes if have bytes to write
    if(num_bytes > 0)
    {
      // Subroutine arguments
      // sub_io_buf = sub_io_buf; // buf from IN_READ is buf for write too
      sub_io_buf_nbytes = num_bytes; // Bytes returned from read is how many to write now
      sub_fd = bram_fd;
      sub_start_state = WRITE_REQ;
      // State to return to from subroutine
      sub_return_state = IN_READ;
      // Subroutine return values
      //    not used
    }
    else
    {
      // Otherwise time to close BRAM
      state = BRAM_CLOSE;
    }
  }
  else if(state==BRAM_CLOSE)
  {
    // Close BRAM file
    // Subroutine arguments
    sub_fd = bram_fd;
    sub_start_state = CLOSE_REQ;
    // State to return to from subroutine
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
    // State to return to from subroutine
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
    // State to return to from subroutine
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
    // State to return to from subroutine
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
    // State to return to from subroutine
    sub_return_state = OUT_WRITE;
    // Subroutine return buffer sub_io_buf 
    // need not be read/modified/saved elsewhere
    // output from read is input to write next
    // Can only do since no syscalls dont have BOTH input and output buffers
    // Save number of bytes to write next
    num_bytes = sub_io_buf_nbytes_ret;
  }
  else if(state==OUT_WRITE)
  {
    // Write to output file if have bytes to write
    if(num_bytes > 0)
    {
      // Subroutine arguments
      // sub_io_buf = sub_io_buf; // buf from BRAM_READ is buf for write too
      sub_io_buf_nbytes = num_bytes; // Bytes returned from read is how many to write now
      sub_fd = out_fd;
      sub_start_state = WRITE_REQ;
      // State to return to from subroutine
      sub_return_state = BRAM_READ;
      // Subroutine return values
      //    not used
    }
    else
    {
      // Otherwise reached end of reading BRAM data, done
      state = PRINT_DONE;
    }
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
    // State to return to from subroutine
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
  else if(sub_state == OPEN_REQ)
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
      sub_state = RETURN_STATE;
    }
  }
  else if(sub_state == WRITE_REQ)
  {
    // Request to write
    o.c2h.sys_write.req.buf = sub_io_buf;
    o.c2h.sys_write.req.nbyte = sub_io_buf_nbytes;
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
      sub_io_buf_nbytes_ret = i.h2c.sys_write.resp.nbyte;
      // Return to primary state machine
      sub_state = RETURN_STATE;
    }
  }
  else if(sub_state == READ_REQ)
  {
    // Request to read
    o.c2h.sys_read.req.nbyte = sub_io_buf_nbytes;
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
      sub_io_buf_nbytes_ret = i.h2c.sys_read.resp.nbyte;
      sub_io_buf = i.h2c.sys_read.resp.buf;
      // Return to primary state machine
      sub_state = RETURN_STATE;
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
      sub_state = RETURN_STATE;
    }
  }
  else if(sub_state==RETURN_STATE)
  {
    // This state allows primary state machine to get return values
    state = sub_return_state;
    sub_state = IDLE;
  }
  
  if(rst)
  {
    state = RESET;
    sub_state = IDLE;
  }
  
  return o;
}

// Include wrapper connecting 'main' to fosix 'host'
#include "main_wrapper.c"
