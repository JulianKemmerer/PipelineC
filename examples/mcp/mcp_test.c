#include "intN_t.h"
#include "uintN_t.h"
#pragma PART "xc7a35ticsg324-1l"

typedef struct my_struct_t{
  uint32_t field;
}my_struct_t;

my_struct_t big_comb_multi_cycle_func(my_struct_t x){
  my_struct_t rv;
  rv.field = x.field / ~x.field;
  return rv;
}

my_struct_t my_fsm(my_struct_t i){
  my_struct_t o;

  #pragma MULTI_CYCLE 32 data0 data1
  static my_struct_t data0;
  static my_struct_t data1;

  o = data1;
  data1 = big_comb_multi_cycle_func(data0);
  data0 = i;

  return o;
}

#pragma MAIN_MHZ wrapper 100
my_struct_t wrapper(my_struct_t x){
  my_struct_t rv;
  rv.field = x.field;
  for(uint32_t i=0;i<3;i+=1){
     my_struct_t f = my_fsm(rv);
     rv.field |= f.field;
  }
  return rv;
}