#pragma once
#include "stream/stream.h"

/*drawRect(int start_x, int start_y, int end_x, int end_y, uint8_t color, volatile pixel_t* FB) command*/
typedef struct draw_rect_t{
  pixel_t color;
  uint16_t start_x;
  uint16_t start_y;
  uint16_t end_x;
  uint16_t end_y;
}draw_rect_t;
DECL_STREAM_TYPE(draw_rect_t)