
//#pragma PART "xc7a100tcsg324-1"
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN_MHZ main 1000.0
#define elem_t uint5_t
#define SIZE 16
#define LOG2_SIZE 4
elem_t main(elem_t x[SIZE], elem_t y[SIZE])
{
  // First element wise sum
  elem_t xy_sum[SIZE];
  uint32_t i;
  for (i = 0; i < SIZE; i+=1)
  {
    xy_sum[i] = x[i] + y[i];
  }

  // Binary tree of adders accumulate sum
  // This binary tree has 
  //    SIZE elements at the base
  //    LOG2_SIZE + 1 levels in the tree
  // Oversized 2D array, unused elements optimize away
  elem_t tree_nodes[LOG2_SIZE+1][SIZE]; 
  // Ex. N=16 
  // Sum N values 'as parallel as possible' using a binary tree 
  //    Level 0: 16 input values  
  //    Level 1: 8 adders in parallel 
  //    Level 2: 4 adders in parallel 
  //    Level 3: 2 adders in parallel
  //    Level 4: 1 final adder  

  // The first level of the tree is input element wise sum
  // Parallel multiplications
  uint32_t i;
  for(i=0; i < SIZE; i+=1)
  {
    tree_nodes[0][i] = xy_sum[i];
  }
    
  // Do the summation starting at level 1
  uint32_t n_adds = SIZE/2; 
  uint32_t level; 
  for(level=1; level<(LOG2_SIZE+1); level+=1) 
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
  elem_t sum = tree_nodes[LOG2_SIZE][0];
  return sum;
}