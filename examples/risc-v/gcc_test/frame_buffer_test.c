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

  // Toggle as test of fast read and write
  while(1){
    //for(int y=*THREAD_ID; y < FRAME_HEIGHT; y+=NUM_THREADS){
    //    for(int x=0; x < FRAME_WIDTH; x+=BUFFER_N_PIXELS){
    for(int y=0; y < FRAME_HEIGHT; y+=1){
        for(int x=(*THREAD_ID)*RISCV_RAM_NUM_BURST_WORDS; x < FRAME_WIDTH; x+=(NUM_THREADS*RISCV_RAM_NUM_BURST_WORDS)){
            // Read pixel buffer
            pixel_t pixel_buf[RISCV_RAM_NUM_BURST_WORDS];
            frame_buf_read(x, y, RISCV_RAM_NUM_BURST_WORDS, pixel_buf);
            // Do kernel on all pixels
            for(int i=0; i < RISCV_RAM_NUM_BURST_WORDS; i++){
              kernel(x+i, y, &(pixel_buf[i]));
            }
            // Write pixel buffer
            frame_buf_write(x, y, RISCV_RAM_NUM_BURST_WORDS, pixel_buf);
        }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    threads_frame_sync();
  }
}
