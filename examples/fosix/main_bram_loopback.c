/*
 This code describes a state machine that 
 reads "/tmp/in" from the host OS into FPGA block ram.
 Then writes "/tmp/out" on the host OS with contents of that block ram.
 "Loopback the file from input to output using BRAM buffer on FPGA"
reset;
gcc host.c -o host -I ../../../../
rm /tmp/in;
sudo rm -f /tmp/out;
head -c 16384 < /dev/urandom > /tmp/in
sudo ./host
#hexdump -Cv /tmp/in -n 128
#sudo hexdump -Cv /tmp/out -n 128
sudo diff /tmp/in /tmp/out
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
// Stateful global variables
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
  fosix_proc_to_sys_t proc_to_sys;

  // Declare syscall connection wire of type syscall_io_t
  // Use wire to make system calls from FSM below
  SYSCALL_DECL(syscall_io)
  
  // Syscall return mostly unused
  fosix_size_t unused = 0;

  // Primary state machine 
  if(state==RESET){
    state = STDOUT_OPEN;
  }else if(state==STDOUT_OPEN){
    // Open /dev/stdout (stdout on driver program on host)
    OPEN_THEN(syscall_io, stdout_fd, "/dev/stdout",\
      state = PRINT_OPEN_IN;)
  }else if(state==PRINT_OPEN_IN){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Opening /tmp/in\n",\
     state = IN_OPEN;)
  }else if(state==IN_OPEN){
    // Open /tmp/in on host
    OPEN_THEN(syscall_io, in_fd, "/tmp/in",\
      state = PRINT_OPEN_BRAM;)
  }else if(state==PRINT_OPEN_BRAM){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Opening bram\n",\
      state = BRAM_OPEN0;)
  }else if(state==BRAM_OPEN0 | state==BRAM_OPEN1){
    // Open bram
    OPEN_THEN(syscall_io, bram_fd, "bram",\
      if(state==BRAM_OPEN0){  \
        state = PRINT_READ_IN;  \
      } else /* BRAM_OPEN1*/ { \
        state = PRINT_WRITE_OUT; \
      })
  }else if(state==PRINT_READ_IN){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Reading /tmp/in\n",\
      state = IN_READ;)
  }else if(state==IN_READ){
    // Read from the input file
    // Reusing subroutine buffer syscall_io.buf for return
    // Save number of bytes to write next
    READ_THEN(syscall_io, num_bytes, in_fd, syscall_io.buf, BRAM_WIDTH,\
      state = BRAM_WRITE;)
  }else if(state==BRAM_WRITE){
    // Write to BRAM num_bytes if have bytes to write
    if(num_bytes > 0){
      WRITE_THEN(syscall_io, unused, bram_fd, syscall_io.buf, num_bytes,\
        state = IN_READ;)
    }else{
      // Otherwise time to close BRAM
      state = BRAM_CLOSE;
    }
  }else if(state==BRAM_CLOSE){
    // Close BRAM file
    CLOSE_THEN(syscall_io, unused, bram_fd,\
      state = PRINT_OPEN_OUT;)
  }else if(state==PRINT_OPEN_OUT){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Opening /tmp/out\n",\
      state = OUT_OPEN;)
  }else if(state==OUT_OPEN){
    // Open /tmp/out on host
    OPEN_THEN(syscall_io, out_fd, "/tmp/out",\
      state = BRAM_OPEN1;)
  }else if(state==PRINT_WRITE_OUT){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Writing /tmp/out\n",\
      state = BRAM_READ;)
  }else if(state==BRAM_READ){
    // Read from BRAM file
    // Reusing subroutine buffer syscall_io.buf for return
    // Save number of bytes to write next
    READ_THEN(syscall_io, num_bytes, bram_fd, syscall_io.buf, BRAM_WIDTH,\
      state = OUT_WRITE;)
  }else if(state==OUT_WRITE){
    // Write to output file if have bytes to write
    if(num_bytes > 0){
      // buf from BRAM_READ is buf for write too
      WRITE_THEN(syscall_io, unused, out_fd, syscall_io.buf, num_bytes,\
        state = BRAM_READ;)
    }else{
      // Otherwise reached end of reading BRAM data, done
      state = PRINT_DONE;
    }
  }else if(state==PRINT_DONE){
    // Print debug
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Done\n",\
      state = DONE;)
  }
  
  // System call 'FSM' running when asked to start
  SYSCALL(syscall_io, sys_to_proc, proc_to_sys)
  
  // Write outputs
  WIRE_WRITE(fosix_proc_to_sys_t, main_proc_to_sys, proc_to_sys)
}
