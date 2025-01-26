#pragma once
#include "compiler.h"

// Separate wires and MAINs so can be different clock domains

// TODO define active low high resolved LED_ON LED_OFF consts

#ifdef LED_R_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, LED_R_WIRE, led_r)
#else
#ifdef LED_R_OUT
DECL_OUTPUT_REG(uint1_t, led_r)
#endif
#endif

#ifdef LED_G_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, LED_G_WIRE, led_g)
#else
#ifdef LED_G_OUT
DECL_OUTPUT_REG(uint1_t, led_g)
#endif
#endif

#ifdef LED_B_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, LED_B_WIRE, led_b)
#else
#ifdef LED_B_OUT
DECL_OUTPUT_REG(uint1_t, led_b)
#endif
#endif