#pragma once

// Hardware memory address mappings for PipelineC and software C code

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#endif

#define MEM_MAP_BASE_ADDR 0x10000000

// The output/stop/halt peripheral
#define RETURN_OUTPUT_ADDR (MEM_MAP_BASE_ADDR+0)
static volatile uint32_t* RETURN_OUTPUT = (uint32_t*)RETURN_OUTPUT_ADDR;

// LEDs
#define LEDS_ADDR (RETURN_OUTPUT_ADDR + sizeof(uint32_t))
static volatile uint32_t* LEDS = (uint32_t*)LEDS_ADDR;

// Re: memory mapped structs
//__attribute__((packed)) increases code size bringing in memcpy
// Not actually needed to pack for ~memory savings
// when memory mapped padding regs will optimize away if unused
// So manually add padding fields for 32b|4B alignment (otherwise need packed)
// (if not PipelineC built in to-from bytes functions won't work)

// // For now use separate input and output structs for accelerators
// // that have special input and output valid flags
// #include "gcc_test/gol/hw_config.h"