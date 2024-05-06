#include <stdint.h>
#include "mem_map.h"

typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color

uint32_t main() {
  int R = 0;
  int G = 255;
  int B = 0;
  pixel_t pixel = {.r=R, .g=G, .b=B};
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel.a<<(0*8));
  write_data |= ((uint32_t)pixel.b<<(1*8));
  write_data |= ((uint32_t)pixel.g<<(2*8));
  write_data |= ((uint32_t)pixel.r<<(3*8));
  *RETURN_OUTPUT = write_data;
  return write_data;
}
