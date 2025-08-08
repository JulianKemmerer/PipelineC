#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"

/* Ex. this header configured like
// REQUIRED
#define FIXED_TOTAL_BITS 16
#define FIXED_FRACTIONAL_BITS 8
// OPTIONAL
#define FIXED_TYPE_NAME my_fixed_t
#define FIXED_UNSIGNED
*/

// Base integer type for fixed point representation
#ifdef FIXED_UNSIGNED
#ifndef FIXED_TYPE_NAME
#define FIXED_TYPE_NAME PPCAT(PPCAT(PPCAT(PPCAT(PPCAT(uint,FIXED_TOTAL_BITS),_),fixed),FIXED_FRACTIONAL_BITS),_t)
#endif
#define fixed_int_t PPCAT(PPCAT(uint,FIXED_TOTAL_BITS),_t)
#else
#ifndef FIXED_TYPE_NAME
#define FIXED_TYPE_NAME PPCAT(PPCAT(PPCAT(PPCAT(PPCAT(int,FIXED_TOTAL_BITS),_),fixed),FIXED_FRACTIONAL_BITS),_t)
#endif
#define fixed_int_t PPCAT(PPCAT(int,FIXED_TOTAL_BITS),_t)
#endif

typedef struct FIXED_TYPE_NAME{
  fixed_int_t bits;
} FIXED_TYPE_NAME;

// Global constant _FRAC_BITS for fractional bits
uint32_t PPCAT(PPCAT(FIXED_TYPE_NAME,_),FRAC_BITS) = FIXED_FRACTIONAL_BITS;

// Overload '+' operator
FIXED_TYPE_NAME PPCAT(PPCAT(PPCAT(BIN_OP_PLUS_,FIXED_TYPE_NAME),_),FIXED_TYPE_NAME)(FIXED_TYPE_NAME left, FIXED_TYPE_NAME right)
{
  FIXED_TYPE_NAME result;
  result.bits = left.bits + right.bits;
  return result;
}

#undef FIXED_TYPE_NAME
#undef FIXED_TOTAL_BITS
#undef FIXED_FRACTIONAL_BITS
#undef fixed_int_t
#ifdef FIXED_UNSIGNED
#undef FIXED_UNSIGNED
#endif
