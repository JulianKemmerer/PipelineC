// This describes the work to be done:
// 	Input data format
// 	Output data format
// 	The actual computation 'work' to be done
#pragma once

// Do work on inputs to form outputs

// MATRIX MULT EXAMPLE

#define DIM 45 //45^2 * 2 bytes ~=4096 dma bytes
#define data_t int16_t
#define array_sum int16_array_sum45

typedef struct work_inputs_t
{
  data_t matrix0[DIM][DIM];
  data_t matrix1[DIM][DIM];
} work_inputs_t;
typedef struct work_outputs_t
{
  data_t result[DIM][DIM];
} work_outputs_t;
work_outputs_t work(work_inputs_t inputs)
{
  work_outputs_t outputs;
  // Matrix mult
  uint64_t i;
  uint64_t j;
  uint64_t k;
  for (i = 0; i < DIM; i = i + 1) 
  { 
    for (j = 0; j < DIM; j = j + 1) 
    { 
      data_t res_k[DIM];
      for (k = 0; k < DIM; k = k + 1)
      {
          res_k[k] = inputs.matrix0[i][k] * inputs.matrix1[k][j]; 
      }
      outputs.result[i][j] = array_sum(res_k);
    } 
  }
    
  return outputs;
}


