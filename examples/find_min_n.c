#pragma PART "LFE5U-85F-6BG381C" // See main.c for other part examples

#include "uintN_t.h"

// Container for 3 values at a time
#define N_MIN 3
typedef struct minimum_t
{
  uint8_t values[N_MIN]; // 0 is smallest, then 1 is next etc
}minimum_t;

// Helper module to incorporate a new fourth value
// into existing sorted list of 3 smallest values
minimum_t update_min(minimum_t min, uint8_t new_value)
{
  minimum_t rv = min; // start of returning input unmodified
  // If new minimum is found, need to adjust position
  // of other prev minimum values, dropping one (the largest)
  // If min[i] is new min, shift starting at i to make room
  uint1_t found_a_min_value = 0;
  uint32_t min_i;
  for(min_i=0; min_i<N_MIN; min_i+=1)
  {
    if((new_value < min.values[min_i]) & !found_a_min_value)
    {
      // Found a minimum value
      // Shift data up based on min_i positon
      uint32_t shift_i;
      for(shift_i=(N_MIN-1); shift_i>min_i; shift_i-=1)
      {
        rv.values[shift_i] = min.values[shift_i-1];
      }
      // Write new minimum into position
      rv.values[min_i] = new_value;
      found_a_min_value = 1;
    }
  }
  return rv;
}

// Function to do the entire vector
#define N_INPUTS 16
minimum_t find_min(uint8_t values[N_INPUTS])
{
  minimum_t min = {{255, 255, 255}}; // max init
  // Iterate over each value
  uint32_t in_i;
  for(in_i=0; in_i<N_INPUTS; in_i+=1)
  {
    // And update list of smallest three with each value
    min = update_min(min, values[in_i]);
  }
  return min;
}

#pragma MAIN testbench
// Includes ~valid/go input control signal
// and returns match flag so design does not optimize away
uint1_t testbench(uint1_t start)
{
  // Test case
  uint8_t values[N_INPUTS] = 
    {6, 22, 71, 4,
     3, 19, 68, 1,
     5, 21, 70, 3,
     2, 17, 67, 0};
  minimum_t actual = {{0, 1, 2}};

  // Test setup
  uint8_t inputs[N_INPUTS]; // zeros
  // Unless starting/go/valid
  if(start)
  {
    inputs = values;
  }
  minimum_t test = find_min(inputs);
  uint1_t match = test==actual;
  if(start) printf("Test passed: %d\n", match);

  return match;
}

/* Example Modelsim commands
add wave -position end  sim:/top/testbench_15CLK_23cd183f/find_min_find_min_n_c_l76_c20_8c4d/clk
add wave -position end  sim:/top/testbench_15CLK_23cd183f/find_min_find_min_n_c_l76_c20_8c4d/values
add wave -position end  sim:/top/testbench_15CLK_23cd183f/find_min_find_min_n_c_l76_c20_8c4d/return_output
add wave -position 1  sim:/top/testbench_15CLK_23cd183f/start(0)
force -freeze sim:/top/testbench_15CLK_23cd183f/find_min_find_min_n_c_l76_c20_8c4d/clk 1 0, 0 {50 ps} -r 100
force -freeze sim:/top/testbench_15CLK_23cd183f/start(0) 0 0
*/