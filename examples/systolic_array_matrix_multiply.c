// Basic systolic array multiplier
// http://ecelabs.njit.edu/ece459/lab3.php

#include "uintN_t.h"
#include "intN_t.h"
#include "wire.h"

#define data_t int16_t // Must be integer to use 'accum' primitive below
#define MATRIX_DIM 8

typedef struct processor_io_t
{
  data_t a;
  data_t b;
  uint1_t reset_and_read_result;
}processor_io_t;

processor_io_t processor(processor_io_t inputs)
{  
  // Logic to get outputs from inputs
  processor_io_t outputs;
  // Typically pass inputs to outputs
  outputs = inputs;
  // First do multiply, then accumulate
  data_t increment = inputs.a * inputs.b;
  // Except when resetting and reading out results
  if(inputs.reset_and_read_result)
  {
    increment = 0; // Reset to 0
  }
  // The built in accumulate function
  data_t result = accum(increment, inputs.reset_and_read_result);
  // Read out of results through 'a' port
  if(inputs.reset_and_read_result)
  {
    outputs.a = result;
  }
  return outputs;
}

// Do main func just instantiating N^2 processors 'flattened' 
// without dataflow dependency in the explict code function to be pipelined
// This helps eliminate wires being routing through pipelining as shown at bottom of file
// Global wires for all wires to and from processors are connected in processor_wiring instead
processor_io_t processor_inputs[MATRIX_DIM][MATRIX_DIM];
processor_io_t processor_outputs[MATRIX_DIM][MATRIX_DIM];

#pragma MAIN processor_instances
void processor_instances()
{
  uint32_t i, j;
  for(i=0; i<MATRIX_DIM; i+=1)
  {
    for(j=0; j<MATRIX_DIM; j+=1)
    {      
      // The processing element
      processor_outputs[i][j] = processor(processor_inputs[i][j]);
    }
  }
}

#pragma MAIN processor_wiring
typedef struct multiplier_outputs_t
{
  // The result matrix
  data_t result[MATRIX_DIM][MATRIX_DIM];
  // Valid flags for the elements
  uint1_t results_valid[MATRIX_DIM][MATRIX_DIM];
}multiplier_outputs_t;
multiplier_outputs_t processor_wiring(
  uint1_t reset_and_read_result,
  data_t i_inputs[MATRIX_DIM], 
  data_t j_inputs[MATRIX_DIM]
){
  // Assign i,j inputs to processors a,b inputs
  uint32_t i, j;
  for(i=0; i<MATRIX_DIM; i+=1)
  {
    processor_inputs[i][0].a = i_inputs[i];
  }
  for(j=0; j<MATRIX_DIM; j+=1)
  {
    processor_inputs[0][j].b = j_inputs[j];
  }
  // Output data result matrix and flag for when result is done/valid
  multiplier_outputs_t outputs;
  for(i=0; i<MATRIX_DIM; i+=1)
  {
    for(j=0; j<MATRIX_DIM; j+=1)
    {
      // Common processor inputs
      processor_inputs[i][j].reset_and_read_result = reset_and_read_result;
      // a outputs to the right
      if(j<(MATRIX_DIM-1))
      {
        processor_inputs[i][j+1].a = processor_outputs[i][j].a;
      }
      // b outputs down
      if(i<(MATRIX_DIM-1))
      {
        processor_inputs[i+1][j].b = processor_outputs[i][j].b;
      }
      // Result read from a port 
      outputs.result[i][j] = processor_outputs[i][j].a;
      // And includes valid flag
      outputs.results_valid[i][j] = processor_outputs[i][j].reset_and_read_result;
    }
  }
  return outputs;
}



/*
// This way is bad because it delays inputs and outputs beyond what is needed
//  procecessor0,0 is first and all other processor inputs are delays by that modules latency, etc
// Same for outputs processor 3,3 is last, and all outputs are delayed to align

// Global control wires not routed through main pipelining
uint1_t reset_wire;
uint1_t read_result_wire;
#pragma MAIN main_ctrl
void main_ctrl(uint1_t reset, uint1_t read_result)
{
  reset_wire = reset;
  read_result_wire = read_result;
}

#pragma MAIN main
// Output data is 'a' wires from last column
typedef struct row_t
{
  data_t data[MATRIX_DIM];
}row_t;
row_t main(data_t i_inputs[MATRIX_DIM], data_t j_inputs[MATRIX_DIM])
{
  row_t output_wires;
  // Input wires for each processor
  data_t a[MATRIX_DIM][MATRIX_DIM];
  data_t b[MATRIX_DIM][MATRIX_DIM];
  // Assign i,j inputs to processors a,b inputs
  uint32_t i, j;
  for(i=0; i<MATRIX_DIM; i+=1)
  {
    a[i][0] = i_inputs[i];
  }
  for(j=0; j<MATRIX_DIM; j+=1)
  {
    b[0][j] = j_inputs[j];
  }
  for(i=0; i<MATRIX_DIM; i+=1)
  {
    for(j=0; j<MATRIX_DIM; j+=1)
    {      
      // The processing element
      processor_t p_ij = processor(a[i][j], b[i][j]);  
      // a outputs to the right
      if(j<(MATRIX_DIM-1))
      {
        a[i][j+1] = p_ij.a;
      }
      // b outputs down
      if(i<(MATRIX_DIM-1))
      {
        b[i+1][j] = p_ij.b;
      }
      // Result final read out from last 'a' wires
      if(j==(MATRIX_DIM-1))
      {
        output_wires.data[i] = p_ij.a;
      }
    }
  }
  return output_wires;
}*/