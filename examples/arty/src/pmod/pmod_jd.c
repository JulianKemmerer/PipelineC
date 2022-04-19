#pragma once
#include "wire.h"
#include "uintN_t.h"

// PMOD pins can be input or outputs (or both)
// Only support in OR out, not inout

// Add/remove pmod pins as in vs out below
// Inputs
/*typedef struct pmod_jd_to_app_t
{
  //uint1_t jd0
  //uint1_t jd1;
  //uint1_t jd2;
  //uint1_t jd3;
  //uint1_t jd4;
  //uint1_t jd5;
  //uint1_t jd6;
  //uint1_t jd7;
}pmod_jd_to_app_t;*/
// Outputs
typedef struct app_to_pmod_jd_t
{
  uint1_t jd0;
  uint1_t jd1;
  uint1_t jd2;
  uint1_t jd3;
  uint1_t jd4;
  uint1_t jd5;
  uint1_t jd6;
  uint1_t jd7;
}app_to_pmod_jd_t;

// Globally visible ports/wires
//pmod_jd_to_app_t pmod_jd_to_app;
app_to_pmod_jd_t app_to_pmod_jd;
//#include "clock_crossing/pmod_jd_to_app.h"
#include "clock_crossing/app_to_pmod_jd.h"

// Top level module connecting to globally visible ports
#pragma MAIN pmod_jd // No associated clock domain yet
app_to_pmod_jd_t pmod_jd(/*pmod_jd_to_app_t inputs*/)
{
  app_to_pmod_jd_t outputs;
  WIRE_READ(app_to_pmod_jd_t, outputs, app_to_pmod_jd)
  //WIRE_WRITE(pmod_jd_to_app_t, pmod_jd_to_app, inputs)
  return outputs;
}
