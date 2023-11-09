#pragma PART "xc7a100tcsg324-1"

#include "uintN_t.h"
#include "arrays.h"

// treat const args like future template arg

uint32_t add(uint32_t x, uint32_t c)
{
  return x + c;
}
//#pragma MAIN main_add
uint32_t main_add(uint32_t x)
{
  // Same as template add<1>(x);
  return add(x, 1);
}

/* Transformed into
uint32_t add_const_1(uint32_t x)
{
  uint32_t c = 1;
  return x + c;
}
uint32_t main(uint32_t x)
{
  return add_const_1(x);
}*/


float add_float(float x, float c)
{
  return x + c;
}
//#pragma MAIN main_add_float
float main_add_float(float x)
{
  return add_float(x, 1.23);
}



uint1_t shift_reg(uint32_t size, uint1_t din, uint1_t enable){
  static uint1_t the_regs[size];
  uint1_t rv = the_regs[0];
  if(enable){
    ARRAY_1SHIFT_INTO_TOP(the_regs, size, din)
  }
  return rv;
}
//#pragma MAIN main_shift_reg
uint1_t main_shift_reg(uint1_t din, uint1_t enable){
  return shift_reg(3, din, enable);
}



uint32_t add_const_array(uint32_t x, uint32_t c)
{
  // Constant unrolled loop
  // Arrays?
  uint32_t a[c+1];
  a[0] = x;
  uint32_t i;
  for (i = 1; i < (c+1); i+=1)
  {
    a[i-1] += 1;
    a[i] = a[i-1];
  }
  return a[c];
}
//#pragma MAIN main_add_const_array
uint32_t main_add_const_array(uint32_t x)
{
  return add_const_array(x, 3);
}
