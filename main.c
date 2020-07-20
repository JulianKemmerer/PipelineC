
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"

//// FULL DMA WORK TESTING
//15x15 333 sec before adding pipeline map caching
//      250  after assuming latency==slices length , nont build pipeline map
//20x20 429
//30x30 2099

// JUST MATRIX MULT
/////////////
// New longer testing at 4x4
// Ran through syns, saved logs, rming .parsed file each time...
// 4x4    25.137 seconds
// 8x8    95.744 seconds
// 16x16  797 sec

// 16x16 Only through parsing funcs: 146 sec
// ~140 with set subtract instead of remove in loop
// ~140 with more set intersect instead of search for match in loop



#include "uintN_t.h"
#pragma MAIN_MHZ main 600.0

uint64_t add(uint64_t x, uint64_t y) 
{
__vhdl__("\
  -- Arch declarations go here \n\
  begin \n\
  -- The arch body, processes, assignments, etc go here \n\
  return_output <= x + y; \
");
}

uint64_t main(uint64_t x, uint64_t y) 
{
 return add(x,y);
}


/*
#include "intN_t.h"
#pragma MAIN_MHZ work_main 600.0

#define DIM 16 //45 //45^2 * 2 bytes ~=4096 dma bytes
#define data_t int16_t
#define array_sum int16_array_sum16 //45

typedef struct work_inputs_t
{
  data_t matrix0[DIM][DIM];
  data_t matrix1[DIM][DIM];
} work_inputs_t;
typedef struct work_outputs_t
{
  data_t result[DIM][DIM];
} work_outputs_t;

// FOR THE SAKE OF COMPILE TIME BREAK THE ABOVE INTO SMALLER MODULES

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
elem_inputs_t unpack(work_inputs_t inputs)
{
  elem_inputs_t rv;
  uint64_t i;
  uint64_t j;
  uint64_t k;
  for (i = 0; i < DIM; i = i + 1) 
  { 
    for (j = 0; j < DIM; j = j + 1) 
    { 
      for (k = 0; k < DIM; k = k + 1)
      {
          rv.row_pair[i][j].data_0i[k] = inputs.matrix0[i][k];
          rv.row_pair[i][j].data_1j[k] = inputs.matrix1[k][j]; 
      }
    }
  }
  return rv;
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
work_outputs_t work_main(work_inputs_t inputs)
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
