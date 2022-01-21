#pragma once
#include "wire.h"
#include "uintN_t.h"
#include "cdc.h"

// Globally visible port/wire name
uint4_t switches; 
#include "clock_crossing/switches.h"

// Declares switches_module as a module with top level ports, no set clock frequency
// Input value is wire from switches
#pragma MAIN switches_module
uint4_t switches_input_regs[2]; // Good practice to double reg inputs
void switches_module(uint4_t sw)
{
  // Double register input signal
  uint4_t sw_registered;
  CDC2(uint4_t, sw_cdc, sw_registered, sw)
  
  // Drive the output port with input
  WIRE_WRITE(uint4_t, switches, sw_registered) // switches = sw_registered
}
