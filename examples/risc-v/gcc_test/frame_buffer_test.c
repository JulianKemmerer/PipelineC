#include <stdint.h>
#include "mem_map.h"
#include "frame_buffer_test.h"

void main() {
  // Do test of modifying pixels
  *LED = 1;
  // x,y bounds based on which thread you are

  // Write all pixels with test pattern
  pixel_t p;
  for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
      for(int x=0; x < FRAME_WIDTH; x++){
          p.r = x;
          p.g = y;
          p.b = 64;
          frame_buf_write(x, y, 1, &p);
      }
  }
  *LED = ~*LED;
  threads_frame_sync();

  // Many reads, kernels, and writes happening at once
  pixel_t pixel_buf[RISCV_RAM_NUM_BURST_WORDS];
  while(1){
    for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
        // Bottle neck is read
        // Start reads of many pixels at once
        // Start read of entire line in advance
        uint32_t x = 0;
        frame_buf_read_start(x, y, FRAME_WIDTH);
        // Then do loop processing burst size at a time
        int32_t remaining_pixels = FRAME_WIDTH;
        while(remaining_pixels > 0){
          uint32_t num_pixels = 
            remaining_pixels >= RISCV_RAM_NUM_BURST_WORDS ? 
              RISCV_RAM_NUM_BURST_WORDS : remaining_pixels;
          frame_buf_read_finish(pixel_buf, num_pixels);
          for(int i=0; i < num_pixels; i++){
            kernel(x+i, y, &(pixel_buf[i]), &(pixel_buf[i]));
          }
          frame_buf_write(x, y, num_pixels, pixel_buf);
          remaining_pixels -= num_pixels;
          x += num_pixels;
        }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
  }
}