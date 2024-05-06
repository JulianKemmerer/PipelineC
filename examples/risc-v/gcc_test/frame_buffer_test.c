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

  while(1){
    for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
        // Bottle neck is read (specifically starting reads)
        // So start read of many pixels at once...
        // start read of entire line in advance
        uint32_t x = 0;
        frame_buf_read_start(x, y, FRAME_WIDTH);
        // Then process one pixel at a time
        while(x < FRAME_WIDTH){
          frame_buf_read_finish(&p, 1);
          kernel(x, y, &p, &p);
          frame_buf_write(x, y, 1, &p);
          x += 1;
        }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
  }
}