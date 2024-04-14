#pragma once
#include "wire.h"
#include "uintN_t.h"

// Individual four leds 0-3
#include "led0_3_ports.c"

// Globally visible port/wire name
uint4_t leds; 

// Declares leds_module as a module with top level ports, no set clock frequency
// Return value is wire out to LEDs
#pragma MAIN leds_module
#pragma FUNC_WIRES leds_module
void leds_module()
{
  // Read uint4 port wire
  uint4_t leds_wire = leds;
  
  // Drive the individual leds with the bits of the uint4
  uint1_t bit0 = leds_wire >> 0;
  uint1_t bit1 = leds_wire >> 1;
  uint1_t bit2 = leds_wire >> 2;
  uint1_t bit3 = leds_wire >> 3;
  led0 = bit0;
  led1 = bit1;
  led2 = bit2;
  led3 = bit3;
}



