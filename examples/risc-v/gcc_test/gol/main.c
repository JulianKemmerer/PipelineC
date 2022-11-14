#include <stdint.h>
#include "../../../../compiler.h" // 'and' 'or' workaround

// Hardware memory map
#include "../../mem_map.h"

// General CPU frame buffer hooks, ex. frame_buf_read|write
#ifdef FRAME_BUFFER
#ifdef __PIPELINEC__ // Only HW stuff in .c file
#include "../../frame_buffer.c"
#endif
#endif

// Demo application that plays Conway's Game of Life
// Software implementations (which can also be used to derive HW FSMs)

// Returns the count of alive neighbours around x,y
#ifndef COUNT_NEIGHBORS_IGNORE_C_CODE
int32_t count_neighbors(int32_t x, int32_t y){
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

// Include various Gol specific hardware acceleration if using as plain c code
// like count_neighbors, cell_next_state, next_state_buf_rw, etc
#ifndef __PIPELINEC__
#include "hw.c"

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
    #ifdef USE_NEXT_STATE_BUF_RW
    next_state_buf_rw_in_t args;
    #endif

    // Precompute+fill next state line buffers
    // Line at y-2 is at line_sel=0, y-1 at line_sel=1
    int32_t y_minus_2_line_sel = 0;
    int32_t y_minus_1_line_sel = 1;
    for(y=0; y<2; y+=1)
    {
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        #ifdef USE_NEXT_STATE_BUF_RW
        args.frame_x = x;
        args.frame_y = y;
        args.line_sel = y;
        args.op_sel = NEXT_STATE_LINE_WRITE;
        next_state_buf_rw(args);
        #else
        cell_alive_next = cell_next_state(x, y);
        line_buf_write(y, x, cell_alive_next);
        #endif
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
        #ifdef USE_NEXT_STATE_BUF_RW
        args.frame_x = x;
        args.frame_y = y_write;
        args.line_sel = y_minus_2_line_sel;
        args.op_sel = LINE_READ_FRAME_WRITE;
        next_state_buf_rw(args);
        #else
        cell_alive_next = line_buf_read(y_minus_2_line_sel, x);
        frame_buf_write(x, y_write, cell_alive_next);
        #endif
      }

      // Use now available y_minus_2_line_sel line buffer
      // to store next state from current reads
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        #ifdef USE_NEXT_STATE_BUF_RW
        args.frame_x = x;
        args.frame_y = y;
        args.line_sel = y_minus_2_line_sel;
        args.op_sel = NEXT_STATE_LINE_WRITE;
        next_state_buf_rw(args);
        #else
        cell_alive_next = cell_next_state(x, y);
        line_buf_write(y_minus_2_line_sel, x, cell_alive_next);
        #endif
      }

      // Swap buffers (flip sel bits)
      y_minus_2_line_sel = y_minus_2_line_sel==0 ? 1 : 0;
      y_minus_1_line_sel = y_minus_1_line_sel==0 ? 1 : 0;
    }

    // Write next states of final lines left in buffers
    for(x=0; x<FRAME_WIDTH; x+=1)
    {
      y_write = FRAME_HEIGHT - 2;
      #ifdef USE_NEXT_STATE_BUF_RW
      args.frame_x = x;
      args.frame_y = y_write;
      args.line_sel = y_minus_2_line_sel;
      args.op_sel = LINE_READ_FRAME_WRITE;
      next_state_buf_rw(args);
      #else
      cell_alive_next = line_buf_read(y_minus_2_line_sel, x);
      frame_buf_write(x, y_write, cell_alive_next);
      #endif
      //
      y_write = FRAME_HEIGHT - 1;
      #ifdef USE_NEXT_STATE_BUF_RW
      args.frame_x = x;
      args.frame_y = y_write;
      args.line_sel = y_minus_1_line_sel;
      args.op_sel = LINE_READ_FRAME_WRITE;
      next_state_buf_rw(args);
      #else
      cell_alive_next = line_buf_read(y_minus_1_line_sel, x);
      frame_buf_write(x, y_write, cell_alive_next);
      #endif
    }
  }
  return 0;
}

#endif