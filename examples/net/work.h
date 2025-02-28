// This describes the work to be done:
// 	Input data format
// 	Output data format
// 	The actual computation 'work' to be done
// Ideally in PipelineC/C code that can be compiled+checked in software easily.
#pragma once
#include "intN_t.h"
#ifdef __PIPELINEC__
#include "stream/stream.h"
#endif
// Do work on inputs to form outputs

// MATRIX MULT EXAMPLE
#define DIM 2
#define data_t int8_t

typedef struct work_inputs_t
{
  data_t matrix0[DIM][DIM];
  data_t matrix1[DIM][DIM];
} work_inputs_t;
#ifdef __PIPELINEC__
#include "work_inputs_t_bytes_t.h"
DECL_STREAM_TYPE(work_inputs_t)
#else
#include "type_bytes_t.h/work_inputs_t_bytes_t.h/work_inputs_t_bytes.h"
#endif
typedef struct work_outputs_t
{
  data_t result[DIM][DIM];
} work_outputs_t;
#ifdef __PIPELINEC__
#include "work_outputs_t_bytes_t.h"
DECL_STREAM_TYPE(work_outputs_t)
#else
#include "type_bytes_t.h/work_outputs_t_bytes_t.h/work_outputs_t_bytes.h"
#endif

// Basic algorithm from internet
void work_cpu(work_inputs_t* inputs, work_outputs_t* outputs)
{ 
    int i, j, k; 
    for (i = 0; i < DIM; i++) 
    { 
        for (j = 0; j < DIM; j++) 
        { 
            outputs->result[i][j] = 0;
            for (k = 0; k < DIM; k++)
            {
                outputs->result[i][j] += inputs->matrix0[i][k] * inputs->matrix1[k][j];
            }
        } 
    } 
}

// Basic PipelineC implementation without pointers
work_outputs_t work(work_inputs_t inputs)
{ 
    work_outputs_t outputs;
    uint32_t i;
    uint32_t j;
    uint32_t k;
    for (i = 0; i < DIM; i+=1) 
    { 
        for (j = 0; j < DIM; j+=1) 
        { 
            outputs.result[i][j] = 0;
            for (k = 0; k < DIM; k+=1)
            {
                outputs.result[i][j] += inputs.matrix0[i][k] * inputs.matrix1[k][j];
            }
        } 
    }
    return outputs;
}

// Helper to init a work_inputs_t
data_t max_val = 100;
work_inputs_t work_inputs_init(int test_num)
{
  // Randomizeish values
  work_inputs_t inputs;
  int i, j;
  for (i = 0; i < DIM; i++) 
  { 
      for (j = 0; j < DIM; j++) 
      { 
          inputs.matrix0[i][j] = rand()%max_val;
          inputs.matrix1[i][j] = rand()%max_val;
      } 
  } 
  
  return inputs;
}

// Helper to compare two outputs
int compare_bad(int test_num, work_outputs_t cpu, work_outputs_t fpga)
{
  int i, j;
  for (i = 0; i < DIM; i++) 
  { 
      for (j = 0; j < DIM; j++) 
      { 
          if(cpu.result[i][j] != fpga.result[i][j])
          {
            printf("Output %d: %d,%d does not match! FPGA: %d, CPU: %d\n", test_num, i,j, fpga.result[i][j], cpu.result[i][j]);
            return 1;
          }
      } 
  }
  return 0;
}

// Most scalable (making best of O(N^3) as possible), most parallel, PipelineC implementation
/*
#include "xstr.h" // Stringification for raw vhdl
#define array_sum int16_array_sum4 // Built in func
// FOR THE SAKE OF COMPILE TIME BREAK THE ABOVE INTO SMALLER MODULES
// NOT REQUIRED TO DO IF YOU ARE IMMORTAL AND HAVE ALOT OF TIME TO UNROLL LARGE O(N^3) LOOPS

// The two rows needed for a single element in the resulting matrix
typedef struct row_pair_t
{
  data_t data_0i[DIM];
  data_t data_1j[DIM];
}row_pair_t;

// All of the two row pairs needed for all elements in the resulting matrix
typedef struct elem_inputs_t
{
  row_pair_t row_pair[DIM][DIM];
}elem_inputs_t;
// Unpack the normal input matrices to row ordered elem_inputs_t
#pragma FUNC_WIRES unpack
elem_inputs_t unpack(work_inputs_t inputs)
{
  // For sake of compile time do loop in raw vhdl
__vhdl__("\
begin \n\
  i_gen: for i in 0 to (" xstr(DIM) "-1) generate \n\
    j_gen: for j in 0 to (" xstr(DIM) "-1) generate \n\
      k_gen: for k in 0 to (" xstr(DIM) "-1) generate \n\
          return_output.row_pair(i)(j).data_0i(k) <= inputs.matrix0(i)(k); \n\
          return_output.row_pair(i)(j).data_1j(k) <= inputs.matrix1(k)(j);  \n\
      end generate; \n\
    end generate; \n\
  end generate; \n\
");
}

// Function to determine value of a single element in the result matrix
data_t elem_func(row_pair_t row_pair)
{
  uint64_t k;
  data_t res_k[DIM];
  for (k = 0; k < DIM; k = k + 1)
  {
      res_k[k] = row_pair.data_0i[k] * row_pair.data_1j[k]; 
  }
  return array_sum(res_k);
}

// Function doing the entire matrix mult
work_outputs_t work(work_inputs_t inputs)
{
  // Unpack to elem_func inputs
  elem_inputs_t elem_func_input = unpack(inputs);
  
  // Calculate each element in the result
  work_outputs_t outputs;
  uint64_t i;
  uint64_t j;
  for (i = 0; i < DIM; i = i + 1) 
  { 
    for (j = 0; j < DIM; j = j + 1) 
    { 
      outputs.result[i][j] = elem_func(elem_func_input.row_pair[i][j]);
    }
  }
  return outputs;
}
*/
