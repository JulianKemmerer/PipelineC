#include "uintN_t.h"
#include "intN_t.h"
#include "global_func_inst.h"

// Make getting to autopipeline from stateful module easier
// A pipeline my_func() and a stateful testbench() reading the inputs and outputs
// Global instance wires with macros to do read and write makes this easy

// The function inputs and outputs
typedef struct my_func_in_t
{
  int32_t x;
  int32_t y;
  uint1_t valid;
}my_func_in_t;
typedef struct my_func_out_t
{
  int32_t data;
  uint1_t valid;
}my_func_out_t;
// The work to pipeline out = f(in)
my_func_out_t my_func(my_func_in_t input)
{
  my_func_out_t output;
  output.data = input.x * input.y;
  output.valid = input.valid;
  return output;
}

// Helper macros to make a globally visible and wired up instance of the pipeline
GLOBAL_FUNC_INST(my_inst, my_func_out_t, my_func, my_func_in_t)
//GLOBAL_PIPELINE_INST(my_inst, my_func_out_t, my_func, my_func_in_t)

#pragma MAIN_MHZ testbench 200.0
uint1_t testbench()
{
  static uint1_t err;
  uint1_t rv = err;
  // Test vectors of inputs and outputs
  static int32_t write_input_index = 0;
  static int32_t read_output_index = 0;
  // 3 random test vectors
  int32_t inputs_x[3];
  inputs_x[0] = 0b1000000000000000000000000000000;
  inputs_x[1] = 0b1000000000000000000000000000001;
  inputs_x[2] = 0b0000000000000010000000000000001;
  int32_t inputs_y[3];
  inputs_y[0] = 0b0000000000000000000000000000001;
  inputs_y[1] = 0b0000000000000000000000000000001;
  inputs_y[2] = 0b1000000000000010000000000000001;
  // TODO be able to call my_inst during compile time constant eval
  // For now ok since just '*'
  int32_t outputs[3];
  int32_t i;
  for(i=0;i<3;i+=1)
  {
    outputs[i] = inputs_x[i] * inputs_y[i];
  }

  // Write data into N clock cycle pipeline
  my_func_in_t input;
  input.x = inputs_x[write_input_index];
  input.y = inputs_y[write_input_index];
  input.valid = 1;
  write_input_index += 1;
  my_inst_in = input;
  // Read output of pipeline
  // .valid = 1 output data doesnt show up until N cycles/iterations later
  my_func_out_t output = my_inst_out;
  
  // Check test data pattern
  if(output.valid)
  {
    if(output.data != outputs[read_output_index])
    {
      err = 1;
    }
    else
    {
      read_output_index += 1;
    }
  }
  
  return rv;
}
