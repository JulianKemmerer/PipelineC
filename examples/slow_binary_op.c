#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"

#include "slow_binary_op.h"

// Do many binary operations using fewer resources at slow II
DECL_STREAM_TYPE(uint16_t)
#define slow_out_t uint16_t
#define slow_in_t uint16_t
#define slow_OP +
#define SLOW_N_INPUTS 255
// How slow?
#define slow_II SLOW_N_INPUTS // maximum=N inputs

// Base binary tree, II=n inputs/2
DECL_SLOW_BINARY_OP(
  the_binary_ops, slow_II,
  slow_out_t, slow_OP, slow_in_t, slow_in_t, SLOW_N_INPUTS
)

#pragma MAIN main
void main()
{
  static uint32_t cycle = 0;
  uint1_t valid = cycle ==0;
  slow_in_t x[SLOW_N_INPUTS];
  slow_in_t y[SLOW_N_INPUTS];
  uint32_t i;
  slow_out_t correct_output[SLOW_N_INPUTS];
  for(i = 0; i < SLOW_N_INPUTS; i+=1)
  {
    x[i] = i;
    y[i] = i;
    correct_output[i] = x[i] slow_OP y[i];
  }
  the_binary_ops_out_t out_stream = the_binary_ops(x, y, valid);
  if(out_stream.valid){
    for(i = 0; i < SLOW_N_INPUTS; i+=1)
    {
      printf("Cycle %d: output[%d] = %d (expected %d)\n", cycle, i, out_stream.data[i], correct_output[i]);
    }
  }
  cycle += 1;
}