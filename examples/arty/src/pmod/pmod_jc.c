#pragma once
#include "wire.h"
#include "uintN_t.h"

// PMOD pins can be input or outputs (or both)
// Only support in OR out, not inout

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct pmod_jc_to_app_t
{
  //uint1_t jc0
  //uint1_t jc1;
  //uint1_t jc2;
  //uint1_t jc3;
  //uint1_t jc4;
  //uint1_t jc5;
  //uint1_t jc6;
  //uint1_t jc7;
}pmod_jc_to_app_t;*/
// Outputs
typedef struct app_to_pmod_jc_t
{
  uint1_t jc0;
  uint1_t jc1;
  uint1_t jc2;
  uint1_t jc3;
  uint1_t jc4;
  uint1_t jc5;
  uint1_t jc6;
  uint1_t jc7;
}app_to_pmod_jc_t;

// Globally visible ports/wires
//pmod_jc_to_app_t pmod_jc_to_app;
app_to_pmod_jc_t app_to_pmod_jc;
//#include "clock_crossing/pmod_jc_to_app.h"
#include "clock_crossing/app_to_pmod_jc.h"

// Top level module connecting to globally visible ports
#pragma MAIN pmod_jc // No associated clock domain yet
app_to_pmod_jc_t pmod_jc(/*pmod_jc_to_app_t inputs*/)
{
  app_to_pmod_jc_t outputs;
  WIRE_READ(app_to_pmod_jc_t, outputs, app_to_pmod_jc)
  //WIRE_WRITE(pmod_jc_to_app_t, pmod_jc_to_app, inputs)
  return outputs;
}
