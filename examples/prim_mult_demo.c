#include "uintN_t.h"
#include "intN_t.h"

// Set device and include device primitives
#pragma PART "LFE5U-85F-6BG381C"
#include "primitives/ecp5.c"
#define mul18x18 ECP5_MUL18X18

#pragma MAIN_MHZ main 500.0
uint36_t main(uint18_t a, uint18_t b)
{
  return mul18x18(a, b);
}

/*
#define N_INPUTS 64
#define LOG2_N_INPUTS 6 // log2(N_INPUTS)
#pragma MAIN_MHZ binary_tree_mults 315.0
uint18_t binary_tree_mults(uint18_t x[N_INPUTS])
{
  // This binary tree has 
  //    N_INPUTS elements at the base
  //    LOG2_N_INPUTS + 1 levels in the tree
  // Oversized 2D array, unused elements optimize away
  uint18_t tree_nodes[LOG2_N_INPUTS+1][N_INPUTS]; 
  // Ex. N=16 
  //    Level 0: 16 input values  
  //    Level 1: 8 ops in parallel 
  //    Level 2: 4 ops in parallel 
  //    Level 3: 2 ops in parallel 
  //    Level 4: 1 final op

  // The first level of the tree is inputs
  uint32_t i;
  for(i=0; i < N_INPUTS; i+=1)
  {
    tree_nodes[0][i] = x[i];
  }
    
  // Do the tree starting at level 1
  uint32_t n_ops = N_INPUTS/2; 
  uint32_t level; 
  for(level=1; level<(LOG2_N_INPUTS+1); level+=1) 
  {   
    // Parallel ops  
    for(i=0; i<n_ops; i+=1)
    { 
      tree_nodes[level][i] = mul18x18(tree_nodes[level-1][i*2], tree_nodes[level-1][(i*2)+1]);
    } 
      
    // Each level decreases ops by half  
    n_ops = n_ops / 2;  
  } 
    
  // Output is last node in tree
  uint18_t rv = tree_nodes[LOG2_N_INPUTS][0];
    
  return rv;
}
*/