#pragma once
#include "wire.h"
#include "uintN_t.h"

// PMOD pins can be input or outputs (or both)
// Only support in OR out, not inout

// Add/remove pmod pins as in vs out below
// Inputs
typedef struct pmod_ja_to_app_t
{
  uint1_t ja0;
  uint1_t ja1;
  uint1_t ja2;
  uint1_t ja3;
  uint1_t ja4;
  uint1_t ja5;
  uint1_t ja6;
  uint1_t ja7;
}pmod_ja_to_app_t;
// Outputs
typedef struct app_to_pmod_ja_t
{
  uint1_t ja0;
  uint1_t ja1;
  uint1_t ja2;
  uint1_t ja3;
  uint1_t ja4;
  uint1_t ja5;
  uint1_t ja6;
  uint1_t ja7;
}app_to_pmod_ja_t;

// Globally visible ports/wires
pmod_ja_to_app_t pmod_ja_to_app;
app_to_pmod_ja_t app_to_pmod_ja;
#include "clock_crossing/pmod_ja_to_app.h"
#include "clock_crossing/app_to_pmod_ja.h"

// Top level module connecting to globally visible ports
#pragma MAIN pmod_ja // No associated clock domain yet
app_to_pmod_ja_t pmod_ja(pmod_ja_to_app_t inputs)
{
  app_to_pmod_ja_t outputs;
  WIRE_READ(app_to_pmod_ja_t, outputs, app_to_pmod_ja)
  WIRE_WRITE(pmod_ja_to_app_t, pmod_ja_to_app, inputs)
  return outputs;
}
