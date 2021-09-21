#include "compiler.h"

#include "fosix.c" // FPGA POSIX?

void main()
{
  fosix_fd_t stdout_fd; // File descriptor for /dev/stdout
  
  // Open files for user IO
  stdout_fd = open("/dev/stdout");
  while(1)
  {
    STRWRITE(stdout_fd, "Hello World\n")
  }
}
// Derived fsm from main
#include "main_FSM.h"

// Wrap up main FSM as top level
MAIN_MHZ(main_wrapper, UART_CLK_MHZ) // Use uart clock for main
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}
