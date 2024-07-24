// TODO rename i2s.h
#pragma once
#include "wire.h"
#include "uintN_t.h"

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

/*
// TX and RX use same master clock, clock for i2s_module
#pragma MAIN_MHZ i2s_module 22.579
// Globally visible ports/wires
i2s_to_app_t i2s_to_app;
app_to_i2s_t app_to_i2s;
// These should be in a macro somehow TODO \/
//#include "uint1_t_array_N_t.h"
#include "i2s_to_app_t_array_N_t.h"
#include "i2s_to_app_clock_crossing.h"
//#include "uint1_t_array_N_t.h"
#include "app_to_i2s_t_array_N_t.h"
#include "app_to_i2s_clock_crossing.h"
// Top level module connecting to globally visible ports
app_to_i2s_t i2s_module(i2s_to_app_t inputs)
{
  app_to_i2s_t outputs;
  WIRE_READ(app_to_i2s_t, outputs, app_to_i2s)
  WIRE_WRITE(i2s_to_app_t, i2s_to_app, inputs)
  return outputs;
}
*/
