#pragma PART "xc7a100tcsg324-1" // FMAX ~140 MHz LINE_WIDTH=15, FMAX ~80 MHz LINE_WIDTH=142
//#pragma PART "LFE5U-85F-6BG381C" // FMAX ~100 MHz LINE_WIDTH=15, FMAX ~60 MHz LINE_WIDTH=142
#define CLOCK_MHZ 80 // Limited by beam_splitter stateful function
#include "compiler.h"
#include "uintN_t.h"
#include "arrays.h"

// https://adventofcode.com/2025/day/7

#define LINE_WIDTH 15
#define split_flags_total uint1_array_sum15 // pipelinec built in function for binary tree sum
#define EMPTY_LINE "..............."
#define input_t char
#define EMPTY '.'
#define BEAM '|'
#define SPLITTER '^'
#define NUM_LINES 16

// Inputs to dataflow
// Global wires connect this process into rest of design
input_t input_line[LINE_WIDTH];
uint1_t input_valid;
MAIN_MHZ(inputs_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void inputs_process()
{
  // Hard code inputs for sim for now...
  static input_t inputs[NUM_LINES][LINE_WIDTH] = {
    ".......|.......",
    "...............",
    ".......^.......",
    "...............",
    "......^.^......",
    "...............",
    ".....^.^.^.....",
    "...............",
    "....^.^...^....",
    "...............",
    "...^.^...^.^...",
    "...............",
    "..^...^.....^..",
    "...............",
    ".^.^.^.^.^...^.",
    "..............."
  };
  static uint16_t line_counter;
  static uint1_t test_running = 1;
  input_line = inputs[0];
  input_valid = test_running;
  if(input_valid){
    ARRAY_SHIFT_DOWN(inputs, NUM_LINES, 1)
    test_running = line_counter < (NUM_LINES-1);
    line_counter += 1;
  }
}


#pragma MAIN beam_splitter
uint32_t beam_splitter(){
  // Regs for state, line and split count
  static uint16_t split_count;
  static input_t current_line[LINE_WIDTH] = EMPTY_LINE;
  // Next value for regs default is current
  input_t next_line[LINE_WIDTH] = current_line;
  uint16_t next_split_count = split_count;
  // Unrolled loop of comparators muxes and such
  // could do simple next_split_count += 1 accumulation, but would be slow chain of adders
  // instead keep 1b flag for each input position 'is_splitting' and sum that
  uint1_t is_spltting[LINE_WIDTH];
  for(uint32_t i=0; i<LINE_WIDTH; i+=1){
    if(input_line[i]==BEAM){
      next_line[i] = BEAM;
    }else if((current_line[i]==BEAM)&(input_line[i]==SPLITTER)){
      if(i>0) next_line[i-1] = BEAM;
      next_line[i] = EMPTY;
      if(i<(LINE_WIDTH-1)) next_line[i+1] = BEAM;
      //next_split_count += 1;
      is_spltting[i] = 1;
    }
  }
  next_split_count += split_flags_total(is_spltting);
  // Clock enable regs when input valid
  if(input_valid){
    printf("Current line: %s\n", current_line);
    printf("Input line  : %s\n", input_line);
    printf("Next line   : %s\n", next_line);
    printf("Split count %d\n", next_split_count);
    current_line = next_line;
    split_count = next_split_count;
  }
  // Return so doesnt synthesize away
  return split_count;
}