// Access to individual LEDs

#pragma once
#include "uintN_t.h"

// TODO DO BETTER THAN COPY PASTE - MACRO ME FOOL

uint1_t led0;
#pragma MAIN led0_module
#pragma FUNC_WIRES led0_module
uint1_t led0_module()
{
  uint1_t out_wire = led0;
  return out_wire;
}

uint1_t led1;
#pragma MAIN led1_module
#pragma FUNC_WIRES led1_module
uint1_t led1_module()
{
  uint1_t out_wire = led1;
  return out_wire;
}

uint1_t led2;
#pragma MAIN led2_module
#pragma FUNC_WIRES led2_module
uint1_t led2_module()
{
  uint1_t out_wire = led2;
  return out_wire;
}

uint1_t led3;
#pragma MAIN led3_module
#pragma FUNC_WIRES led3_module
uint1_t led3_module()
{
  uint1_t out_wire = led3;
  return out_wire;
}



