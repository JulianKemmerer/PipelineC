#include <stdint.h>
#include "../../../../compiler.h" // 'and' 'or' workaround

// Include various hardware acceleration if using as plain c code
// like frame_buf_read/write, count_neighbors, etc
#ifndef __PIPELINEC__
#include "hw.c"
#endif

// Demo application that plays Conway's Game of Life
// returns the count of alive neighbours around x,y
#ifndef COUNT_NEIGHBORS_IGNORE_C_CODE
int32_t count_neighbors(int32_t x, int32_t y){
  // Software implementation (which can also be used to derive HW FSM)
  // https://www.geeksforgeeks.org/program-for-conways-game-of-life/
  int32_t i, j;
  int32_t count=0;
  for(i=x-1; i<=x+1; i+=1){
      for(j=y-1;j<=y+1;j+=1){
          if(!( ((i==x) and (j==y)) or ((i<0) or (j<0)) or ((i>=FRAME_WIDTH) or (j>=FRAME_HEIGHT)))){
            int32_t cell_alive = frame_buf_read(i, j);
            if(cell_alive==1){
              count+=1;
            }
          }
      }
  }
  return count;
}
#endif
#ifndef CELL_NEXT_STATE_IGNORE_C_CODE
// Game of Life logic to determine if cell at x,y lives or dies
int32_t cell_next_state(int32_t x, int32_t y)
{
  int32_t neighbour_live_cells = count_neighbors(x, y);
  int32_t cell_alive = frame_buf_read(x, y);
  int32_t cell_alive_next;
  if((cell_alive==1) and ((neighbour_live_cells==2) or (neighbour_live_cells==3))){
      cell_alive_next=1;
  }else if((cell_alive==0) and (neighbour_live_cells==3)){
      cell_alive_next=1;
  }else{
      cell_alive_next=0;
  }
  return cell_alive_next;
}
#endif


// Helper functions for working with one frame buffer and two line buffers
/*
// Read from line buffer, write data to frame buffer
void line_buf_read_frame_buf_write(
  int32_t line_sel, int32_t line_x,
  int32_t frame_x, int32_t frame_y)
{
  int32_t rd_data = line_buf_read(line_sel, line_x);
  frame_buf_write(frame_x, frame_y, rd_data);
}

// Compute next state for cell and write to line buffer
void cell_next_state_line_buf_write(int32_t frame_x, int32_t frame_y, int32_t line_sel)
{
  int32_t cell_alive_next = cell_next_state(frame_x, frame_y);
  line_buf_write(line_sel, frame_x, cell_alive_next);
}
*/

// Main function using one frame buffer and two line buffers
int32_t main()
{
  while(1)
  {
    // Loop over all pixels line by line
    // y is current read line
    // Writes of next state are delayed in two line buffers (index y-2)
    /*
           |----
           |   Y-2 WRITE  , Line Select = 0 |...
           |----
           |   Y-1 CELLS  , Line Select = 1 |...
           |----
      y->  |   READ CELLS ,                 |...
           |----  
    */
    int32_t x, y;
    int32_t cell_alive_next;
    
    // Precompute+fill next state line buffers
    // Line at y-2 is at line_sel=0, y-1 at line_sel=1
    int32_t y_minus_2_line_sel = 0;
    int32_t y_minus_1_line_sel = 1;
    for(y=0; y<2; y+=1)
    {
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        cell_alive_next = cell_next_state(x, y);
        line_buf_write(y, x, cell_alive_next);
      }
    }
    
    int32_t y_write;
    // Starting with some next line buffers completed makes loop easier to write
    for(y=2; y<FRAME_HEIGHT; y+=1)
    { 
      // Write line is 2 lines delayed
      y_write = y - 2;
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        cell_alive_next = line_buf_read(y_minus_2_line_sel, x);
        frame_buf_write(x, y_write, cell_alive_next);
      }

      // Use now available y_minus_2_line_sel line buffer
      // to store next state from current reads
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        cell_alive_next = cell_next_state(x, y);
        line_buf_write(y_minus_2_line_sel, x, cell_alive_next);
      }

      // Swap buffers (flip sel bits)
      y_minus_2_line_sel = y_minus_2_line_sel==0 ? 1 : 0;
      y_minus_1_line_sel = y_minus_1_line_sel==0 ? 1 : 0;
    }

    // Write next states of final lines left in buffers
    for(x=0; x<FRAME_WIDTH; x+=1)
    {
      y_write = FRAME_HEIGHT - 2;
      cell_alive_next = line_buf_read(y_minus_2_line_sel, x);
      frame_buf_write(x, y_write, cell_alive_next);
      y_write = FRAME_HEIGHT - 1;
      cell_alive_next = line_buf_read(y_minus_1_line_sel, x);
      frame_buf_write(x, y_write, cell_alive_next);
    }
  }
  return 0;
}