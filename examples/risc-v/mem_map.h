#ifdef __PIPELINEC__
#include "uintN_t.h"
#else
#include <stdint.h>
#endif

// The output/stop/halt peripheral
#define RETURN_OUTPUT_ADDR 0x10000000
static volatile uint32_t* RETURN_OUTPUT = (uint32_t*)RETURN_OUTPUT_ADDR;

// LEDs
#define LEDS_ADDR 0x10000004
static volatile uint32_t* LEDS = (uint32_t*)LEDS_ADDR;

// Frame buffer, write x,y then read/write data
#define FRAME_BUF_X_ADDR 0x10000008
static volatile uint32_t* FRAME_BUF_X = (uint32_t*)FRAME_BUF_X_ADDR;
#define FRAME_BUF_Y_ADDR 0x1000000C
static volatile uint32_t* FRAME_BUF_Y = (uint32_t*)FRAME_BUF_Y_ADDR;
#define FRAME_BUF_DATA_ADDR 0x10000010
static volatile uint32_t* FRAME_BUF_DATA = (uint32_t*)FRAME_BUF_DATA_ADDR;

// Two-line buffer, write sel,x then read/write data
#define LINE_BUF_SEL_ADDR 0x10000014
static volatile uint32_t* LINE_BUF_SEL = (uint32_t*)LINE_BUF_SEL_ADDR;
#define LINE_BUF_X_ADDR 0x10000018
static volatile uint32_t* LINE_BUF_X = (uint32_t*)LINE_BUF_X_ADDR;
#define LINE_BUF_DATA_ADDR 0x1000001C
static volatile uint32_t* LINE_BUF_DATA = (uint32_t*)LINE_BUF_DATA_ADDR;