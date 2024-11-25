#pragma once
#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"

// Configure IO direction for hard wired single use pins

// RGB LED
#define ICE_39_OUT
#define ICE_40_OUT
#define ICE_41_OUT
#ifdef ICE_39_OUT
DECL_OUTPUT(uint1_t, ice_39)
#endif
#ifdef ICE_40_OUT
DECL_OUTPUT(uint1_t, ice_40)
#endif
#ifdef ICE_41_OUT
DECL_OUTPUT(uint1_t, ice_41)
#endif
#define LED_G_WIRE ice_39
#define LED_B_WIRE ice_40
#define LED_R_WIRE ice_41
#include "rgb_led/led_rgb_wires.c"

// GPIO multiple use pins

#ifdef ICE_2_OUT
DECL_OUTPUT(uint1_t, ice_2)
#endif
#ifdef ICE_3_OUT
DECL_OUTPUT(uint1_t, ice_3)
#endif
#ifdef ICE_4_OUT
DECL_OUTPUT(uint1_t, ice_4)
#endif
#ifdef ICE_25_OUT
DECL_OUTPUT(uint1_t, ice_25)
#endif
#ifdef ICE_27_IN
DECL_INPUT(uint1_t, ice_27)
#endif
#ifdef ICE_28_OUT
DECL_OUTPUT(uint1_t, ice_28)
#endif
#ifdef ICE_31_OUT
DECL_OUTPUT(uint1_t, ice_31)
#endif
#ifdef ICE_32_OUT
DECL_OUTPUT(uint1_t, ice_32)
#endif
#ifdef ICE_34_OUT
DECL_OUTPUT(uint1_t, ice_34)
#endif
#ifdef ICE_36_OUT
DECL_OUTPUT(uint1_t, ice_36)
#endif
#ifdef ICE_38_OUT
DECL_OUTPUT(uint1_t, ice_38)
#endif
#ifdef ICE_42_OUT
DECL_OUTPUT(uint1_t, ice_42)
#endif
#ifdef ICE_43_OUT
DECL_OUTPUT(uint1_t, ice_43)
#endif
#ifdef ICE_44_OUT
DECL_OUTPUT(uint1_t, ice_44)
#endif
#ifdef ICE_45_OUT
DECL_OUTPUT(uint1_t, ice_45)
#endif
#ifdef ICE_46_OUT
DECL_OUTPUT(uint1_t, ice_46)
#endif
#ifdef ICE_47_OUT
DECL_OUTPUT(uint1_t, ice_47)
#endif
#ifdef ICE_48_OUT
DECL_OUTPUT(uint1_t, ice_48)
#endif


