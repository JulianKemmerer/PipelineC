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