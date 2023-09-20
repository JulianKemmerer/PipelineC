/**
Imagine a sequence of zeros and ones: 1,1,0,1,0,0,1,etc

Binary bytes (ASCII characters) have been encoded into the sequence
based on some integer constant N(ex.=1,2,etc) as follows:
* The sequence begins with 2N or more 1's
* Upon seeing the first 1->0 transition skip the next 3N-1 values
* The value arrived at is the first and least significant bit in the byte
* The next seven more-significant bits of the byte
  are obtained by skipping every 2N-1 values
* After the 8th bit completing the byte, repeat the above for next byte,
  beginning with looking for the 1->0 transition

Fill in this C function such that returns zero/NULL
until a full eight bit byte/character is parsed.
* The function is run once for each element in the sequence in order
* Only add code inside the function
* Only return a completed non-zero/null character once
* No global variables, no pointers, pass by value only
* No libraries, no OS functionality, etc 
* Hint: static local variables maintain state

uint8_t the_function(bool seq_val){
  // CODE HERE
}
*/
#ifndef __PIPELINEC__
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#else 
#include "uintN_t.h"
#define bool uint1_t
#endif

#define N 2 // Some integer 1,2,3 etc
#define SKIP3 ((3*N)-1)
#define SKIP2 ((2*N)-1)

uint8_t the_function(bool seq_val){
  static uint8_t char_buffer; // Buffer to hold eight bits
  static uint8_t bit_counter; // Count of how many bits in buffer
  // State machine state
  static bool waiting_for_one_zero_transition = 1; 
  static uint8_t counter = 0;
  static bool prev_seq_val = 0;
  uint8_t rv = 0;
  if(waiting_for_one_zero_transition){
    // Wait for 1->0
    if(prev_seq_val & !seq_val){
      // Setup first wait
      counter = SKIP3;
      bit_counter = 0;
      waiting_for_one_zero_transition = 0;
    }
  }else{
    // Skipping data until counter elapses
    if(counter==0){
      // Make room in buffer (shifting in zero)
      char_buffer = char_buffer >> 1;
      // OR-in top bit as it comes in
      if(seq_val){
        char_buffer |= 0b10000000;
      }
      // Reset counter/state
      if(bit_counter==7){
        // Last bit, back to waiting for next byte
        rv = char_buffer;
        waiting_for_one_zero_transition = 1;
      }else{
        // counter reset to SKIP2 for next bit
        counter = SKIP2;
      }
      bit_counter += 1;
    }else{
      counter -= 1;
    }
  }
  prev_seq_val = seq_val;
  return rv; 
}

#ifdef __PIPELINEC__
#pragma MAIN testbench
// pipelinec examples/c_puzzle.c --sim --comb --cocotb --ghdl --run 87
#endif
void testbench(){
  // For example these input_values sequences encode "Hi" with N=1 and N=2

  #if N==1
  // N=1
  #define TEST_SIZE 45
  bool input_values[TEST_SIZE] = {
    1, // 2*N=2 or more 1's to start
    1, // Ex. 3
    1,
    //
    0, // The 1->0 transition \/
    0, // Skip 3*N - 1=2
    // 'H' = 0x48 = 0b01001000
    0, // Skipped
    0, // Bit[0]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[1]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[2]
    //
    1, // Skip 2*N - 1=1
    1, // Bit[3]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[4]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[5]
    //
    1, // Skip 2*N - 1=1
    1, // Bit[6]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[7]
    //
    1, // 2*N=2 or more 1's 
    1, // Ex. 3
    1,
    //
    0, // The 1->0 transition \/
    0, // Skip 3*N - 1=2
    // 'i' = 0x69 = 0b01101001
    1, // Skipped
    1, // Bit[0]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[1]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[2]
    //
    1, // Skip 2*N - 1=1
    1, // Bit[3]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[4]
    //
    1, // Skip 2*N - 1=1
    1, // Bit[5]
    //
    1, // Skip 2*N - 1=1
    1, // Bit[6]
    //
    0, // Skip 2*N - 1=1
    0, // Bit[7]
    //
    1, // 2*N=2 or more 1's 
    1, // 
    1
  };
  #endif

  #if N==2
  // N=2
  #define TEST_SIZE 87
  bool input_values[TEST_SIZE] = {
    1, // 2*N=4 or more 1's to start
    1, // Ex. 5
    1,
    1,
    1,
    //
    0, // The 1->0 transition \/
    0, // Skip 3*N - 1=5
    0, // Skipped
    0, // Skipped
    // 'H' = 0x48 = 0b01001000
    0, // Skipped
    0, // Skipped
    0, // Bit[0]
    0, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[1]
    0, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[2]
    0, // Skip 2*N - 1=3
    //
    1, // Skipped
    1, // Skipped
    1, // Bit[3]
    1, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[4]
    0, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[5]
    0, // Skip 2*N - 1=3
    //
    1, // Skipped
    1, // Skipped
    1, // Bit[6]
    1, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[7]
    0,
    //
    1, // 2*N=4 or more 1's
    1, // Ex. 5
    1,
    1,
    1,
    //
    0, // The 1->0 transition \/
    0, // Skip 3*N - 1=5
    0, // Skipped
    0, // Skipped
    // 'i' = 0x69 = 0b01101001
    1, // Skipped
    1, // Skipped
    1, // Bit[0]
    1, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[1]
    0, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[2]
    0, // Skip 2*N - 1=3
    //
    1, // Skipped
    1, // Skipped
    1, // Bit[3]
    1, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[4]
    0, // Skip 2*N - 1=3
    //
    1, // Skipped
    1, // Skipped
    1, // Bit[5]
    1, // Skip 2*N - 1=3
    //
    1, // Skipped
    1, // Skipped
    1, // Bit[6]
    1, // Skip 2*N - 1=3
    //
    0, // Skipped
    0, // Skipped
    0, // Bit[7]
    0,
    //
    1, // 2*N=4 or more 1's 
    1, // Ex. 5
    1,
    1,
    1
  };
  #endif
  static uint32_t seq_index = 0;
  uint8_t the_char = the_function(input_values[seq_index]);
  if(the_char != 0){
    printf("the_char = %c\n", the_char);
  }
  seq_index += 1;
}

#ifndef __PIPELINEC__
// gcc c_puzzle.c -o c_puzzle && ./c_puzzle
int main(int argc, char** argv)
{
  int i = 0;
  while(i<TEST_SIZE)
  {
    testbench();
    i++;
  }    
  return 0;
}
#endif
