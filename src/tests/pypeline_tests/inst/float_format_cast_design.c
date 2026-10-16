// Known issue #376: the C front end converts between float formats by wrapping the
// connection in the VHDL function resize_float_e_m_t, not with an operator.
// See float_format_cast_test.py.
#include "uintN_t.h"
#include "float_e_m_t.h"

// Only converts float to float_5_10_t, so it has no submodules
float_5_10_t to_half(float x)
{
  return x;
}

#pragma MAIN half_top
float_5_10_t half_top(float x)
{
  return to_half(x);
}

// x is converted to float_5_10_t inside select_half's own body, where it
// feeds the MUX submodule that the if makes
#pragma MAIN select_half
float_5_10_t select_half(uint1_t sel, float x, float_5_10_t y)
{
  float_5_10_t rv = y;
  if(sel)
  {
    rv = x;
  }
  return rv;
}
