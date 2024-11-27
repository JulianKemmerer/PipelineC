#pragma once

#define DECL_BINARY_OP_TREE(name, out_t, tree_t, in_t, OP, SIZE, CEIL_LOG2_SIZE)\
out_t name(in_t data[SIZE]) \
{ \
  /* This binary tree has */\
  /*    N elements at the base*/\
  /*    LOG2_N + 1 levels in the tree*/\
  /* Oversized 2D array, unused elements optimize away*/\
  tree_t tree_nodes[CEIL_LOG2_SIZE+1][SIZE]; \
  uint32_t i; \
  for(i=0; i < SIZE; i+=1) \
  { \
    tree_nodes[0][i] = data[i]; \
  } \
  /* Ex. N=5*/\
  /* Sum N values 'as parallel as possible' using a binary tree */\
  /*    Level 0: 5 input values  */\
  /*    Level 1: 2 adders in parallel, 1 value left over*/\
  /*    Level 2: 1 adders in parallel, 1 value left over*/\
  /*    Level 3: 1 final adder*/\
 \
  /* Do the ops starting at level 1*/\
  uint32_t n_inputs_curr = SIZE; \
  uint32_t n_inputs_next = 0;  \
  uint32_t level;  \
  for(level=1; level<(CEIL_LOG2_SIZE+1); level+=1)  \
  {    \
    /* Parallel operations single level*/\
    uint32_t op_count = 0; \
    while(n_inputs_curr > 0){ \
      /* Mostly binary op pairs*/\
      if(n_inputs_curr > 1){ \
        tree_nodes[level][op_count] = tree_nodes[level-1][op_count*2] OP tree_nodes[level-1][(op_count*2)+1]; \
        op_count += 1; \
        n_inputs_curr -= 2; \
        n_inputs_next += 1; \
      }else{ \
        /* Left over single element*/\
        tree_nodes[level][op_count] = tree_nodes[level-1][op_count*2]; \
        n_inputs_curr -= 1; \
        n_inputs_next += 1; \
      } \
    } \
    \
    /* Prepare for next level*/\
    n_inputs_curr = n_inputs_next; \
    n_inputs_next = 0; \
  }  \
     \
  /* Result is last node in tree*/\
  out_t result = tree_nodes[CEIL_LOG2_SIZE][0]; \
  return result; \
}
