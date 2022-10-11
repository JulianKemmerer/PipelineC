#include "mem_map.h"
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
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
