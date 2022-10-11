// Define the frame buffer RAM
#include "ram.h" // For DECL_RAM_DP_RW_R_0 macro
#include "frame_buffer.h" // For frame size
// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application' (CPU in this demo)
// RAM init data from file
#include "gcc_test/gol/frame_buf_init_data.h"
DECL_RAM_DP_RW_R_0(
  uint1_t,
  frame_buf_ram,
  FRAME_WIDTH*FRAME_HEIGHT,
  FRAME_BUF_INIT_DATA
)

// Helper function to flatten 2D x,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  return (x*FRAME_HEIGHT) + y;
}

// Uses VGA pmod signals
#include "vga/vga_pmod.c"

// Frame buffer application/user global wires for use once anywhere in code
//  Inputs
uint1_t frame_buffer_wr_data_in;
uint16_t frame_buffer_x_in;
uint16_t frame_buffer_y_in;
uint1_t frame_buffer_wr_enable_in; // 0=read
//  Outputs
uint1_t frame_buffer_rd_data_out;

// Logic for wiring up VGA chasing the beam signals and user frame buffer wires
// User application uses frame_buffer_ wires directly
typedef struct frame_buf_outputs_t{
  uint1_t read_val;
  vga_signals_t vga_signals;
} frame_buf_outputs_t;
MAIN_MHZ(frame_buf_function, PIXEL_CLK_MHZ)
void frame_buf_function()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();

  // Convert VGA timing position
  // and application x,y pos to RAM addresses
  uint32_t frame_buffer_addr = pos_to_addr(frame_buffer_x_in, frame_buffer_y_in);
  uint32_t vga_addr = pos_to_addr(vga_signals.pos.x, vga_signals.pos.y);

  // Do RAM lookup
  // Do RAM lookups
  // First port is for user application, is read+write
  // Second port is read only for the frame buffer vga display
  frame_buf_ram_outputs_t frame_buf_outputs
    = frame_buf_ram(frame_buffer_addr, 
                         frame_buffer_wr_data_in, 
                         frame_buffer_wr_enable_in,
                         vga_addr);
  
  // Drive output signals with RAM values
  frame_buffer_rd_data_out = frame_buf_outputs.rd_data0;
  // Default black=0 unless pixel is white=1
  pixel_t color = {0};
  uint1_t vga_pixel = frame_buf_outputs.rd_data1;
  if(vga_pixel)
  {
    color.r = 255;
    color.g = 255;
    color.b = 255;
  }

  // Final connection to output display pmod
  pmod_register_outputs(vga_signals, color);
}

// Similar structure for two-line buffer RAM/s
// Global wires for use once anywhere in code
//  Inputs
uint1_t line_bufs_line_sel_in;
uint16_t line_bufs_x_in;
uint1_t line_bufs_wr_data_in;
uint1_t line_bufs_wr_enable_in; // 0=read
//  Outputs
uint1_t line_bufs_rd_data_out;

// Line buffer used only by application via global wires (never called directly)
// So need stand alone func to wire things up (similar to frame buffer wiring)
MAIN_MHZ(line_bufs_function, PIXEL_CLK_MHZ)
void line_bufs_function()
{
  // Do RAM lookups, 0 clk delay
  // Is built in as _RAM_SP_RF_0 (single port, read first, 0 clocks)
  // Two line buffers inside one func for now
  static uint1_t line_buf0[FRAME_WIDTH];
  static uint1_t line_buf1[FRAME_WIDTH];
  uint1_t read_val;
  if (line_bufs_line_sel_in) {
    read_val = line_buf1_RAM_SP_RF_0(line_bufs_x_in, line_bufs_wr_data_in, line_bufs_wr_enable_in);
  } else {
    read_val = line_buf0_RAM_SP_RF_0(line_bufs_x_in, line_bufs_wr_data_in, line_bufs_wr_enable_in);
  }
  // Drive output signals
  line_bufs_rd_data_out = read_val;
}
