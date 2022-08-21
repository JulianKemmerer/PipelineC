
// Set the target FPGA part
//#pragma PART "LFE5U-85F-6BG381C" // An ECP5U 85F part
#pragma PART "xc7a35ticsg324-1l" // Arty 35t
//#pragma PART "xc7a100tcsg324-1" // Arty 100t

#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480

// Common PipelineC includes
#include "compiler.h"
#include "uintN_t.h"
#include "intN_t.h"
#include "vga/vga_pmod.c"

// Include frame buffer RAM code and helper funcs
// (also include 2-line buffer for Game of Life)
#include "frame_buffer_ram.c"

// Display side of frame buffer is always reading
MAIN_MHZ(frame_buffer_display, PIXEL_CLK_MHZ)
void frame_buffer_display()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();

  // Do RAM lookup
  frame_buf_outputs_t frame_buf_outputs = frame_buf_function(vga_signals);
  uint1_t vga_pixel = frame_buf_outputs.read_val;
  vga_signals = frame_buf_outputs.vga_signals;
  
  // Default black=0 unless pixel is white=1
  pixel_t color = {0};
  if(vga_pixel)
  {
    color.r = 255;
    color.g = 255;
    color.b = 255;
  }

  // Final connection to output display pmod
  pmod_register_outputs(vga_signals, color);
}

// Demo application that plays Conway's Game of Life
// https://www.geeksforgeeks.org/program-for-conways-game-of-life/
//returns the count of alive neighbours around r,c
uint8_t count_live_neighbour_cells(uint32_t r, uint32_t c){
  int32_t i, j;
  uint8_t count=0;
  for(i=r-1; i<=r+1; i+=1){
      for(j=c-1;j<=c+1;j+=1){
          if(!( ((i==r) & (j==c)) | ((i<0) | (j<0)) | ((i>=FRAME_WIDTH) | (j>=FRAME_HEIGHT)))){
            uint1_t cell_alive = frame_buf_read(i, j);
            if(cell_alive){
              count+=1;
            }
          }
      }
  }
  return count;
}
// Game of Life logic to determine if cell at x,y lives or dies
uint1_t cell_next_state(uint16_t x, uint16_t y)
{
  uint8_t neighbour_live_cells = count_live_neighbour_cells(x, y);
  uint1_t cell_alive = frame_buf_read(x, y);
  uint1_t cell_alive_next;
  if(cell_alive & ((neighbour_live_cells==2) | (neighbour_live_cells==3))){
      cell_alive_next=1;
  }
  else if(!cell_alive & (neighbour_live_cells==3)){
      cell_alive_next=1;
  }
  else{
      cell_alive_next=0;
  }
  return cell_alive_next;
}
// Main function using one frame buffer and two line buffers
void main()
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
    uint32_t x, y;
    uint1_t cell_alive_next;
    
    // Precompute+fill next state line buffers
    // Line at y-2 is at line_sel=0, y-1 at line_sel=1
    uint1_t y_minus_2_line_sel = 0;
    uint1_t y_minus_1_line_sel = 1;
    for(y=0; y<2; y+=1)
    {
      for(x=0; x<FRAME_WIDTH; x+=1)
      {
        cell_alive_next = cell_next_state(x, y);
        line_buf_write(y, x, cell_alive_next);
      }
    }

    // Starting with some next line buffers completed makes loop easier to write
    uint16_t y_write;
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
      y_minus_2_line_sel = !y_minus_2_line_sel;
      y_minus_1_line_sel = !y_minus_1_line_sel;
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
}

// Derived fsm from main (TODO code gen...)
#include "main_FSM.h"
// Wrap up main FSM as top level
MAIN_MHZ(main_wrapper, PIXEL_CLK_MHZ)
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}

// Demo 'application' state machine that inverts pixels every second
/*void main()
{
  while(1)
  {
    // Loop over all pixels
    uint32_t x, y;
    for(x=0; x<FRAME_WIDTH; x+=1)
    {
      for(y=0; y<FRAME_HEIGHT; y+=1)
      {      
        // Read the pixel value
        uint1_t pixel = frame_buf_read(x, y);
        // Invert color
        pixel = !pixel;
        // Write pixel value back
        frame_buf_write(x, y, pixel);
      }
    }
    // Wait a ~second
    uint32_t sec_ticks_remaining = (uint32_t)(PIXEL_CLK_MHZ * 1.0e6);
    while(sec_ticks_remaining > 0)
    {
      sec_ticks_remaining -= 1;
      __clk();
    }
  }
}*/