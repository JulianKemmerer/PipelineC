
/*Repeating better compares --comb and pipeline experiments...
>,>=,<,<= for signed and unsigned 32b ops*/
#include "intN_t.h"
#include "uintN_t.h"
#pragma PART "5CSEMA5F31C6" // Roughly the next size up Cyclone V from Analogue Pocket
#pragma MAIN main
/* #define TEST_OP >
// GT > resizes right
// GTE >= resizes left
// LT < resizes left
// LTE <= resizes right
#define TEST_LTYPE int32_t
#define TEST_RTYPE int2_t 
uint1_t main(TEST_LTYPE x, TEST_RTYPE y)
{
  return x TEST_OP y;
}*/

/*int33_t sub_as_adds(int32_t left, int32_t right){
  // left-right 
  uint32_t r = ~right+1;
  return left+r;
}*/




uint1_t signed_GT_as_sub(int32_t left, int2_t right)
{
  //int33_t sub = sub_as_adds(right, left);
  int33_t sub = right - left;
  uint1_t lt_zero = sub(32,32);
  return lt_zero;        
}

// TRY IMPLEMENTING SIGNED COMPARE
// AS UNSIGNED COMPARE plus sign logic like raw hdl
//check out better comapres and make signed implemnted as unsigned


uint1_t signed_GT_as_unsigned_gt(int32_t left, int2_t right)
{ 
  int32_t right_ext = right;
  uint1_t lsign = left(31,31);
  uint1_t rsign = right_ext(31,31);
  uint1_t signs_different = lsign ^ rsign;
  uint31_t lunsigned = left;
  uint31_t runsigned = right_ext;
  // Same sign only compare unsigned magnitude, twos complement makes it make sense
  uint1_t unsigned_gt = lunsigned > runsigned;
  uint1_t rv;
  if(signs_different){
    rv = rsign;
  }else{
    rv = unsigned_gt;
  }
  return rv;      
}

uint1_t main(int32_t x, int2_t y)
{
  return signed_GT_as_unsigned_gt(x,y); // vs "x>y"
}



