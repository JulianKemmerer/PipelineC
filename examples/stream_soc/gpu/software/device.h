#pragma once

void drawRect(int start_x, int start_y, int end_x, int end_y, uint8_t color, volatile pixel_t* UNUSED_FB_TODO_REMOVE){
  if(start_x==end_x) return; // Zero width
  if(start_y==end_y) return; // Zero height
  pixel_t p = {color, color, color, color};
  draw_rect_t cmd;
  cmd.color = p;
  cmd.start_x = start_x;
  cmd.start_y = start_y;
  cmd.end_x = end_x;
  cmd.end_y = end_y;
  mm_handshake_write(gpu_cmd, &cmd);
}
