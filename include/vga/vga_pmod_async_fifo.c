#pragma once
#include "compiler.h"
#include "fifo.h"

// Allow data to be streamed out of the vga pmod interface from any clock domain
// A as-small-as-posible ASYNC FIFO is used to buffer samples from the input domain
// which needs to be faster than the output pixel clock domain

// Declare the ASYNC FIFO instance
// Buffers all the vga signals and pixel colors
#include "vga_signals.h"
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color
typedef struct vga_fifo_word_t
{
  vga_signals_t vga;
  pixel_t color;
}vga_fifo_word_t;
// The fifo itself
#define VGA_ASYNC_FIFO_DEPTH 16 // Min async fifo size=16
vga_fifo_word_t vga_async_fifo[VGA_ASYNC_FIFO_DEPTH]; 
#include "clock_crossing/vga_async_fifo.h"

// There might be a non zero latency between
// the VGA timing outputs being stalled
// and pixel data flowing into the ASYNC fifo stopping.
// And since stall/feedback/flow control signals
// does not always behave as expect: 
// https://github.com/JulianKemmerer/PipelineC/issues/122
// Another small sync FIFO is used 
// to add extra buffering to cover the delay between 
// the stall at the timing module and stop of pixel data later
#define MAX_VGA_TIMING_TO_PIXEL_CYCLES 2
// The built in FIFO_FWFT has its own extra pausing/latency delay issue
// https://github.com/JulianKemmerer/PipelineC/issues/142 See: fifo.h
// FIFO_FWFT_EXTRA_STOP_LATENCY, FIFO_FWFT_MIN_PROG_FULL
#include "fifo.h"
// FIFO is intended to run just above at minimum level, set prog full
#define VGA_LATENCY_FIFO_PROG_FULL FIFO_FWFT_MIN_PROG_FULL
// FIFO needs to be big enough to run at prog full
// while also having "skid room" for the latencies involved in stopping
#define VGA_LATENCY_FIFO_DEPTH (VGA_LATENCY_FIFO_PROG_FULL + MAX_VGA_TIMING_TO_PIXEL_CYCLES + FIFO_FWFT_EXTRA_STOP_LATENCY)
FIFO_FWFT(vga_latency_fifo, vga_fifo_word_t, VGA_LATENCY_FIFO_DEPTH)

// If sync fifo is nearing full then the vga timing counters, hsync, vsync etc, is stalled
// A globally visible stall wire connected to the VGA timing instance is used
#include "vga_stall_signal.c"
#include "vga_timing.h"

// Chipscope debug hooks
#ifdef DEBUG
#include "debug_port.h"
DEBUG_REG_DECL(vga_signals_t, vga_in_debug)
DEBUG_REG_DECL(uint1_t, sync_fifo_rd_en_debug)
DEBUG_REG_DECL(vga_latency_fifo_t, sync_fifo_debug)
DEBUG_REG_DECL(uint1_t, async_fifo_wr_en_debug)
DEBUG_REG_DECL(vga_fifo_word_t, async_fifo_wr_data_debug)
DEBUG_REG_DECL(vga_async_fifo_write_t, async_fifo_debug)
#endif

// Write side of async fifo, any clock rate faster than pixel clock
void pmod_async_fifo_write(vga_signals_t vga, pixel_t color)
{
  // Write first goes through small stall latency fifo
  uint1_t sync_fifo_wr_en = vga.valid;
  vga_fifo_word_t sync_fifo_wr_data;
  sync_fifo_wr_data.vga = vga;
  sync_fifo_wr_data.color = color;
  uint1_t sync_fifo_rd_en;
  #pragma FEEDBACK sync_fifo_rd_en // Value is from later assignment
  vga_latency_fifo_t sync_fifo = vga_latency_fifo(sync_fifo_rd_en, sync_fifo_wr_data, sync_fifo_wr_en);
  #ifdef DEBUG
  vga_in_debug = vga;
  sync_fifo_debug = sync_fifo;
  sync_fifo_rd_en_debug = sync_fifo_rd_en;
  #endif

  // Data then flows into ASYNC fifo to slow pixel clock domain
  // Try to write VGA signal into ASYNC FIFO
  uint1_t async_fifo_wr_en = sync_fifo.data_out_valid;
  vga_fifo_word_t async_fifo_wr_data[1];
  async_fifo_wr_data[0].vga = sync_fifo.data_out.vga;
  async_fifo_wr_data[0].color = sync_fifo.data_out.color;
  vga_async_fifo_write_t async_fifo = vga_async_fifo_WRITE_1(async_fifo_wr_data, async_fifo_wr_en);
  #ifdef DEBUG
  async_fifo_wr_en_debug = async_fifo_wr_en;
  async_fifo_wr_data_debug = async_fifo_wr_data[0];
  async_fifo_debug = async_fifo;
  #endif
  
  // Read from sync fifo if async was ready
  sync_fifo_rd_en = async_fifo.ready;

  // Stall the vga timing 'in advance' using prog full 
  // 'overflow' extra data from stall latency is saved in sync fifo
  vga_req_stall = (sync_fifo.count>=VGA_LATENCY_FIFO_PROG_FULL);
}

// Chipscope debug hooks
#ifdef DEBUG
DEBUG_REG_DECL(uint16_t, wait_counter_debug)
DEBUG_REG_DECL(uint1_t, async_fifo_valid_out_debug)
DEBUG_REG_DECL(vga_fifo_word_t, async_fifo_data_out_debug)
#endif

// Pixel clock output side using standard vga pmod connection
#include "vga_pmod.c"
MAIN_MHZ(pmod_async_fifo_reader, PIXEL_CLK_MHZ)
void pmod_async_fifo_reader()
{
  // Avoid getting caught and weirdness regarding
  // clock rates close to pixel clock and any initial gaps in data
  // by waiting a few clocks to build up some pixels first
  static uint16_t wait_counter = (VGA_ASYNC_FIFO_DEPTH/2);
  
  // Read from async fifo always once initial wait elapsed
  uint1_t rd_en = (wait_counter==0);
  vga_async_fifo_read_t read = vga_async_fifo_READ_1(rd_en);
  vga_fifo_word_t rd_data = read.data[0];
  pmod_register_outputs(rd_data.vga, rd_data.color);
  #ifdef DEBUG
  wait_counter_debug = wait_counter;
  async_fifo_valid_out_debug = read.valid;
  async_fifo_data_out_debug = rd_data;
  #endif

  // Count once valid pixels arrive at fifo output
  if(read.valid)
  {
    if(wait_counter > 0)
    {
       wait_counter -= 1;
    }
  }
}