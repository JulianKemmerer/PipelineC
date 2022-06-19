#include "uintN_t.h"
#include "intN_t.h"
#include "leds/leds_port.c" // Top level LEDs ports

// Globally visible port/wire names for output register
uint4_t leds_out_reg_data;
uint1_t leds_out_reg_enable;
#include "clock_crossing/leds_out_reg_data.h"
#include "clock_crossing/leds_out_reg_enable.h"

#pragma MAIN leds_out_reg_module
void leds_out_reg_module()
{
  static uint4_t the_reg;
  // Reg drives output port wire directly
  WIRE_WRITE(uint4_t, leds, the_reg)
  // Input data and enable drive reg write logic
  uint4_t reg_data;
  uint1_t reg_enable;
  WIRE_READ(uint4_t, reg_data, leds_out_reg_data)
  WIRE_READ(uint1_t, reg_enable, leds_out_reg_enable)
  if(reg_enable)
  {
    the_reg = reg_data;
  }
}

void set_leds_out_reg_en(uint1_t en)
{
  WIRE_WRITE(uint1_t, leds_out_reg_enable, en)
}
// Single instance FSM because can only be one WIRE_WRITE instance
#include "set_leds_out_reg_en_SINGLE_INST.h"

void set_leds_out_reg(uint4_t data)
{
  // Drive the output register for a clock cycle
  // Set both data and enable
  WIRE_WRITE(uint4_t, leds_out_reg_data, data)
  set_leds_out_reg_en(1);
  // And then clear enable
  set_leds_out_reg_en(0);
}
// Single instance FSM because can only be one WIRE_WRITE instance
#include "set_leds_out_reg_SINGLE_INST.h"

// Comb logic - not an FSM (for those who done like WIRE_READ macros)
uint4_t read_leds_out_reg()
{
  // Read wire straight from the output register
  uint4_t rv;
  WIRE_READ(uint4_t, rv, leds)
  return rv;
}

uint4_t get_leds_out_reg()
{
  return read_leds_out_reg();
}
// FSM because using "get" to mean fsm style
#include "get_leds_out_reg_FSM.h"
