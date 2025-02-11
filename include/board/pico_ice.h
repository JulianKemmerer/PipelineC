// See pico-ice-sdk/rtl/pico_ice.pcf
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
#ifdef ICE_25_OUT
DECL_OUTPUT(uint1_t, ice_25)
#endif
#ifdef ICE_27_IN
DECL_INPUT(uint1_t, ice_27)
#endif

// Expose named PMOD ports

// PMOD0

//  A=top/inner row, pin1-6
#define PMOD_NAME pmod_0a

#ifdef PMOD_0A_O4
#define ICE_45_OUT
#define PMOD_O4_WIRE ice_45
#endif
#ifdef ICE_45_OUT
DECL_OUTPUT(uint1_t, ice_45)
#endif
#ifdef PMOD_0A_I4
#define ICE_45_IN
#define PMOD_I4_WIRE ice_45
#endif
#ifdef ICE_45_IN
DECL_INPUT(uint1_t, ice_45)
#endif

#ifdef PMOD_0A_O3
#define ICE_47_OUT
#define PMOD_O3_WIRE ice_47
#endif
#ifdef ICE_47_OUT
DECL_OUTPUT(uint1_t, ice_47)
#endif
#ifdef PMOD_0A_I3
#define ICE_47_IN
#define PMOD_I3_WIRE ice_47
#endif
#ifdef ICE_47_IN
DECL_INPUT(uint1_t, ice_47)
#endif

#ifdef PMOD_0A_O2
#define ICE_2_OUT
#define PMOD_O2_WIRE ice_2
#endif
#ifdef ICE_2_OUT
DECL_OUTPUT(uint1_t, ice_2)
#endif
#ifdef PMOD_0A_I2
#define ICE_2_IN
#define PMOD_I2_WIRE ice_2
#endif
#ifdef ICE_2_IN
DECL_INPUT(uint1_t, ice_2)
#endif

#ifdef PMOD_0A_O1
#define ICE_4_OUT
#define PMOD_O1_WIRE ice_4
#endif
#ifdef ICE_4_OUT
DECL_OUTPUT(uint1_t, ice_4)
#endif
#ifdef PMOD_0A_I1
#define ICE_4_IN
#define PMOD_I1_WIRE ice_4
#endif
#ifdef ICE_4_IN
DECL_INPUT(uint1_t, ice_4)
#endif

#include "pmod/pmod_wires.h"

//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_0b

#ifdef PMOD_0B_O4
#define ICE_44_OUT
#define PMOD_O4_WIRE ice_44
#endif
#ifdef ICE_44_OUT
DECL_OUTPUT(uint1_t, ice_44)
#endif
#ifdef PMOD_0B_I4
#define ICE_44_IN
#define PMOD_I4_WIRE ice_44
#endif
#ifdef ICE_44_IN
DECL_INPUT(uint1_t, ice_44)
#endif

#ifdef PMOD_0B_O3
#define ICE_46_OUT
#define PMOD_O3_WIRE ice_46
#endif
#ifdef ICE_46_OUT
DECL_OUTPUT(uint1_t, ice_46)
#endif
#ifdef PMOD_0B_I3
#define ICE_46_IN
#define PMOD_I3_WIRE ice_46
#endif
#ifdef ICE_46_IN
DECL_INPUT(uint1_t, ice_46)
#endif

#ifdef PMOD_0B_O2
#define ICE_48_OUT
#define PMOD_O2_WIRE ice_48
#endif
#ifdef ICE_48_OUT
DECL_OUTPUT(uint1_t, ice_48)
#endif
#ifdef PMOD_0B_I2
#define ICE_48_IN
#define PMOD_I2_WIRE ice_48
#endif
#ifdef ICE_48_IN
DECL_INPUT(uint1_t, ice_48)
#endif

#ifdef PMOD_0B_O1
#define ICE_3_OUT
#define PMOD_O1_WIRE ice_3
#endif
#ifdef ICE_3_OUT
DECL_OUTPUT(uint1_t, ice_3)
#endif
#ifdef PMOD_0B_I1
#define ICE_3_IN
#define PMOD_I1_WIRE ice_3
#endif
#ifdef ICE_3_IN
DECL_INPUT(uint1_t, ice_3)
#endif

#include "pmod/pmod_wires.h"

// PMOD1
//  A=top/inner row, pin1-6
#define PMOD_NAME pmod_1a

#ifdef PMOD_1A_O4
#define ICE_31_OUT
#define PMOD_O4_WIRE ice_31
#endif
#ifdef ICE_31_OUT
DECL_OUTPUT(uint1_t, ice_31)
#endif

#ifdef PMOD_1A_O3
#define ICE_34_OUT
#define PMOD_O3_WIRE ice_34
#endif
#ifdef ICE_34_OUT
DECL_OUTPUT(uint1_t, ice_34)
#endif

#ifdef PMOD_1A_O2
#define ICE_38_OUT
#define PMOD_O2_WIRE ice_38
#endif
#ifdef ICE_38_OUT
DECL_OUTPUT(uint1_t, ice_38)
#endif

#ifdef PMOD_1A_O1
#define ICE_43_OUT
#define PMOD_O1_WIRE ice_43
#endif
#ifdef ICE_43_OUT
DECL_OUTPUT(uint1_t, ice_43)
#endif

#include "pmod/pmod_wires.h"

//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_1b

#ifdef PMOD_1B_O4
#define ICE_28_OUT
#define PMOD_O4_WIRE ice_28
#endif
#ifdef ICE_28_OUT
DECL_OUTPUT(uint1_t, ice_28)
#endif

#ifdef PMOD_1B_O3
#define ICE_32_OUT
#define PMOD_O3_WIRE ice_32
#endif
#ifdef ICE_32_OUT
DECL_OUTPUT(uint1_t, ice_32)
#endif

#ifdef PMOD_1B_O2
#define ICE_36_OUT
#define PMOD_O2_WIRE ice_36
#endif
#ifdef ICE_36_OUT
DECL_OUTPUT(uint1_t, ice_36)
#endif

#ifdef PMOD_1B_O1
#define ICE_42_OUT
#define PMOD_O1_WIRE ice_42
#endif
#ifdef ICE_42_OUT
DECL_OUTPUT(uint1_t, ice_42)
#endif

#include "pmod/pmod_wires.h"
