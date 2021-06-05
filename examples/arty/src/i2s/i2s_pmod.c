#pragma once
#include "wire.h"
#include "uintN_t.h"

#include "../pmod/pmod.c"
#include "i2s.c"

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

i2s_to_app_t pmod_to_i2s(pmod_to_app_t pmod)
{
  i2s_to_app_t i2s;
  i2s.rx_data = pmod.ja7;
  return i2s;
}

app_to_pmod_t i2s_to_pmod(app_to_i2s_t i2s)
{
  app_to_pmod_t pmod;
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
  pmod_to_app_t from_pmod;
  WIRE_READ(pmod_to_app_t, from_pmod, pmod_to_app)
  // Convert to i2s
  return pmod_to_i2s(from_pmod);
}
void write_i2s_pmod(app_to_i2s_t to_i2s)
{
  // Convert i2s signals to pmod
  app_to_pmod_t to_pmod = i2s_to_pmod(to_i2s);
  // Write outgoing signals to pmod
  WIRE_WRITE(app_to_pmod_t, app_to_pmod, to_pmod)
}
