#include "compiler.h"
#include "uintN_t.h"

// Types for arrays of data and coeffs
#define fir_samples_window_t PPCAT(fir_name,_samples_window_t)
typedef struct fir_samples_window_t{
  fir_data_t data[FIR_N_TAPS];
}fir_samples_window_t;

#define fir_samples_window_func PPCAT(fir_name,_sample_window_func)
fir_samples_window_t fir_samples_window_func(fir_data_t input)
{
  static fir_samples_window_t window;
  fir_samples_window_t rv = window;
  uint32_t i;
  for(i=(FIR_N_TAPS-1); i>0; i=i-1)
  {
    window.data[i] = window.data[i-1];
  }
  window.data[0] = input;
  return rv;
}

// The FIR filter pipeline
fir_out_t fir_name(fir_data_t input)
{
  // Constant set of coeffs
  fir_coeff_t coeffs[FIR_N_TAPS] = FIR_COEFFS;

  // buffer up N datas in shift reg
  fir_samples_window_t sample_window = fir_samples_window_func(input);
  
  // A binary tree of adders is used to sum the results of the coeff*data multiplies
  // This binary tree has 
  //    FIR_N_TAPS elements at the base
  //    LOG2_FIR_N_TAPS + 1 levels in the tree
  // Oversized 2D array, unused elements optimize away
  fir_out_t tree_nodes[FIR_LOG2_N_TAPS+1][FIR_N_TAPS]; 
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
    tree_nodes[0][i] = sample_window.data[i] * coeffs[i];
  }
    
  // Do the summation starting at level 1
  uint32_t n_adds = FIR_N_TAPS/2; 
  uint32_t level; 
  for(level=1; level<(FIR_LOG2_N_TAPS+1); level+=1) 
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
  fir_out_t sum = tree_nodes[FIR_LOG2_N_TAPS][0];
    
  return sum;
}


#undef fir_name
#undef FIR_N_TAPS
#undef FIR_LOG2_N_TAPS
#undef fir_data_t
#undef fir_coeff_t
#undef fir_out_t
#undef FIR_COEFFS