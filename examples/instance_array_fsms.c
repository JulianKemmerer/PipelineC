#include "intN_t.h"
#include "uintN_t.h"

#define N_THREADS 10

// Each thread is providing these values to the increment handler module simultaneously
uint32_t increment_input_value;
uint32_t increment_input_tid;
// And expects an output of the sum after the thread's addition (same cycle)
uint32_t increment_output_sum;
// A 'thread'/FSM instance definition trying to increment some accumulator this clock cycle
uint32_t incrementer_thread(uint8_t tid)
{
  while(1)
  {
    increment_input_value = tid + 1;
    increment_input_tid = tid;
    // increment_output_sum ready same cycle
    printf("Thread %d trying to increment by %d, got new total %d.\n",
            tid, increment_input_value, increment_output_sum);
    __out(increment_output_sum); // "return" that continues
    //return increment_output_sum;
  }
}
// Derive FSM from above function
#include "incrementer_thread_FSM.h"

// The module doing the incrementing/accumulating
// sees an array of values, one from each thread
uint32_t increment_input_values[N_THREADS];
uint32_t increment_input_tids[N_THREADS];
#pragma INST_ARRAY increment_input_value increment_input_values
#pragma INST_ARRAY increment_input_tid increment_input_tids
// And drives output totals back to each thread as an array
uint32_t increment_output_sums[N_THREADS];
#pragma INST_ARRAY increment_output_sum increment_output_sums
#pragma MAIN increment_handler
void increment_handler()
{
  // Accumulator reg
  static uint32_t total;

  // In one cycle accumulate from each thread with chained adders
  uint32_t i;
  for(i=0; i<N_THREADS; i+=1)
  {
    increment_output_sums[i] = total + increment_input_values[i];
    printf("Thread %d incrementing total %d by %d -> new total %d.\n",
            increment_input_tids[i], total, increment_input_values[i], increment_output_sums[i]);
    total = increment_output_sums[i]; // accumulate
  }

  return total;
}

// Top level wrapper for N parallel instances of incrementer_thread

// Connect FSM outputs to top level output
// So doesnt synthesize away
typedef struct n_thread_outputs_t
{
  incrementer_thread_OUTPUT_t data[N_THREADS];
}n_thread_outputs_t;
#pragma MAIN main
n_thread_outputs_t main()
{
  // Registers keeping time count and knowning when done
  static uint32_t clk_cycle_count;
  printf("Clock Cycle %d:\n", clk_cycle_count);
  
  // N parallel instances of incrementer_thread
  uint8_t tid;
  incrementer_thread_INPUT_t inputs[N_THREADS];
  n_thread_outputs_t outputs;
  for(tid=0; tid<N_THREADS; tid+=1)
  {
    inputs[tid].tid = tid;
    inputs[tid].input_valid = 1;
    inputs[tid].output_ready = 1;
    outputs.data[tid] = incrementer_thread_FSM(inputs[tid]);
    //if(outputs.data[tid].input_ready)
    //{
    //  printf("Clock# %d: Thread %d starting.\n",
    //    clk_cycle_count, tid);  
    //}
    //if(outputs.data[tid].output_valid)
    //{
    //  printf("Clock# %d: Thread %d output value = %d.\n",
    //    clk_cycle_count, tid, outputs.data[tid].return_output);
    //}
  }
  
  // Func occuring each clk cycle
  clk_cycle_count += 1;
  
  // Wire up outputs
  return outputs;
}