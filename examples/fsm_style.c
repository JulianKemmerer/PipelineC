
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN test0
uint32_t test0(uint32_t x)
{
  uint32_t rv = x + 1;
  return rv;
}

uint32_t test1(uint32_t x)
{
  __clk();
  uint32_t rv = x + 1;
  return rv;
}
#include "test1_FSM.h"
#pragma MAIN test1_wrapper
uint32_t test1_wrapper()
{
  test1_INPUT_t i;
  i.x = 2;
  i.input_valid = 1;
  i.output_ready = 1;
  test1_OUTPUT_t o = test1_FSM(i);
  return o.return_output;
}

uint32_t test2(uint32_t x)
{
  uint32_t rv = x + 1;
  __clk();
  return rv;
}
#include "test2_FSM.h"
#pragma MAIN test2_wrapper
uint32_t test2_wrapper()
{
  test2_INPUT_t i;
  i.x = 2;
  i.input_valid = 1;
  i.output_ready = 1;
  test2_OUTPUT_t o = test2_FSM(i);
  return o.return_output;
}


/*
restart
force -freeze sim:/top/clk_None 1 0, 0 {50 ps} -r 100
force -freeze sim:/top/test0_0CLK_b45f1687/x 00000000000000000000000000000010 0
*/

