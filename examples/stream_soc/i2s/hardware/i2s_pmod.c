#pragma once
#include "wire.h"
#include "uintN_t.h"

// TODO replace with include pmod_wires. top level wires instead of MAIN funcs
//#include "pmod/pmod_wires.h"

// TODO #define config for other pmod connectors
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
#pragma FUNC_WIRES pmod_ja
app_to_pmod_ja_t pmod_ja(pmod_ja_to_app_t inputs)
{
  app_to_pmod_ja_t outputs;
  WIRE_READ(app_to_pmod_ja_t, outputs, app_to_pmod_ja)
  WIRE_WRITE(pmod_ja_to_app_t, pmod_ja_to_app, inputs)
  return outputs;
}

// https://reference.digilentinc.com/pmod/pmodi2s2/reference-manual
typedef struct i2s_to_app_t
{
  uint1_t rx_data;
}i2s_to_app_t;
typedef struct app_to_i2s_t
{
  uint1_t tx_lrck;
  uint1_t tx_sclk;
  uint1_t tx_data;
  uint1_t rx_lrck;
  uint1_t rx_sclk;
}app_to_i2s_t;

// Logic to expose PMOD as I2S
// https://reference.digilentinc.com/pmod/pmodi2s2/reference-manual
// I2S PMOD specific .xdc
//  https://github.com/Digilent/Pmod-I2S2/blob/master/arty-a7-35/src/constraints/Arty-A7-35-Master.xdc
// (Note: not the 'Sch' names but the 'ja' top level port names)
/*
tx_mclk  ja[0]
tx_lrck  ja[1]
tx_sclk  ja[2]
tx_data  ja[3]
rx_mclk  ja[4]
rx_lrck  ja[5]
rx_sclk  ja[6]
rx_data  ja[7]
*/

i2s_to_app_t pmod_to_i2s(pmod_ja_to_app_t pmod)
{
  i2s_to_app_t i2s;
  i2s.rx_data = pmod.ja7;
  return i2s;
}

app_to_pmod_ja_t i2s_to_pmod(app_to_i2s_t i2s)
{
  app_to_pmod_ja_t pmod;
  pmod.ja1 = i2s.tx_lrck;
  pmod.ja2 = i2s.tx_sclk;
  pmod.ja3 = i2s.tx_data;
  pmod.ja5 = i2s.rx_lrck;
  pmod.ja6 = i2s.rx_sclk;
  return pmod;
}

// Helpers to read+write i2s via pmod adapter
i2s_to_app_t read_i2s_pmod()
{
  // Read the incoming pmod signals
  pmod_ja_to_app_t from_pmod;
  WIRE_READ(pmod_ja_to_app_t, from_pmod, pmod_ja_to_app)
  // Convert to i2s
  return pmod_to_i2s(from_pmod);
}
void write_i2s_pmod(app_to_i2s_t to_i2s)
{
  // Convert i2s signals to pmod
  app_to_pmod_ja_t to_pmod = i2s_to_pmod(to_i2s);
  // Write outgoing signals to pmod
  WIRE_WRITE(app_to_pmod_ja_t, app_to_pmod_ja, to_pmod)
}
