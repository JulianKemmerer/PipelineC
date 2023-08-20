#pragma once
#include "uintN_t.h"
#include "cdc.h"

// Globally visible port/wire name
uint4_t switches; 

// Declares switches_module as a module with top level ports, no set clock frequency
// Input value is wire from switches
#pragma MAIN switches_module
void switches_module(uint4_t sw)
{
  // Double register input signal
  uint4_t sw_registered;
  CDC2(uint4_t, sw_cdc, sw_registered, sw)
  
  // Drive the output port with input
  switches = sw_registered;
}