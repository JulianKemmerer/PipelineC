

/*
// II=II slow binary tree of II elements
// II=3 is faked as II=2 would be just one op
stream(uint8_t) test_3tree(uint8_t x[3], uint1_t valid){
  stream(uint8_t) rv;
  rv.data = x[0] + x[1] + x[2];
  rv.valid = valid;
  return rv;
}

#define slow_name test
#define slow_II 3
#define slow_IIdiv2_II_tree test_3tree
*/
#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"

#include "slow_binary_tree.h"

// Adder tree of u8s
DECL_STREAM_TYPE(uint8_t)
#define slow_out_t uint8_t
#define slow_tree_t uint8_t
#define slow_in_t uint8_t 
#define slow_OP +
#define SLOW_N_INPUTS 15
// How slow?
#define slow_II CEIL_DIV(SLOW_N_INPUTS,2) // maximum=least resources=N inputs / 2


// N inputs = II 
// II=1 tree of 2 elements
// do_not_use_slow_funcs_with_II_of_1
/*DECL_SLOW_BINARY_TREE(
  tree8, CEIL_DIV(slow_II,8), none,
  slow_tree_t, slow_tree_t, slow_tree_t, slow_OP, CEIL_DIV(slow_II,4)
)*/
// Termination case
stream(slow_tree_t) tree8(slow_tree_t data[2], uint1_t valid){
  stream(slow_tree_t) rv;
  rv.data = data[0] slow_OP data[1];
  rv.valid = valid;
  return rv;
}
// II=2 tree of 4 elements
DECL_SLOW_BINARY_TREE(
  tree4, CEIL_DIV(slow_II,4), tree8,
  slow_tree_t, slow_tree_t, slow_tree_t, slow_OP, CEIL_DIV(slow_II,2)
)
// II=4 tree of 8 elements
DECL_SLOW_BINARY_TREE(
  tree2, CEIL_DIV(slow_II,2), tree4,
  slow_tree_t, slow_tree_t, slow_tree_t, slow_OP, slow_II // div by 1
)
// ^ Component faster II/2 trees of II elements
// Base binary tree, II=n inputs/2=8
DECL_SLOW_BINARY_TREE(
  the_binary_tree, slow_II, tree2,
  slow_out_t, slow_tree_t, slow_in_t, slow_OP, SLOW_N_INPUTS
)

#pragma MAIN main
void main()
{
  static uint32_t cycle = 0;
  uint1_t valid = cycle ==0;
  uint8_t x[SLOW_N_INPUTS];
  uint32_t i;
  uint8_t correct_sum = 0;
  for ( i = 0; i < SLOW_N_INPUTS; i+=1)
  {
    x[i] = i;
    correct_sum += i;
  }
  stream(uint8_t) out_stream = the_binary_tree(x, valid);
  if(out_stream.valid){
    printf("Cycle %d: sum = %d (expected %d)\n", cycle, out_stream.data, correct_sum);
  }
  cycle += 1;
}