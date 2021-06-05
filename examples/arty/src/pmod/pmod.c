#pragma once
#include "wire.h"
#include "uintN_t.h"

// Only supporting one PMOD port for now...

// PMOD pins can be input or outputs (or both)
// Only support in OR out, not inout
// Add/remove pmod pins as in vs out below
// Inputs
typedef struct pmod_to_app_t
{
  //uint1_t ja0
  //uint1_t ja1;
  //uint1_t ja2;
  //uint1_t ja3;
  //uint1_t ja4;
  //uint1_t ja5;
  //uint1_t ja6;
  uint1_t ja7;
}pmod_to_app_t;
// Outputs
typedef struct app_to_pmod_t
{
  //uint1_t ja0; // Clock not driven by PipelineC code
  uint1_t ja1;
  uint1_t ja2;
  uint1_t ja3;
  //uint1_t ja4; // Clock not driven by PipelineC code
  uint1_t ja5;
  uint1_t ja6;
  //uint1_t ja7;
}app_to_pmod_t;

// Globally visible ports/wires
pmod_to_app_t pmod_to_app;
app_to_pmod_t app_to_pmod;
// These should be in a macro/autogen somehow TODO \/
#include "pmod_to_app_t_array_N_t.h"
#include "pmod_to_app_clock_crossing.h"
#include "app_to_pmod_t_array_N_t.h"
#include "app_to_pmod_clock_crossing.h"

// Top level module connecting to globally visible ports
#pragma MAIN pmod_ja // No associated clock domain yet
app_to_pmod_t pmod_ja(pmod_to_app_t inputs)
{
  app_to_pmod_t outputs;
  WIRE_READ(app_to_pmod_t, outputs, app_to_pmod)
  WIRE_WRITE(pmod_to_app_t, pmod_to_app, inputs)
  return outputs;
}
