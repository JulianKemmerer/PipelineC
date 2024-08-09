#include <stdint.h>
#include "mem_map.h"

int get_max_abs(i2s_sample_in_mem_t* samples, int n_samples){
  //TODO max left and right?
  //and then max across all samples
}


void main() {
  int count = 0;
  // Set entire screen black
  pixel_t p = {0};
  for (size_t i = 0; i < FRAME_WIDTH; i++)
  {
    for (size_t j = 0; j < FRAME_HEIGHT; j++)
    {
      frame_buf_write(i, j, p);
    }
  }
  while(1){
    *LED = count;
    
    // Read i2s samples
    i2s_sample_in_mem_t* samples;
    int n_samples;
    i2s_read(&samples, &n_samples);

    // Compute the max abs value ~volume/amplitude measure    
    int max_abs = get_max_abs(samples, n_samples);

    // Color small area of screen (to be fast)
    // TODO not full frame etc
    // TODO determine square position and size
    // one pixel to start?
    // with color representing the volume value scaled to rgb 255
    // p = ... TODO math with max_abs;
    for (size_t i = 0; i < FRAME_WIDTH; i++)
    {
      for (size_t j = 0; j < FRAME_HEIGHT; j++)
      {
        frame_buf_write(i, j, p);
      }
    }
   
    count += 1;
  }
}