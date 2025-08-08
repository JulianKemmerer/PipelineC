#include "fixed/float_conv.h" // fixed_to_float, fixed_init_from_float macros

// Declare a fixed point type and associated overloaded operations
//  16 total bits, 8 fractional bits 
// If name not given, ex. int16_fixed8_t is type name
#define FIXED_TYPE_NAME my_fixed_t   
// these lines with no name could be put into "fixed/int16_fixed8_t.h"
#define FIXED_TOTAL_BITS 16
#define FIXED_FRACTIONAL_BITS 8
#include "fixed/type_decl.h"

// Test
//#pragma PART "xc7a100tcsg324-1"
#pragma MAIN main
my_fixed_t main()
{
  my_fixed_t a = fixed_init_from_float(1.05, my_fixed_t);
  printf("a: %f\n", fixed_to_float(a, my_fixed_t));
  my_fixed_t b = fixed_init_from_float(3.15, my_fixed_t);
  printf("b: %f\n", fixed_to_float(b, my_fixed_t));
  my_fixed_t c = a + b;
  printf("c: %f\n", fixed_to_float(c, my_fixed_t));
  return c;
}
