#pragma once
#include "wire.h"
#include "uintN_t.h"

// PMOD pins can be input or outputs (or both)
// Only support in OR out, not inout

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct pmod_jb_to_app_t
{
  //uint1_t jb0
  //uint1_t jb1;
  //uint1_t jb2;
  //uint1_t jb3;
  //uint1_t jb4;
  //uint1_t jb5;
  //uint1_t jb6;
  //uint1_t jb7;
}pmod_jb_to_app_t;*/
// Outputs
typedef struct app_to_pmod_jb_t
{
  uint1_t jb0;
  uint1_t jb1;
  uint1_t jb2;
  uint1_t jb3;
  uint1_t jb4;
  uint1_t jb5;
  uint1_t jb6;
  uint1_t jb7;
}app_to_pmod_jb_t;

// Globally visible ports/wires
//pmod_jb_to_app_t pmod_jb_to_app;
app_to_pmod_jb_t app_to_pmod_jb;
//#include "clock_crossing/pmod_jb_to_app.h"
#include "clock_crossing/app_to_pmod_jb.h"

// Top level module connecting to globally visible ports
#pragma MAIN pmod_jb // No associated clock domain yet
app_to_pmod_jb_t pmod_jb(/*pmod_jb_to_app_t inputs*/)
{
  app_to_pmod_jb_t outputs;
  WIRE_READ(app_to_pmod_jb_t, outputs, app_to_pmod_jb)
  //WIRE_WRITE(pmod_jb_to_app_t, pmod_jb_to_app, inputs)
  return outputs;
}
