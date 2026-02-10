#pragma once
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#define TILE_FACTOR 1
#define TILE_FACTOR_LOG2 0
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define FB_SIZE ((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)
// Pixel x,y pos to pixel index in array
uint32_t pos_to_pixel_index(uint16_t x, uint16_t y)
{
  uint32_t x_tile_index = x >> TILE_FACTOR_LOG2;
  uint32_t y_tile_index = y >> TILE_FACTOR_LOG2;
  return (y_tile_index*NUM_X_TILES) + x_tile_index;
}
pixel_t frame_buf_read(uint16_t x, uint16_t y, volatile pixel_t* FB)
{
  return FB[pos_to_pixel_index(x,y)];
}
void frame_buf_write(uint16_t x, uint16_t y, pixel_t pixel, volatile pixel_t* FB)
{
  FB[pos_to_pixel_index(x,y)] = pixel;
}

// Some helper drawing code 
// Rect from Dutra :) (has text console stuff too!?)
// Moved into hardware now :)
/*
void drawRect(int start_x, int start_y, int end_x, int end_y, uint8_t color, volatile pixel_t* FB){
    pixel_t p = {color, color, color, color};
    for (int32_t i = start_x; i < end_x; i++)
    {
        for (int32_t j = start_y; j < end_y; j++)
        {
            frame_buf_write(i,j,p,FB);
        }
    }
}
*/