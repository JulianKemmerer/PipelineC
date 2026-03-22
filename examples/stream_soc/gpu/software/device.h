#pragma once

void drawRect(uint32_t start_x, uint32_t start_y, uint32_t end_x, uint32_t end_y, uint8_t color, volatile pixel_t* UNUSED_FB_TODO_REMOVE){
  if(end_x>FRAME_WIDTH) end_x = FRAME_WIDTH;
  if(end_y>FRAME_HEIGHT) end_y = FRAME_HEIGHT;
  if(start_x==end_x) return; // Zero width
  if(start_y==end_y) return; // Zero height
  if(start_x>=FRAME_WIDTH) return; // Invalid
  if(start_y>=FRAME_HEIGHT) return; // Invalid
  pixel_t p = {color, color, color, color};
  draw_rect_t cmd;
  cmd.color = p;
  cmd.start_x = start_x;
  cmd.start_y = start_y;
  cmd.end_x = end_x;
  cmd.end_y = end_y;
  mm_handshake_write(gpu_cmd, &cmd);
}
