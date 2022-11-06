#pragma once

// Hardware memory mappings

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

// Frame buffer, write x,y then read/write data
#define FRAME_BUF_X_ADDR (LEDS_ADDR + sizeof(uint32_t))
static volatile uint32_t* FRAME_BUF_X = (uint32_t*)FRAME_BUF_X_ADDR;
#define FRAME_BUF_Y_ADDR (FRAME_BUF_X_ADDR + sizeof(uint32_t))
static volatile uint32_t* FRAME_BUF_Y = (uint32_t*)FRAME_BUF_Y_ADDR;
#define FRAME_BUF_DATA_ADDR (FRAME_BUF_Y_ADDR + sizeof(uint32_t))
static volatile uint32_t* FRAME_BUF_DATA = (uint32_t*)FRAME_BUF_DATA_ADDR;

// Two-line buffer, write sel,x then read/write data
#define LINE_BUF_SEL_ADDR (FRAME_BUF_DATA_ADDR + sizeof(uint32_t))
static volatile uint32_t* LINE_BUF_SEL = (uint32_t*)LINE_BUF_SEL_ADDR;
#define LINE_BUF_X_ADDR (LINE_BUF_SEL_ADDR + sizeof(uint32_t))
static volatile uint32_t* LINE_BUF_X = (uint32_t*)LINE_BUF_X_ADDR;
#define LINE_BUF_DATA_ADDR (LINE_BUF_X_ADDR + sizeof(uint32_t))
static volatile uint32_t* LINE_BUF_DATA = (uint32_t*)LINE_BUF_DATA_ADDR;

// Re: memory mapped structs
//__attribute__((packed)) increases code size bringing in memcpy
// Not actually needed to pack for ~memory savings
// when memory mapped padding regs will optimize away if unused
// So manually add padding fields for 32b|4B alignment (otherwise need packed)
// (if not PipelineC built in to-from bytes functions won't work)

// For now use separate input and output structs for accelerators
// that have special input and output valid flags

#ifdef COUNT_NEIGHBORS_IS_HW
#define COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR (LINE_BUF_DATA_ADDR + sizeof(uint32_t))
#include "gcc_test/gol/count_neighbors_hw/mem_map.h"
// Continue from addr=COUNT_NEIGHBORS_MEM_MAP_NEXT_ADDR
#endif