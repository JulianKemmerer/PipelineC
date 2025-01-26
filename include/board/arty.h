#pragma once
// See examples/arty/Arty-A7-35|100-Master.xdc files
#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"

// Configure IO direction for hard wired single use pins

// RGB LEDs
//#define LED0_B_OUT
//#define LED0_G_OUT
//#define LED0_R_OUT
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

// Expose named PMOD ports

// PMOD JB
//  A=top/inner row, pin1-6
#define PMOD_NAME pmod_jb_a
#ifdef JB_0_OUT
DECL_OUTPUT(uint1_t, jb_0)
#define PMOD_O1_WIRE jb_0
#endif
#ifdef JB_1_OUT
DECL_OUTPUT(uint1_t, jb_1)
#define PMOD_O2_WIRE jb_1
#endif
#ifdef JB_2_OUT
DECL_OUTPUT(uint1_t, jb_2)
#define PMOD_O3_WIRE jb_2
#endif
#ifdef JB_3_OUT
DECL_OUTPUT(uint1_t, jb_3)
#define PMOD_O4_WIRE jb_3
#endif
#include "pmod/pmod_wires.h"
//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_jb_b
#ifdef JB_4_OUT
DECL_OUTPUT(uint1_t, jb_4)
#define PMOD_O1_WIRE jb_4
#endif
#ifdef JB_5_OUT
DECL_OUTPUT(uint1_t, jb_5)
#define PMOD_O2_WIRE jb_5
#endif
#ifdef JB_6_OUT
DECL_OUTPUT(uint1_t, jb_6)
#define PMOD_O3_WIRE jb_6
#endif
#ifdef JB_7_OUT
DECL_OUTPUT(uint1_t, jb_7)
#define PMOD_O4_WIRE jb_7
#endif
#include "pmod/pmod_wires.h"

// PMOD JC
//  A=top/inner row, pin1-6
#define PMOD_NAME pmod_jc_a
#ifdef JC_0_OUT
DECL_OUTPUT(uint1_t, jc_0)
#define PMOD_O1_WIRE jc_0
#endif
#ifdef JC_1_OUT
DECL_OUTPUT(uint1_t, jc_1)
#define PMOD_O2_WIRE jc_1
#endif
#ifdef JC_2_OUT
DECL_OUTPUT(uint1_t, jc_2)
#define PMOD_O3_WIRE jc_2
#endif
#ifdef JC_3_OUT
DECL_OUTPUT(uint1_t, jc_3)
#define PMOD_O4_WIRE jc_3
#endif
#include "pmod/pmod_wires.h"
//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_jc_b
#ifdef JC_4_OUT
DECL_OUTPUT(uint1_t, jc_4)
#define PMOD_O1_WIRE jc_4
#endif
#ifdef JC_5_OUT
DECL_OUTPUT(uint1_t, jc_5)
#define PMOD_O2_WIRE jc_5
#endif
#ifdef JC_6_OUT
DECL_OUTPUT(uint1_t, jc_6)
#define PMOD_O3_WIRE jc_6
#endif
#ifdef JC_7_OUT
DECL_OUTPUT(uint1_t, jc_7)
#define PMOD_O4_WIRE jc_7
#endif
#include "pmod/pmod_wires.h"

// PMOD JD
//  A=top/inner row, pin1-6
#define PMOD_NAME pmod_jd_a
#ifdef JD_0_OUT
DECL_OUTPUT(uint1_t, jd_0)
#define PMOD_O1_WIRE jd_0
#endif
#ifdef JD_0_IN
DECL_INPUT(uint1_t, jd_0)
#define PMOD_I1_WIRE jd_0
#endif
#ifdef JD_1_OUT
DECL_OUTPUT(uint1_t, jd_1)
#define PMOD_O2_WIRE jd_1
#endif
#ifdef JD_1_IN
DECL_INPUT(uint1_t, jd_1)
#define PMOD_I2_WIRE jd_1
#endif
#ifdef JD_2_OUT
DECL_OUTPUT(uint1_t, jd_2)
#define PMOD_O3_WIRE jd_2
#endif
#ifdef JD_2_IN
DECL_INPUT(uint1_t, jd_2)
#define PMOD_I3_WIRE jd_2
#endif
#ifdef JD_3_OUT
DECL_OUTPUT(uint1_t, jd_3)
#define PMOD_O4_WIRE jd_3
#endif
#ifdef JD_3_IN
DECL_INPUT(uint1_t, jd_3)
#define PMOD_I4_WIRE jd_3
#endif
#include "pmod/pmod_wires.h"
//  B=bottom/outter row, pin7-12
#define PMOD_NAME pmod_jd_b
#ifdef JD_4_OUT
DECL_OUTPUT(uint1_t, jd_4)
#define PMOD_O1_WIRE jd_4
#endif
#ifdef JD_4_IN
DECL_INPUT(uint1_t, jd_4)
#define PMOD_I1_WIRE jd_4
#endif
#ifdef JD_5_OUT
DECL_OUTPUT(uint1_t, jd_5)
#define PMOD_O2_WIRE jd_5
#endif
#ifdef JD_5_IN
DECL_INPUT(uint1_t, jd_5)
#define PMOD_I2_WIRE jd_5
#endif
#ifdef JD_6_OUT
DECL_OUTPUT(uint1_t, jd_6)
#define PMOD_O3_WIRE jd_6
#endif
#ifdef JD_6_IN
DECL_INPUT(uint1_t, jd_6)
#define PMOD_I3_WIRE jd_6
#endif
#ifdef JD_7_OUT
DECL_OUTPUT(uint1_t, jd_7)
#define PMOD_O4_WIRE jd_7
#endif
#ifdef JD_7_IN
DECL_INPUT(uint1_t, jd_7)
#define PMOD_I4_WIRE jd_7
#endif
#include "pmod/pmod_wires.h"
