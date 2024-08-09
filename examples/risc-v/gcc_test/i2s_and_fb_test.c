#include <stdint.h>
#include <stdlib.h>
#include "mem_map.h"

int get_max_abs(i2s_sample_in_mem_t* samples, int n_samples){
  int max = 0;
  for(size_t i = 0; i < n_samples; i++)
  {
    if(abs(samples[i].l) > max){
      max = abs(samples[i].l);
    }
    if(abs(samples[i].r) > max){
      max = abs(samples[i].r);
    }
  }
  return max;
}

void main() {
  //int count = 0;
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
    *LED = mm_status_regs->i2s_rx_out_desc_overflow;
    
    // Read i2s samples
    i2s_sample_in_mem_t* samples;
    int n_samples;
    i2s_read(&samples, &n_samples);

    // Compute the max abs value ~volume/amplitude measure    
    int max_abs = get_max_abs(samples, n_samples);

    // Color small area of screen (to be fast)
    int x_size = 4;
    int x_start = (FRAME_WIDTH/2)-(x_size/2);
    int x_end = x_start + x_size;
    int y_size = 4;
    int y_start = (FRAME_HEIGHT/2)-(y_size/2);
    int y_end = y_start + y_size;
    // with brightness representing the i2s i24 volume value scaled to rgb 255
    int color_val = (255 * max_abs) / (1<<23); // TODO overflow? fix scaling...
    pixel_t p = {.r=color_val,.g=color_val,.b=color_val};
    for (size_t i = x_start; i < x_end; i++)
    {
      for (size_t j = y_start; j < y_end; j++)
      {
        frame_buf_write(i, j, p);
      }
    }
   
    //count += 1;
  }
}