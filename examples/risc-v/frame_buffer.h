#pragma once
#include "mem_map.h"
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480

#ifndef FRAME_BUFFER_DISABLE_CPU_PORT

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

#define GOL_BASE_ADDR (LINE_BUF_DATA_ADDR + sizeof(uint32_t))

// Memory mapped version not used by pipelinec hardware fsm style frame buffers
#ifndef __PIPELINEC__
// TODO reduce code size with inlined read+write single func call?
void frame_buf_write(int32_t x, int32_t y, int32_t wr_data){
  *FRAME_BUF_X = x;
  *FRAME_BUF_Y = y;
  *FRAME_BUF_DATA = wr_data;
}
int32_t frame_buf_read(int32_t x, int32_t y){
  *FRAME_BUF_X = x;
  *FRAME_BUF_Y = y;
  return *FRAME_BUF_DATA;
}
int32_t line_buf_write(int32_t line_sel, int32_t x, int32_t wr_data){
  *LINE_BUF_SEL = line_sel;
  *LINE_BUF_X = x;
  *LINE_BUF_DATA = wr_data;
}
int32_t line_buf_read(int32_t line_sel, int32_t x){
  *LINE_BUF_SEL = line_sel;
  *LINE_BUF_X = x;
  return *LINE_BUF_DATA;
}
#endif

#else
#define GOL_BASE_ADDR (LEDS_ADDR + sizeof(uint32_t))
#endif
