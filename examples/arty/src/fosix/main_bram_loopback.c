/*
 This code describes a state machine that 
 reads "/tmp/in" from the host OS into FPGA block ram.
 Then writes "/tmp/out" on the host OS with contents of that block ram.
 "Loopback the file from input to output using BRAM buffer on FPGA"
reset;
gcc host.c -o host -I ../../../../
rm /tmp/in;
rm -f /tmp/out;
head -c 16384 < /dev/urandom > /tmp/in
sudo ./host
hexdump -Cv /tmp/in -n 128
sudo hexdump -Cv /tmp/out -n 128
*/
#include "compiler.h"

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
fosix_size_t num_bytes; // Temp holder for number of bytes
fosix_fd_t stdout_fd; // File descriptor for /dev/stdout
fosix_fd_t in_fd; // File descriptor for /tmp/in
fosix_fd_t out_fd; // File descriptor for /tmp/out
fosix_fd_t bram_fd; // File descriptor for BRAM


// Some repeated logic would probably benefit from some macros...TODO...
MAIN_MHZ(main, UART_CLK_MHZ) // Use uart clock for main
void main()
{
  // Read inputs
  fosix_sys_to_proc_t sys_to_proc;
  WIRE_READ(fosix_sys_to_proc_t, sys_to_proc, main_sys_to_proc)  
  // Default output/reset/null values
  fosix_proc_to_sys_t proc_to_sys = POSIX_PROC_TO_SYS_T_NULL();

  // Syscall (_PRE/POST MACRO?)
  // State for using syscalls
  static syscall_io_t syscall_io_reg;
  // Syscall IO signaling keeps regs contents
  syscall_io_t syscall_io = syscall_io_reg;
  // Other than start bit which auto clears
  syscall_io.start = 0;

  // Primary state machine 
  if(state==RESET)
  {
    state = STDOUT_OPEN;
  }
  else if(state==STDOUT_OPEN)
  {
    // Open /dev/stdout (stdout on driver program on host)
    // Subroutine arguments
    syscall_io.path[0]  = '/';
    syscall_io.path[1]  = 'd';
    syscall_io.path[2]  = 'e';
    syscall_io.path[3]  = 'v';
    syscall_io.path[4]  = '/';
    syscall_io.path[5]  = 's';
    syscall_io.path[6]  = 't';
    syscall_io.path[7]  = 'd';
    syscall_io.path[8]  = 'o';
    syscall_io.path[9]  = 'u';
    syscall_io.path[10] = 't';
    syscall_io.path[11] = 0; // Null term
    syscall_io.start = 1;
    syscall_io.num = FOSIX_OPEN;
    if(syscall_io.done)
    {
      // Syscall return values
      stdout_fd = syscall_io.fd; // File descriptor
      // State to return to from syscall
      state = PRINT_OPEN_IN;
    }
  }
  else if(state==PRINT_OPEN_IN)
  {
    // Print debug
    // Subroutine arguments
    syscall_io.buf[0]  = 'O';
    syscall_io.buf[1]  = 'p';
    syscall_io.buf[2]  = 'e';
    syscall_io.buf[3]  = 'n';
    syscall_io.buf[4]  = 'i';
    syscall_io.buf[5]  = 'n';
    syscall_io.buf[6]  = 'g';
    syscall_io.buf[7]  = ' ';
    syscall_io.buf[8]  = 'i';
    syscall_io.buf[9]  = 'n';
    syscall_io.buf[10] = '\n';
    syscall_io.buf_nbytes = 11;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = IN_OPEN;
      // Syscall return values
      //    not used
    }
  }
  else if(state==IN_OPEN)
  {
    // Open /tmp/in on host
    // Subroutine arguments
    syscall_io.path[0]  = '/';
    syscall_io.path[1]  = 't';
    syscall_io.path[2]  = 'm';
    syscall_io.path[3]  = 'p';
    syscall_io.path[4]  = '/';
    syscall_io.path[5]  = 'i';
    syscall_io.path[6]  = 'n';
    syscall_io.path[7]  = 0; // Null term
    syscall_io.start = 1;
    syscall_io.num = FOSIX_OPEN;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = PRINT_OPEN_BRAM;
      // Syscall return values
      in_fd = syscall_io.fd; // File descriptor
    }
  }
  else if(state==PRINT_OPEN_BRAM)
  {
    // Print debug
    // Subroutine arguments
    syscall_io.buf[0]  = 'O';
    syscall_io.buf[1]  = 'p';
    syscall_io.buf[2]  = 'e';
    syscall_io.buf[3]  = 'n';
    syscall_io.buf[4]  = 'i';
    syscall_io.buf[5]  = 'n';
    syscall_io.buf[6]  = 'g';
    syscall_io.buf[7]  = ' ';
    syscall_io.buf[8]  = 'b';
    syscall_io.buf[9]  = 'r';
    syscall_io.buf[10] = 'a';
    syscall_io.buf[11] = 'm';
    syscall_io.buf[12] = '\n';
    syscall_io.buf[13] = 0; // Null term
    syscall_io.buf_nbytes = 14;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = BRAM_OPEN0;
      // Syscall return values
      //    not used
    }
  }
  else if(state==BRAM_OPEN0 | state==BRAM_OPEN1)
  {
    // Open bram
    // Subroutine arguments
    syscall_io.path[0]  = 'b';
    syscall_io.path[1]  = 'r';
    syscall_io.path[2]  = 'a';
    syscall_io.path[3]  = 'm';
    syscall_io.path[4]  = 0; // Null term
    syscall_io.start = 1;
    syscall_io.num = FOSIX_OPEN;
    if(syscall_io.done)
    {
      // State to return to from syscall
      if(state==BRAM_OPEN0)
      {
        state = PRINT_READ_IN;
      }
      else // BRAM_OPEN1
      {
        state = PRINT_WRITE_OUT;
      }
      // Syscall return values
      bram_fd = syscall_io.fd; // File descriptor
    }
  }
  else if(state==PRINT_READ_IN)
  {
    // Print debug
    // Subroutine arguments
    syscall_io.buf[0]  = 'R';
    syscall_io.buf[1]  = 'e';
    syscall_io.buf[2]  = 'a';
    syscall_io.buf[3]  = 'd';
    syscall_io.buf[4]  = 'i';
    syscall_io.buf[5]  = 'n';
    syscall_io.buf[6]  = 'g';
    syscall_io.buf[7]  = ' ';
    syscall_io.buf[8]  = 'i';
    syscall_io.buf[9]  = 'n';
    syscall_io.buf[10] = '\n';
    syscall_io.buf_nbytes = 11;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = IN_READ;
      // Syscall return values
      //    not used
    }
  }
  else if(state==IN_READ)
  {
    // Read from the input file
    // Subroutine arguments
    syscall_io.buf_nbytes = BRAM_WIDTH;
    syscall_io.fd = in_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_READ;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = BRAM_WRITE;
      // Subroutine return buffer sub_io_buf 
      // need not be read/modified/saved elsewhere
      // output from read is input to write next
      // Can only do since no syscalls dont have BOTH input and output buffers
      // Save number of bytes to write next
      num_bytes = syscall_io.buf_nbytes_ret;
    }
  }
  else if(state==BRAM_WRITE)
  {
    // Write to BRAM num_bytes if have bytes to write
    if(num_bytes > 0)
    {
      // Subroutine arguments
      // sub_io_buf = sub_io_buf; // buf from IN_READ is buf for write too
      syscall_io.buf_nbytes = num_bytes; // Bytes returned from read is how many to write now
      syscall_io.fd = bram_fd;
      syscall_io.start = 1;
      syscall_io.num = FOSIX_WRITE;
      if(syscall_io.done)
      {
        // State to return to from syscall
        state = IN_READ;
        // Syscall return values
        //    not used
      }
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
    syscall_io.fd = bram_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_CLOSE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = PRINT_OPEN_OUT;
      // Syscall return values
      //    not used
    }
  }
  else if(state==PRINT_OPEN_OUT)
  {
    // Print debug
    // Subroutine arguments
    syscall_io.buf[0]  = 'O';
    syscall_io.buf[1]  = 'p';
    syscall_io.buf[2]  = 'e';
    syscall_io.buf[3]  = 'n';
    syscall_io.buf[4]  = 'i';
    syscall_io.buf[5]  = 'n';
    syscall_io.buf[6]  = 'g';
    syscall_io.buf[7]  = ' ';
    syscall_io.buf[8]  = 'o';
    syscall_io.buf[9]  = 'u';
    syscall_io.buf[10] = 't';
    syscall_io.buf[11] = '\n';
    syscall_io.buf_nbytes = 12;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = OUT_OPEN;
      // Syscall return values
      //    not used
    }
  }
  else if(state==OUT_OPEN)
  {
    // Open /tmp/out on host
    // Subroutine arguments
    syscall_io.path[0]  = '/';
    syscall_io.path[1]  = 't';
    syscall_io.path[2]  = 'm';
    syscall_io.path[3]  = 'p';
    syscall_io.path[4]  = '/';
    syscall_io.path[5]  = 'o';
    syscall_io.path[6]  = 'u';
    syscall_io.path[7]  = 't'; 
    syscall_io.path[8]  = 0; // Null term
    syscall_io.start = 1;
    syscall_io.num = FOSIX_OPEN;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = BRAM_OPEN1;
      // Syscall return values
      out_fd = syscall_io.fd; // File descriptor
    }
  }
  else if(state==PRINT_WRITE_OUT)
  {
    // Print debug
    // Subroutine arguments
    syscall_io.buf[0]  = 'W';
    syscall_io.buf[1]  = 'r';
    syscall_io.buf[2]  = 'i';
    syscall_io.buf[3]  = 't';
    syscall_io.buf[4]  = 'i';
    syscall_io.buf[5]  = 'n';
    syscall_io.buf[6]  = 'g';
    syscall_io.buf[7]  = ' ';
    syscall_io.buf[8]  = 'o';
    syscall_io.buf[9]  = 'u';
    syscall_io.buf[10] = 't';
    syscall_io.buf[11] = '\n';
    syscall_io.buf_nbytes = 12;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = BRAM_READ;
      // Syscall return values
      //    not used
    }
  }
  else if(state==BRAM_READ)
  {
    // Read from BRAM file
    // Subroutine arguments
    syscall_io.buf_nbytes = BRAM_WIDTH;
    syscall_io.fd = bram_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_READ;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = OUT_WRITE;
      // Subroutine return buffer sub_io_buf 
      // need not be read/modified/saved elsewhere
      // output from read is input to write next
      // Can only do since no syscalls dont have BOTH input and output buffers
      // Save number of bytes to write next
      num_bytes = syscall_io.buf_nbytes_ret;
    }
  }
  else if(state==OUT_WRITE)
  {
    // Write to output file if have bytes to write
    if(num_bytes > 0)
    {
      // Subroutine arguments
      // sub_io_buf = sub_io_buf; // buf from BRAM_READ is buf for write too
      syscall_io.buf_nbytes = num_bytes; // Bytes returned from read is how many to write now
      syscall_io.fd = out_fd;
      syscall_io.start = 1;
      syscall_io.num = FOSIX_WRITE;
      if(syscall_io.done)
      {
        // State to return to from syscall
        state = BRAM_READ;
        // Syscall return values
        //    not used
      }
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
    syscall_io.buf[0]  = 'D';
    syscall_io.buf[1]  = 'o';
    syscall_io.buf[2]  = 'n';
    syscall_io.buf[3]  = 'e';
    syscall_io.buf[4]  = '\n';
    syscall_io.buf_nbytes = 5;
    syscall_io.fd = stdout_fd;
    syscall_io.start = 1;
    syscall_io.num = FOSIX_WRITE;
    if(syscall_io.done)
    {
      // State to return to from syscall
      state = DONE;
      // Syscall return values
      //    not used
    }
  }
  
  // System call 'FSM' running when asked to start  _POST MACRO?
  syscall_io.done = 0; // Auto clear done
  if(syscall_io_reg.start)
  {
    syscall_func_t sc = syscall_func(sys_to_proc, syscall_io_reg);
    proc_to_sys = sc.proc_to_sys;
    syscall_io = sc.syscall_io;
  }
  // Ignore start bit if during done time
  if(syscall_io.done | syscall_io_reg.done)
  {
    syscall_io.start = 0;
  }
  syscall_io_reg = syscall_io;
  
  /*
  if(rst)
  {
    state = RESET;
    sub_state = IDLE;
  }
  */
  
  // Write outputs
  WIRE_WRITE(fosix_proc_to_sys_t, main_proc_to_sys, proc_to_sys)
}
