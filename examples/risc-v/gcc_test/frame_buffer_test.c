#include <stdint.h>
#include "mem_map.h"
#include "frame_buffer_test.h"

void main() {
  // Do test of modifying pixels
  *LED = 1;
  // x,y bounds based on which thread you are

  pixel_t p = {0};
  // Write all pixels with test pattern
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

  uint32_t frame_count;
  while(1){
    for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
        // Bottle neck is read (specifically starting reads)
        // So start read of many pixels at once...
        // start read of entire line in advance
        uint32_t x = 0;
        #ifdef ENABLE_PIXEL_IN_READ
        frame_buf_read_start(x, y, FRAME_WIDTH);
        #endif

        // Can also in advance setup all writes to finish as well
        // (try will fail, but will have begun process with expected num pixels)
        try_frame_buf_write_finish(FRAME_WIDTH);
      
        // Then process one pixel at a time
        while(x < FRAME_WIDTH){
          #ifdef ENABLE_PIXEL_IN_READ
          frame_buf_read_finish(&p, 1);
          #endif
          kernel(x, y, frame_count, &p, &p);
          frame_buf_write_start(x, y, 1, &p);
          x += 1;
        }
        
        // Final wait to finish all writes
        frame_buf_write_finish(FRAME_WIDTH);
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
    frame_count += 1;
  }
}