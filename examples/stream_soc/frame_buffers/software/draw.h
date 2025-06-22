#include "vga/pixel.h"
#include "frame_buf.h"

// Some helper drawing code 
// Rect from Dutra :) (has text console stuff too!?)
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