#include "intN_t.h"
#include "uintN_t.h"

// Cant generate number of instances since not known until after elab
// User will specify and can be checked....
#define N_INSTS 3

uint32_t the_shared_global;
uint32_t read_only_wire;
#pragma MAIN test_func0
void test_func0(uint32_t i){
  // Not important whats here dummy logic...
  // uses read wire to drive write wire (with register)
  the_shared_global = the_shared_global + read_only_wire;
}
#pragma MAIN test_func1
void test_func1(uint32_t i){
  the_shared_global = the_shared_global + read_only_wire;
}
#pragma MAIN test_func2
void test_func2(uint32_t i){
  the_shared_global = the_shared_global + read_only_wire;
}
/*// Top level with 3 instances of the test_func
#pragma MAIN test_main
void test_main(uint32_t x[N_INSTS]){
  int32_t i;
  for(i=0; i<N_INSTS; i+=1){
    test_func(x[i]);
  }
}*/

// Opposite side of read/write only is write/read only arrays
uint32_t the_shared_global_RD_AR[N_INSTS];
#pragma INST_ARRAY the_shared_global the_shared_global_RD_AR
uint32_t read_only_wire_WR_AR[N_INSTS];
#pragma INST_ARRAY read_only_wire read_only_wire_WR_AR

// User writes some code using those arrays
#pragma MAIN arb_test
uint32_t arb_test(){
  // Not important whats here dummy logic...
  // uses read wire to drive write wire (with register)
  static uint32_t regs[N_INSTS];
  read_only_wire_WR_AR = regs;
  uint32_t dummy_output;
  int32_t i;
  for(i = 0; i < N_INSTS; i+=1)
  {
    dummy_output |= regs[i];
    regs[i] = !the_shared_global_RD_AR[i];
  }
  return dummy_output;
}
