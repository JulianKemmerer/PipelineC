#include <stdint.h>
#include "mem_map.h"

void main() {
  int count = 0;
  while(1){
    *LED = count;
    #ifdef MMIO_AXI0
    // Flashing white and black screen
    // Black
    pixel_t p = {0};
    for (size_t i = 0; i < FRAME_WIDTH; i++)
    {
      for (size_t j = 0; j < FRAME_HEIGHT; j++)
      {
        frame_buf_write(i, j, p);
      }
    }
    // White
    p.a = 255;
    p.r = 255;
    p.g = 255;
    p.b = 255;
    for (size_t i = 0; i < FRAME_WIDTH; i++)
    {
      for (size_t j = 0; j < FRAME_HEIGHT; j++)
      {
        frame_buf_write(i, j, p);
      }
    }
    #endif
    count += 1;
  }
}
/*
// Sim debug version that doesnt run forever
int main() {
  int count = 0;
  while(count < 10){
    // 1b led get slow changing upper bits
    *LED = count >> 12;
    count += 1;
  }
  *RETURN_OUTPUT = count;
  return count;
}
*/