
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

// Helper function to flatten 2D x,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  return (x*FRAME_HEIGHT) + y;
}

// Include frame buffer RAM code and helper funcs
#include "frame_buffer_ram.c"

// Display side of frame buffer is always reading
// TODO add valid signal for pipelining, must be --comb for now
MAIN_MHZ(frame_buffer_display, PIXEL_CLK_MHZ)
void frame_buffer_display()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();

  // Convert VGA timing position
  // and application x,y pos to RAM addresses
  // First port is for user application, is read+write
  // Second port is read only for the frame buffer vga display
  uint32_t frame_buffer_addr = pos_to_addr(frame_buffer_x_in, frame_buffer_y_in);
  uint32_t vga_addr = pos_to_addr(vga_signals.pos.x, vga_signals.pos.y);  

  // Do RAM lookups
  frame_buf_outputs_t frame_buf_outputs
    = frame_buf_function(frame_buffer_addr, 
                         frame_buffer_wr_data_in, 
                         frame_buffer_wr_enable_in,
                         vga_addr);

  // Drive output signals with RAM values
  frame_buffer_rd_data_out = frame_buf_outputs.read_data0;
  // Default black=0 unless pixel is white=1
  pixel_t color = {0};
  uint1_t vga_pixel = frame_buf_outputs.read_data1;
  if(vga_pixel)
  {
    color.r = 255;
    color.g = 255;
    color.b = 255;
  }

  // Final connection to output display pmod
  pmod_register_outputs(vga_signals, color);
}

// Demo 'application' state machine that inverts pixels every second
void main()
{
  while(1)
  {
    // Loop over all chunks of pixels
    uint32_t x, y;
    for(x=0; x<FRAME_WIDTH; x+=1)
    {
      for(y=0; y<FRAME_HEIGHT; y+=1)
      {      
        // Read the pixel value
        uint1_t pixel = frame_buf_read(x, y);
        // Invert color
        pixel = !pixel;
        // Write pixel values back
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

/*// A very inefficient all LUTs/muxes (no BRAM) zero latency ~frame buffer
  // https://github.com/JulianKemmerer/PipelineC/wiki/Arrays
  // Array access implemented uses muxes, ex. 640x480=307200
  // so read is implemented like a 307200->1 mux...
  // Actually each index is rounded to power of 2, so 640x480 becomes 1024x512
  //    frame_buffer_ram[10b x value][9b y value] 
  // is same as
  //    frame_buffer_ram[19b address]
  // ...very big/inefficient/slow...
  // 19b select for 524288->1 mux (only 307200 addresses used)...
  static pixel_t frame_buffer_ram[FRAME_WIDTH][FRAME_HEIGHT];
  pixel_t color = frame_buffer_ram[vga_signals.pos.x][vga_signals.pos.y];
  // The additonal read/write port for the main application
  frame_buffer_rd_data_out = frame_buffer_ram[frame_buffer_x_in][frame_buffer_y_in];
  if(frame_buffer_wr_enable_in)
  {
    frame_buffer_ram[frame_buffer_x_in][frame_buffer_y_in] = frame_buffer_wr_data_in;
  }
*/

/*// Allow for reading+writing N pixels at a time from a frame buffer port
// (could be turned into a line buffer)
#define FRAME_BUF_DATA_SIZE_PIXELS 1
typedef struct frame_buf_data_t
{
    pixel_t pixels[FRAME_BUF_DATA_SIZE_PIXELS];
}frame_buf_data_t; 
// Frame buffer RAM stores all pixels in chunks of FRAME_BUF_DATA_SIZE_PIXELS
#define TOTAL_PIXELS (FRAME_HEIGHT*FRAME_WIDTH)
#define FRAME_BUF_NUM_ENTRIES (TOTAL_PIXELS/FRAME_BUF_DATA_SIZE_PIXELS)
frame_buf_data_t frame_buffer[FRAME_BUF_NUM_ENTRIES];
*/