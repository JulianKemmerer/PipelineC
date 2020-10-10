#pragma once
#include "wire.h"
#include "uintN_t.h"

// Globally visible port/wire name
uint4_t switches; 
// This should be in a macro somehow TODO \/
#include "uint4_t_array_N_t.h"
#include "switches_clock_crossing.h"

// Declares switches_module as a module with top level ports, no set clock frequency
// Input value is wire from switches
#pragma MAIN switches_module
void switches_module(uint4_t sw)
{
  // Drive the output port with input
  WIRE_WRITE(uint4_t, switches, sw) // switches = sw
}
