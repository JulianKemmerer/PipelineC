#include "uintN_t.h"
#include "float_e_m_t.h"
#pragma MAIN main
uint16_t main(uint32_t x, float f, float_8_23_t femt, uint32_t sel)
{
  /* Arrays (esp. var ref rd) harder do later
  x[3] = 0;
  uint1_t b = x[3];
  return b; */
  uint16_t y = x(15, 0); // y = x[15:0]
  uint1_t b1 = x(3); // b1 = x[3];
  uint1_t b2 = x(3, 3); // b2 = x[3:3];
  //uint1_t bad_rand_access = x(sel);
  uint32_t f_as_u32 = f(31, 0); // f_as_u32 = f[31:0]
  uint32_t femt_as_u32 = femt(31, 0); // f_as_u32 = f[31:0]  
  return uint32_15_0(f_as_u32|y|b1|b2); // old test
}