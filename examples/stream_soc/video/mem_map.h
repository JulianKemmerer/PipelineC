#pragma once

typedef struct crop2d_params_t{
  uint32_t top_left_x;
  uint32_t top_left_y;
  uint32_t bot_right_x;
  uint32_t bot_right_y;
}crop2d_params_t;

typedef struct scale2d_params_t{
  uint32_t scale;
}scale2d_params_t;

typedef struct fb_pos_params_t{
  uint32_t xpos;
  uint32_t ypos;
}fb_pos_params_t;

