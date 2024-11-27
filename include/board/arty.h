#pragma once
// See examples/arty/Arty-A7-35|100-Master.xdc files
#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"

// Configure IO direction for hard wired single use pins

// RGB LED
#define LED0_B_OUT
#define LED0_G_OUT
#define LED0_R_OUT
#ifdef LED0_B_OUT
DECL_OUTPUT(uint1_t, led0_b)
#define LED_B_WIRE led0_b
#endif
#ifdef LED0_G_OUT
DECL_OUTPUT(uint1_t, led0_g)
#define LED_G_WIRE led0_g
#endif
#ifdef LED0_R_OUT
DECL_OUTPUT(uint1_t, led0_r)
#define LED_R_WIRE led0_r
#endif
#include "rgb_led/led_rgb_wires.c"

// GPIO multiple use pins

// ChipKit
#ifdef CK_29_IN
DECL_INPUT(uint1_t, ck_29)
#endif
#ifdef CK_30_OUT
DECL_OUTPUT(uint1_t, ck_30)
#endif
