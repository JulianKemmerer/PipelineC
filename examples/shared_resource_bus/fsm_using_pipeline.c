#pragma PART "xc7a100tcsg324-1" 
#include "compiler.h"
#include "debug_port.h"
#include "arrays.h"
#include "intN_t.h"
#include "uintN_t.h"
//#include "float_e_m_t.h"
//#define float float_8_11_t

#define DEV_CLK_MHZ 40.0 //270.0
#define HOST_CLK_MHZ 40.0
#define NUM_THREADS 8

// The pipeline
typedef struct test_in_t{
  float x;
  float y;
}test_in_t;
typedef struct test_out_t{
  float result;
}test_out_t;
test_out_t test_func(test_in_t inputs)
{
  test_out_t rv;
  rv.result = inputs.x + inputs.y;
  return rv;
}

// Make a shared resource bus instance from the pipeline
// name : out_type = func_to_pipeline(in_type)
#define SHARED_RESOURCE_BUS_PIPELINE_NAME         test
#define SHARED_RESOURCE_BUS_PIPELINE_OUT_TYPE     test_out_t
#define SHARED_RESOURCE_BUS_PIPELINE_FUNC         test_func
#define SHARED_RESOURCE_BUS_PIPELINE_IN_TYPE      test_in_t
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_THREADS NUM_THREADS
#define SHARED_RESOURCE_BUS_PIPELINE_HOST_CLK_MHZ HOST_CLK_MHZ
#define SHARED_RESOURCE_BUS_PIPELINE_DEV_CLK_MHZ  DEV_CLK_MHZ
#include "shared_resource_bus_pipeline.h"

// Main loop demoing pipeline
uint32_t host_clk_counter;
void main(uint8_t tid)
{
  uint32_t start_time;
  uint32_t end_time;
  test_in_t inputs;
  inputs.x = 1.23;
  inputs.y = 4.56;
  while(inputs.x != 0.0) // So doesnt synthesize away, need to make execution depend on FP stuff
  {
    // First step is reset debug counter
    start_time = host_clk_counter;

    // TEST
    printf("Thread %d: Time %d: adding %f + %f\n", tid, start_time, inputs.x, inputs.y);
    test_out_t outputs = test(inputs);
    end_time = host_clk_counter;
    printf("Thread %d: Time %d: %d cycles for result %f + %f = %f\n", tid, end_time, end_time-start_time, inputs.x, inputs.y, outputs.result);
    inputs.y = inputs.x;
    inputs.x = outputs.result;
  }
}
// Wrap up main FSM at top level
#include "main_FSM.h"
MAIN_MHZ(main_wrapper, HOST_CLK_MHZ)
uint1_t main_wrapper()
{
  // Counter lives here on ticking host clock
  static uint32_t host_clk_counter_reg;
  host_clk_counter = host_clk_counter_reg;
  host_clk_counter_reg += 1;
  // Instantiate threads of main()
  uint1_t valid_out = 1; // So doesnt synthesize away
  uint8_t tid;
  for(tid = 0; tid < NUM_THREADS; tid+=1)
  {
    main_INPUT_t i;
    i.input_valid = 1;
    i.tid = tid;
    i.output_ready = 1;
    main_OUTPUT_t o = main_FSM(i);
    valid_out &= o.output_valid;
  }
  return valid_out;
}