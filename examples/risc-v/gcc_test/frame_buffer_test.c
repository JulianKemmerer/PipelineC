#include <stdint.h>
#include "mem_map.h"
#include "frame_buffer_test.h"

void main() {
  // Do test of modifying pixels
  *LED = 1;
  // x,y bounds based on which thread you are
  // Let each thread do entire horizontal X lines, split Y direction

  // Write all pixels with test pattern
  pixel_t p;
  //while(1){
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
  //}

  // Toggle as test of fast read and write
  while(1){
    for(int y=0; y < FRAME_HEIGHT; y+=1){
        for(int x=*THREAD_ID; x < FRAME_WIDTH; x+=NUM_THREADS){
            // Read pixel
            frame_buf_read(x, y, 1, &p);
            // Invert all colors 
            p.r = ~p.r;
            p.g = ~p.g;
            p.b = ~p.b;
            // Write to screen
            frame_buf_write(x, y, 1, &p);
        }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
  }
}
