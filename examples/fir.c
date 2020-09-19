#include "uintN_t.h"
#pragma MAIN_MHZ fir_main 500.0
#pragma PART "xc7a35ticsg324-1l"

#define data_t uint16_t
#define coeff_t uint16_t
#define FIR_N_TAPS 16
#define LOG2_FIR_N_TAPS 4 //  log2(FIR_N_TAPS)
#define output_t uint36_t // data_width + coeff_width + log2(taps#)

// An array of datas (for shift reg)
typedef struct data_pipe_t
{
  data_t data[FIR_N_TAPS];
}data_pipe_t;

// Global func to buffer up N datas (shift reg)
data_pipe_t data_pipe_reg;
data_pipe_t data_pipe_func(data_t input)
{
  data_pipe_t rv = data_pipe_reg;
  uint32_t i;
  for(i=(FIR_N_TAPS-1); i>0; i=i-1)
  {
    data_pipe_reg.data[i] = data_pipe_reg.data[i-1];
  }
  data_pipe_reg.data[0] = input;
  return rv;
}

// the FIR filter function
output_t fir_main(data_t input, coeff_t coeffs[FIR_N_TAPS])
{
  // buffer up N datas in shift reg
  data_pipe_t data_pipe = data_pipe_func(input);
  
  // A binary tree of adders is used to sum the results of the multiplies
  // This binary tree has 
  //    FIR_N_TAPS elements at the base
  //    LOG2_FIR_N_TAPS + 1 levels in the tree
  output_t tree_nodes[LOG2_FIR_N_TAPS+1][FIR_N_TAPS]; // Oversized 2d array, unused elements optimize away
  // Ex. N=16 
  // Sum N values 'as parallel as possible' using a binary tree 
  //    Level 0: 16 input values  
  //    Level 1: 8 adders in parallel 
  //    Level 2: 4 adders in parallel 
  //    Level 3: 2 adders in parallel 
  //    Level 4: 1 final adder  

  // The first level of the tree is the result of the data*coeff
  // Parallel multiplications
  uint32_t i;
  for(i=0; i < FIR_N_TAPS; i+=1)
  {
    tree_nodes[0][i] = data_pipe.data[i] * coeffs[i];
  }
    
  // Do the summation starting at level 1
  uint32_t n_adds = FIR_N_TAPS/2; 
  uint32_t level; 
  for(level=1; level<(LOG2_FIR_N_TAPS+1); level+=1) 
  {   
    // Parallel sums  
    for(i=0; i<n_adds; i+=1)  
    { 
      tree_nodes[level][i] = tree_nodes[level-1][i*2] + tree_nodes[level-1][(i*2)+1]; 
    } 
      
    // Each level decreases adders by half  
    n_adds = n_adds / 2;  
  } 
    
  // Sum is last node in tree
  output_t sum = tree_nodes[LOG2_FIR_N_TAPS][0];
    
  return sum;
}
