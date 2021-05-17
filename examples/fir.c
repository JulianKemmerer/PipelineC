#include "uintN_t.h"
#pragma MAIN_MHZ fir_main 500.0

#define data_t uint16_t
#define coeff_t uint16_t
#define FIR_N_TAPS 16
#define LOG2_FIR_N_TAPS 4 // log2(FIR_N_TAPS)
#define output_t uint36_t // data_width + coeff_width + log2(taps#)

// Func to 'static' buffer up the coeffs by shifting into shift reg
typedef struct coeffs_array_t
{
  coeff_t data[FIR_N_TAPS];
}coeffs_array_t;
coeffs_array_t coeff_config_func(coeff_t coeff, uint1_t wr_en)
{
  static coeffs_array_t coeffs;
  coeffs_array_t rv = coeffs;
  if(wr_en)
  {
    uint32_t i;
    for(i=(FIR_N_TAPS-1); i>0; i=i-1)
    {
      coeffs.data[i] = coeffs.data[i-1];
    }
    coeffs.data[0] = coeff;
  }
  return rv;
}

// Func to 'static' buffer up N samples (shift reg)
typedef struct sample_window_t
{
  data_t data[FIR_N_TAPS];
}sample_window_t;
sample_window_t sample_window_func(data_t input)
{
  static sample_window_t window;
  sample_window_t rv = window;
  uint32_t i;
  for(i=(FIR_N_TAPS-1); i>0; i=i-1)
  {
    window.data[i] = window.data[i-1];
  }
  window.data[0] = input;
  return rv;
}

// The FIR filter pipeline
output_t fir_main(data_t input, coeff_t coeff_in, uint1_t coeff_wr_en)
{
  // Allow filer coeffs to be config'd by shifting into shift reg
  coeffs_array_t coeffs = coeff_config_func(coeff_in, coeff_wr_en);
  // buffer up N datas in shift reg
  sample_window_t sample_window = sample_window_func(input);
  
  // A binary tree of adders is used to sum the results of the coeff*data multiplies
  // This binary tree has 
  //    FIR_N_TAPS elements at the base
  //    LOG2_FIR_N_TAPS + 1 levels in the tree
  output_t tree_nodes[LOG2_FIR_N_TAPS+1][FIR_N_TAPS]; // Oversized 2D array, unused elements optimize away
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
    tree_nodes[0][i] = sample_window.data[i] * coeffs.data[i];
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
