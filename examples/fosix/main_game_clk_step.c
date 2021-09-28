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
// Could make into smaller serial fsm version
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
typedef struct my_getline_t
{
  char line[USER_GUESS_BUF_SIZE];
}my_getline_t;
my_getline_t my_getline(fosix_fd_t fd)
{
  char line[USER_GUESS_BUF_SIZE];
  user_guess_buf_size_t num_chars;
  char read_buf;
  
  // Read chars until EOL
  uint1_t not_enough_chars = 1;
  while(not_enough_chars)
  {
    // Read a char
    read_t r = read(fd, 1);
    read_buf = r.buf[0];
    // Record it in the line buffer
    line[num_chars] = read_buf;
    num_chars += 1;
    // At EOL?
    if(read_buf=='\n')
    {
      not_enough_chars = 0;
    }
  }
  
  // Return line of chars
  my_getline_t rv;
  rv.line = line;
  return rv;
}

// Helper to read user string and convert to int
guess_t read_guess(fosix_fd_t fd)
{
  // Read line containing guess
  my_getline_t mgl = my_getline(fd);
  guess_t guess = my_atoi(mgl.line);
  return guess;
}

// Make a 'random' number by just counting faster
guess_t RANDOM_VAL_WIRE;
#include "clock_crossing/RANDOM_VAL_WIRE.h"
#pragma MAIN random_module
void random_module()
{
  static guess_t count;
  WIRE_WRITE(guess_t, RANDOM_VAL_WIRE, count)
  // Increment but stay in range
  if(count==(GUESS_MAX-1))
  {
    count = 0;
  }
  else
  {
    count += 1;
  }
}
guess_t random_num()
{
  guess_t val;
  WIRE_READ(guess_t, val, RANDOM_VAL_WIRE)
  return val;
}


void main()
{
  guess_t actual; // Actual value
  guess_t guess; // Guess from user
  fosix_fd_t stdout_fd; // File descriptor for /dev/stdout
  fosix_fd_t stdin_fd; // File descriptor for /dev/stdin 
  
  // Open files for user IO
  stdout_fd = open("/dev/stdout");
  stdin_fd = open("/dev/stdin");
  while(1)
  {
    // Start game
    STRWRITE(stdout_fd, "PipelineC guessing game!\n")
    // Pick 'random' number
    guess_t actual = random_num();
    // Make user guess multiple times if needed
    uint1_t incorrect = 1;
    while(incorrect)
    {
      STRWRITE(stdout_fd, "Enter guess: ")
      guess_t guess = read_guess(stdin_fd);
      if(guess > actual)
      {
        STRWRITE(stdout_fd, "Too high!\n")
      } 
      else if(guess < actual)
      {
        STRWRITE(stdout_fd, "Too low!\n")
      }
      else
      {
        STRWRITE(stdout_fd, "Correct!\n")
        incorrect = 0;
      }
    }
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
