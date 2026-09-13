// Build fixture for autopipeline_c_pragma_test.py: C frontend
// `#pragma AUTOPIPELINE N` is a fixed latency of N inserted registers, built
// even by a --comb build (no PART: PyRTL delay model).
#include "uintN_t.h"

uint8_t c_pragma_core(uint8_t x)
{
  uint8_t a = x / ~x;
  return a / (x + 1);
}

#pragma MAIN_MHZ main 10.0
uint8_t main(uint8_t x)
{
  static uint1_t toggle;
  toggle = ~toggle;
  uint8_t rv;
  #pragma AUTOPIPELINE 2
  rv = c_pragma_core(x);
  return rv;
}
