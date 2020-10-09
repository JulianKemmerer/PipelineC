#pragma once
#include "wire.h"
#include "uintN_t.h"

// Globally visible port/wire name
uint4_t leds; 
// This should be in a macro somehow TODO \/
#include "uint4_t_array_N_t.h"
#include "leds_clock_crossing.h"

// Declares leds_module as a module with top level ports
// Return value is wire out to LEDs
#pragma MAIN_MHZ leds_module 83.33  // Temp same as XIL_MIG_MHZ // UI CLK
uint4_t leds_module()
{
  // Drive the output port with the global wire
  uint4_t out_wire;
  WIRE_READ(uint4_t, out_wire, leds) // out_wire = leds
  return out_wire;
}
