#include "uintN_t.h"
#include "intN_t.h"

// Set device and include device primitives
#pragma PART "LFE5U-85F-6BG381C"
#include "primitives/ecp5.c"
#define mul18x18 ECP5_MUL18X18

#pragma MAIN_MHZ main 500.0
uint36_t main(uint18_t a, uint18_t b)
{
  return mul18x18(a, b);
}
