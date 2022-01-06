
#include "intN_t.h"
#include "uintN_t.h"


#pragma MAIN test0
uint32_t test0(uint32_t x)
{
  uint32_t rv = x + 1;
  return rv;
}

uint32_t test1(uint32_t x)
{
  __clk();
  uint32_t rv = x + 1;
  return rv;
}
#include "test1_FSM.h"
#pragma MAIN test1_wrapper
uint32_t test1_wrapper()
{
  test1_INPUT_t i;
  i.x = 2;
  i.input_valid = 1;
  i.output_ready = 1;
  test1_OUTPUT_t o = test1_FSM(i);
  return o.return_output;
}

uint32_t test2(uint32_t x)
{
  uint32_t rv = x + 1;
  __clk();
  return rv;
}
#include "test2_FSM.h"
#pragma MAIN test2_wrapper
uint32_t test2_wrapper()
{
  test2_INPUT_t i;
  i.x = 2;
  i.input_valid = 1;
  i.output_ready = 1;
  test2_OUTPUT_t o = test2_FSM(i);
  return o.return_output;
}

/*
uint32_t wait(uint32_t clocks)
{
  while(clocks > 0)
  {
    __clk();
    clocks -= 1;
  }
  return clocks;
}
uint32_t wait_test()
{
  uint32_t clocks_to_wait = 5;
  while(clocks_to_wait > 0)
  {
    wait(clocks_to_wait);
    clocks_to_wait -= 1;
  }
  return clocks_to_wait;
}
#include "wait_test_FSM.h"
#pragma MAIN wait_test_wrapper
uint32_t wait_test_wrapper()
{
  wait_test_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  wait_test_OUTPUT_t o = wait_test_FSM(i);
  return o.return_output;
}
*/
/*
// A single cycle comb. logic doing:
//  Input/entry handshake
//  Comb. logic add
//  Update a storage register
//  Output/return handshake 
uint8_t atomic_add(uint8_t val, uint8_t tid)
{
  static uint8_t the_reg;
  uint8_t new_reg_val = the_reg + val;
  printf("Thread %d incremented value from %d -> %d.\n",
    tid, the_reg, new_reg_val);
  the_reg = new_reg_val;
  return the_reg;
}
// Signal to tool to derive a single instance
// FSM region, ex. only one 8b the_reg in the design
// shared among N calling instances
#include "atomic_add_SINGLE_INST.h"

// A 'thread'/FSM instance definition
// trying to repeatedly increment the_reg
uint8_t incrementer_thread(uint8_t tid)
{
  while(1)
  {
    // Try to do atomic add 
    uint8_t local_reg_val = atomic_add(1, tid);
    // Output val so doesnt synthesize away
    __out(local_reg_val); 
  }
}
// Derive FSM from above function
#include "incrementer_thread_FSM.h"

// Top level N parallel instances of incrementer_thread
#define N_THREADS 10
// Connect FSM outputs to top level output
// So doesnt synthesize away
typedef struct n_thread_outputs_t
{
  incrementer_thread_OUTPUT_t data[N_THREADS];
}n_thread_outputs_t;
#pragma MAIN_MHZ main 100.0
n_thread_outputs_t main()
{
  // Registers keeping time count and knowning when done
  static uint32_t clk_cycle_count;
  
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
    if(outputs.data[tid].input_ready)
    {
      printf("Clock# %d: Thread %d starting.\n",
        clk_cycle_count, tid);  
    }
    if(outputs.data[tid].output_valid)
    {
      printf("Clock# %d: Thread %d output value = %d.\n",
        clk_cycle_count, tid, outputs.data[tid].return_output);
    }
  }
  
  // Func occuring each clk cycle
  clk_cycle_count += 1;
  
  // Wire up outputs
  return outputs;
}
*/

/*
// Output 4b wired to LEDs
// Derived FSM style
uint4_t main()
{
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  while (1) {
    // LEDs updated every clock
    // with the 4 most significant bits
    uint4_t led = uint28_27_24(counter);
    counter = counter + 1;
    __out(led);
  }
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
uint4_t main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
  return o.return_output;
}
*/
