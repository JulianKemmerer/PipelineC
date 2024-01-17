// Arbitrary width types
#include "uintN_t.h"
// FPGA part/synthesis tool
#pragma PART "xc7a35ticsg324-1l" 
// Specify two main functions
// (at different clock rates since
// timing reported by clock domain)
#pragma MAIN_MHZ my_adder 1000
#pragma MAIN_MHZ my_shifter 500

uint32_t my_adder(uint32_t x, uint32_t y){
  return x + y;
}
uint32_t my_shifter(uint32_t x, uint32_t y){
  return x << y;
}
