/*
 This code describes a state machine that plays a guess the number game with the user.
*/
#include "compiler.h"

#include "fosix.c" // FPGA POSIX?

// Convert string to integer
#define GUESS_MIN 0
#define GUESS_MAX 99
#define USER_GUESS_BUF_SIZE 3 // Guess between "0\n"-"99\n"
#define guess_t uint7_t 
#define user_guess_buf_size_t uint3_t


// atoi() sized for this small example
guess_t my_atoi(char str[USER_GUESS_BUF_SIZE])
{
  guess_t res = 0;
  uint32_t i;
  uint1_t reached_end = 0;
  for(i=0; i<USER_GUESS_BUF_SIZE; i+=1)
  {
    if(str[i] == 0 | str[i] == '\n')
    {
      reached_end = 1;
    }
    if(!reached_end)
    {
      res = (res * 10) + (str[i] - '0');
    }
  }
  return res;
}


// Repeatedly read a single char until reaching newline
typedef enum my_getline_state_t
{
  READ_CHARS,
  OUTPUT_LINE
}my_getline_state_t;
typedef struct my_getline_t
{
  syscall_io_t syscall_io;
  uint1_t done;
  char line[USER_GUESS_BUF_SIZE];
}my_getline_t;
my_getline_t my_getline(syscall_io_t syscall_io, fosix_fd_t fd)
{
  static my_getline_state_t state;
  static char read_buf;
  static user_guess_buf_size_t num_chars;
  static char line[USER_GUESS_BUF_SIZE];
  
  my_getline_t rv;
  rv.syscall_io = syscall_io;
  rv.done = 0;
  rv.line = line;
   
  // Read a char
  if(state==READ_CHARS)
  {
    int2_t num_chars_read;
    char syscall_buf[FOSIX_BUF_SIZE];
    READ_THEN(rv.syscall_io, num_chars_read, fd, syscall_buf, 1,\
      read_buf = syscall_buf[0];\
      line[num_chars] = read_buf;\
      num_chars += 1;\
      state = OUTPUT_LINE;)
  } else if(state==OUTPUT_LINE) {
    // Time for output?
    if(read_buf=='\n')
    {
      rv.done = 1;
      // Start over
      num_chars = 0;
    }
    state = READ_CHARS; 
  }
  
  
  return rv;
}


// Helper to read user string and convert to int
typedef enum read_guess_state_t
{
  READ_LINE,
  OUTPUT_INT
}read_guess_state_t;
typedef struct read_guess_t
{
  syscall_io_t syscall_io;
  uint1_t done;
  guess_t guess;
}read_guess_t;
read_guess_t read_guess(syscall_io_t syscall_io, fosix_fd_t fd)
{
  static read_guess_state_t state;
  static char guess_str[USER_GUESS_BUF_SIZE];
  
  read_guess_t rv;
  rv.syscall_io = syscall_io;
  rv.done = 0;
  rv.guess = 0;
   
  // Read line containing guess
  if(state==READ_LINE)
  {
    // Read guess chars, convert to int
    my_getline_t read = my_getline(rv.syscall_io, fd);
    rv.syscall_io = read.syscall_io;
    if(read.done)
    {
      guess_str = read.line;
      state = OUTPUT_INT;
    }
  } else if(state==OUTPUT_INT) {
    rv.guess = my_atoi(guess_str);
    rv.done = 1;
    state = READ_LINE; // Start over
  }
  
  return rv;
}


// Primary state machine states
typedef enum state_t {
  RESET,
  STDOUT_OPEN,
  STDIN_OPEN,
  PRINT_START,
  PRINT_MAKE_GUESS,
  READ_GUESS,
  PRINT_RESP
} state_t;
// Stateful global variables
state_t state;
guess_t counter; // Randomish value
guess_t actual; // Actual value
guess_t guess; // Guess from user
fosix_fd_t stdout_fd; // File descriptor for /dev/stdout
fosix_fd_t stdin_fd; // File descriptor for /dev/stdin 

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
    OPEN_THEN(syscall_io, stdout_fd, "/dev/stdout",\
      state = STDIN_OPEN;)
  }else if(state==STDIN_OPEN){
    OPEN_THEN(syscall_io, stdin_fd, "/dev/stdin",\
      state = PRINT_START;)
  }else if(state==PRINT_START){
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "PipelineC guessing game!\n",\
     state = PRINT_MAKE_GUESS;\
     actual = counter;) // Sample fast clock for a 'randomish' number
  }else if(state==PRINT_MAKE_GUESS){
    STRWRITE_THEN(syscall_io, unused, stdout_fd, "Enter guess: ",\
      state = READ_GUESS;)
  }else if(state==READ_GUESS){
    // Read guess chars, convert to int
    read_guess_t read = read_guess(syscall_io, stdin_fd);
    syscall_io = read.syscall_io;
    if(read.done)
    {
      guess = read.guess;
      state = PRINT_RESP;
    }
  }else if(state==PRINT_RESP){
    if(guess > actual){
      STRWRITE_THEN(syscall_io, unused, stdout_fd, "Too high!\n",\
        state = PRINT_MAKE_GUESS;)
    }else if(guess < actual){
      STRWRITE_THEN(syscall_io, unused, stdout_fd, "Too low!\n",\
        state = PRINT_MAKE_GUESS;)
    }else{
      STRWRITE_THEN(syscall_io, unused, stdout_fd, "Correct!\n",\
        state = PRINT_START;)
    }
  }
  
  // A counter running at UART CLK 25MHz, fast enough to seem random
  if(counter==GUESS_MAX){
    counter = GUESS_MIN;
  } else {
    counter += 1;
  }
  
  // System call 'FSM' running when asked to start
  SYSCALL(syscall_io, sys_to_proc, proc_to_sys)
  
  // Write outputs
  WIRE_WRITE(fosix_proc_to_sys_t, main_proc_to_sys, proc_to_sys)
}
