// Access to individual LEDs

#pragma once
#include "wire.h"
#include "uintN_t.h"

// TODO DO BETTER THAN COPY PASTE - MACRO ME FOOL

uint1_t led0; 
#include "uint1_t_array_N_t.h"
#include "led0_clock_crossing.h"
#pragma MAIN led0_module
uint1_t led0_module()
{
  uint1_t out_wire;
  WIRE_READ(uint1_t, out_wire, led0)
  return out_wire;
}

uint1_t led1; 
#include "uint1_t_array_N_t.h"
#include "led1_clock_crossing.h"
#pragma MAIN led1_module
uint1_t led1_module()
{
  uint1_t out_wire;
  WIRE_READ(uint1_t, out_wire, led1)
  return out_wire;
}

uint1_t led2; 
#include "uint1_t_array_N_t.h"
#include "led2_clock_crossing.h"
#pragma MAIN led2_module
uint1_t led2_module()
{
  uint1_t out_wire;
  WIRE_READ(uint1_t, out_wire, led2)
  return out_wire;
}

uint1_t led3; 
#include "uint1_t_array_N_t.h"
#include "led3_clock_crossing.h"
#pragma MAIN led3_module
uint1_t led3_module()
{
  uint1_t out_wire;
  WIRE_READ(uint1_t, out_wire, led3)
  return out_wire;
}



