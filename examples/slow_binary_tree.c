#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"

#include "slow_binary_tree.h"

DECL_STREAM_TYPE(uint8_t)

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
#define slow_out_t uint8_t
#define slow_tree_t uint8_t
#define slow_in_t uint8_t 
#define slow_OP +
#define SLOW_N_INPUTS 15


DECL_SLOW_BINARY_TREE(
  slow_name, slow_II, slow_IIdiv2_II_tree,
  slow_out_t, slow_tree_t, slow_in_t, slow_OP, SLOW_N_INPUTS
)

#pragma MAIN main
void main()
{
  static uint32_t cycle = 0;
  uint1_t valid = cycle ==0;
  uint8_t x[15];
  uint32_t i;
  uint8_t correct_sum = 0;
  for ( i = 0; i < 15; i+=1)
  {
    x[i] = i;
    correct_sum += i;
  }
  stream(uint8_t) out_stream = test(x, valid);
  if(out_stream.valid){
    printf("Cycle %d: sum = %d (expected %d)\n", cycle, out_stream.data, correct_sum);
  }
  cycle += 1;
}