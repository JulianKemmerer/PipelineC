// Define the frame buffer RAM
#include "uintN_t.h"
#include "arrays.h"
#include "ram.h" // For DECL_RAM_DP_RW_R macros
#include "frame_buffer.h" // For frame size
// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application' (CPU in this demo)
// RAM init data from file
#include "gcc_test/gol/frame_buf_init_data.h"
// Configure frame buffer based on latency
#define FRAME_BUFFER_LATENCY 0
#if FRAME_BUFFER_LATENCY == 0
DECL_RAM_DP_RW_R_0(
#elif FRAME_BUFFER_LATENCY == 1
DECL_RAM_DP_RW_R_1(
#elif FRAME_BUFFER_LATENCY == 2
DECL_RAM_DP_RW_R_2(
#endif
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

// Uses async fifo to buffer VGA pmod signals into pixel clock domain
#include "vga/vga_pmod_async_fifo.c"

// Frame buffer application/user global wires for use once anywhere in code
typedef struct frame_buffer_inputs_t{
  uint16_t x;
  uint16_t y;
  uint1_t wr_data;
  uint1_t wr_en;
  uint1_t valid;
}frame_buffer_inputs_t;
typedef struct frame_buffer_outputs_t{
  // Inputs corresponding to output data
  frame_buffer_inputs_t inputs; 
  // The output data
  uint1_t rd_data;
}frame_buffer_outputs_t;
//  Inputs
frame_buffer_inputs_t frame_buffer_in;
//  Outputs
frame_buffer_outputs_t frame_buffer_out;

// Logic for wiring up VGA chasing the beam signals and user frame buffer wires
// User application uses frame_buffer_ wires directly
MAIN_MHZ(frame_buf_function, CPU_CLK_MHZ)
void frame_buf_function()
{
  // VGA timing for fixed resolution, with stall signals
  vga_signals_t vga_signals = vga_timing();

  // Convert VGA timing position
  // and application x,y pos to RAM addresses
  uint32_t frame_buffer_addr = pos_to_addr(frame_buffer_in.x, frame_buffer_in.y);
  uint32_t vga_addr = pos_to_addr(vga_signals.pos.x, vga_signals.pos.y);

  // Do RAM lookups
  // First port is for user application, is read+write
  // Second port is read only for the frame buffer vga display
  frame_buf_ram_outputs_t ram_outputs
    = frame_buf_ram(frame_buffer_addr, // Port0
                    frame_buffer_in.wr_data, 
                    frame_buffer_in.wr_en,
                    frame_buffer_in.valid,
                    #if FRAME_BUFFER_LATENCY == 2
                    1, // Always input regs enabled
                    #endif
                    #if FRAME_BUFFER_LATENCY >= 1
                    TODO FIX PORTS
                    1, // Always reading
                    #endif     
                    vga_addr, // Port1
                    1 // Inputs always valid
                    #if FRAME_BUFFER_LATENCY == 2
                    , 1 // Always input regs enabled
                    #endif
                    #if FRAME_BUFFER_LATENCY >= 1
                    TODO FIX PORTS
                    , 1 // Always output regs enabled
                    #endif
                    );

  // Delay VGA signals to match ram output latency
  uint16_t frame_buffer_in_x = frame_buffer_in.x;
  uint16_t frame_buffer_in_y = frame_buffer_in.x;
  #if FRAME_BUFFER_LATENCY > 0
  TODO local delay wars frame_buffer_in_x,y
  static vga_signals_t vga_delay_regs[FRAME_BUFFER_LATENCY];
  vga_signals_t vga_signals_into_delay = vga_signals;
  // Drive vga_signals from end/output delay regs
  vga_signals = vga_delay_regs[FRAME_BUFFER_LATENCY-1];
  // Shift array up to make room, and then put new vga at buf[0]
  ARRAY_SHIFT_UP(vga_delay_regs, FRAME_BUFFER_LATENCY, 1)
  vga_delay_regs[0] = vga_signals_into_delay;
  #endif
  
  // Drive output signals with RAM values (delayed FRAME_BUFFER_LATENCY)
  frame_buffer_out.inputs.x = frame_buffer_in_x; 
  frame_buffer_out.inputs.y = frame_buffer_in_y;
  frame_buffer_out.inputs.wr_data = ram_outputs.wr_data0;
  frame_buffer_out.inputs.wr_en = ram_outputs.wr_en0;
  frame_buffer_out.inputs.valid = ram_outputs.valid0;
  frame_buffer_out.rd_data = ram_outputs.rd_data0;

  // Default black=0 unless pixel is white=1
  pixel_t color = {0};
  uint1_t vga_pixel = ram_outputs.rd_data1;
  if(vga_pixel)
  {
    color.r = 255;
    color.g = 255;
    color.b = 255;
  }

  // Final connection to output display pmod
  pmod_async_fifo_write(vga_signals, color);
}

// Similar structure for two-line buffer RAM/s

// Global wires for use once anywhere in code
typedef struct line_bufs_inputs_t{
  uint1_t line_sel;
  uint16_t x;
  uint1_t wr_data;
  uint1_t wr_en; // 0=read
  uint1_t valid;
}line_bufs_inputs_t;
typedef struct line_bufs_outputs_t{
  // Inputs corresponding to outputs
  line_bufs_inputs_t inputs;
  uint1_t rd_data;
}line_bufs_outputs_t;
//  Inputs
line_bufs_inputs_t line_bufs_in;
//  Outputs
line_bufs_outputs_t line_bufs_out;

// Configure latency to match frame buffer
#if FRAME_BUFFER_LATENCY == 0
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_0
#elif FRAME_BUFFER_LATENCY == 1
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_1
#elif FRAME_BUFFER_LATENCY == 2
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_2
#endif

// Line buffer used only by application via global wires (never called directly)
// So need stand alone func to wire things up (similar to frame buffer wiring)
MAIN_MHZ(line_bufs_function, CPU_CLK_MHZ)
void line_bufs_function()
{
  // Do RAM lookups, 0 clk delay
  // Is built in as _RAM_SP_RF_0 (single port, read first, 0 clocks)
  // Two line buffers inside one func for now
  static uint1_t line_buf0[FRAME_WIDTH];
  static uint1_t line_buf1[FRAME_WIDTH];
  uint1_t read_val;
  if (line_bufs_in.line_sel) {
    read_val = line_buf_RAM(1)(line_bufs_in.x, line_bufs_in.wr_data, line_bufs_in.wr_en & line_bufs_in.valid);
  } else {
    read_val = line_buf_RAM(0)(line_bufs_in.x, line_bufs_in.wr_data, line_bufs_in.wr_en & line_bufs_in.valid);
  }

  // Drive output signals with RAM values (delayed FRAME_BUFFER_LATENCY)
  line_bufs_inputs_t line_bufs_in_delayed = line_bufs_in;
  #if FRAME_BUFFER_LATENCY > 0
  TODO buffer inputs to align with outputs
  #endif
  // Drive output signals
  line_bufs_out.rd_data = read_val;
  line_bufs_out.inputs = line_bufs_in_delayed;
}
