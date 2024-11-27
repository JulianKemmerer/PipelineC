#pragma once
// Expose 4 buttons as top level inputs
// connected to globally visible wire

#include "uintN_t.h"
#include "cdc.h"

// Globally visible port/wire name
uint4_t buttons;

// Declares as a module with top level ports, no set clock frequency
// Input value is wire from buttons
#pragma MAIN buttons_module
void buttons_module(uint4_t btn)
{
  // Double register input signal
  #ifdef BUTTONS_NO_CDC
  // No cdc direct connect
  buttons = btn;
  #else
  // Typical double reg CDC for async button input
  uint4_t registered;
  CDC2(uint4_t, btn_cdc, registered, btn) // registered = btn
  // Drive the output port with input
  buttons = registered; // buttons = registered
  #endif
}
