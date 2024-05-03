#pragma once
#include "compiler.h"
#include "fifo.h"

// Allow data to be streamed out of the vga pmod interface from any clock domain
// This version only expects per screen x,y pixel colors into fifo 
// (not all vga signals like vga_pmod_async_fifo.c)
// Also this version assumes proper flow control out of fifo
// and does not use 'in advance' prog full based stall signal
// directly connected to the otherwise free running vga_timing

// Only pixels are written into the FIFO
// VGA timing is done at the output of the fifo
// (not reading during blank, only x,y pixels out of fifo)

// Configurable N_PIXELS wide FIFO and pixel_clk side does serialize
#ifndef VGA_ASYNC_FIFO_N_PIXELS
#define VGA_ASYNC_FIFO_N_PIXELS 1
#endif

// Declare the ASYNC FIFO instance
// Buffers all the vga signals and pixel colors
#include "vga_signals.h"
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color
typedef struct vga_fifo_word_t
{
  pixel_t pixels[VGA_ASYNC_FIFO_N_PIXELS];
}vga_fifo_word_t;
// The fifo itself
#define VGA_ASYNC_FIFO_DEPTH 256 // 256 need for DDR access pattern it seems... // Min async fifo size=16
vga_fifo_word_t vga_async_fifo[VGA_ASYNC_FIFO_DEPTH]; 
#include "clock_crossing/vga_async_fifo.h"

// VGA timing counter logic, etc
#include "vga_timing.h"

// Chipscope debug hooks
#ifdef VGA_PMOD_ASYNC_FIFO_DEBUG
#include "debug_port.h"
DEBUG_REG_DECL(vga_signals_t, vga_in_debug)
DEBUG_REG_DECL(uint1_t, sync_fifo_rd_en_debug)
DEBUG_REG_DECL(vga_latency_fifo_t, sync_fifo_debug)
DEBUG_REG_DECL(uint1_t, async_fifo_wr_en_debug)
DEBUG_REG_DECL(vga_fifo_word_t, async_fifo_wr_data_debug)
DEBUG_REG_DECL(vga_async_fifo_write_t, async_fifo_debug)
#endif

// Write side of async fifo, any clock rate faster than pixel clock
/*typedef struct pmod_async_fifo_write_t
{
  uint1_t ready;
}pmod_async_fifo_write_t;*/
uint1_t pmod_async_fifo_write_logic(pixel_t pixels[VGA_ASYNC_FIFO_N_PIXELS], uint1_t wr_en)
{
  // Try to write VGA signal into ASYNC FIFO
  vga_fifo_word_t async_fifo_wr_data[1];
  async_fifo_wr_data[0].pixels = pixels;
  vga_async_fifo_write_t async_fifo = vga_async_fifo_WRITE_1(async_fifo_wr_data, wr_en);
  #ifdef VGA_PMOD_ASYNC_FIFO_DEBUG
  async_fifo_wr_en_debug = async_fifo_wr_en;
  async_fifo_wr_data_debug = async_fifo_wr_data[0];
  async_fifo_debug = async_fifo;
  #endif
  // Connect ready from fifo to output
  /*pmod_async_fifo_write_t o;
  o.ready = async_fifo.ready;*/
  return async_fifo.ready;
}
void pmod_async_fifo_write(pixel_t pixels[VGA_ASYNC_FIFO_N_PIXELS])
{
  // FSM wrap pmod_async_fifo_write_logic
  uint1_t done = 0;
  do
  {
    done = pmod_async_fifo_write_logic(pixels, 1);
    __clk();
  }while(!done);
}

// Chipscope debug hooks
#ifdef VGA_PMOD_ASYNC_FIFO_DEBUG
DEBUG_REG_DECL(uint16_t, wait_counter_debug)
DEBUG_REG_DECL(uint1_t, async_fifo_valid_out_debug)
DEBUG_REG_DECL(vga_fifo_word_t, async_fifo_data_out_debug)
#endif


// Pixel clock output side using standard vga pmod connection
#include "vga_pmod.c"
#include "stream/serializer.h"
serializer(pixel_serializer, pixel_t, VGA_ASYNC_FIFO_N_PIXELS)
MAIN_MHZ(pmod_async_fifo_reader, PIXEL_CLK_MHZ)
void pmod_async_fifo_reader()
{
  // Avoid getting caught and weirdness regarding
  // clock rates close to pixel clock and any initial gaps in data
  // by waiting a few clocks to build up some pixels first
  static uint16_t wait_counter = (VGA_ASYNC_FIFO_DEPTH/2);
  uint1_t wait_done = (wait_counter==0);

  // Read pixels from async fifo if serializer is ready
  uint1_t ser_in_ready;
  #pragma FEEDBACK ser_in_ready // Not driven until later
  uint1_t rd_en = ser_in_ready;
  vga_async_fifo_read_t fifo_read = vga_async_fifo_READ_1(rd_en);
  vga_fifo_word_t rd_data = fifo_read.data[0];
  #ifdef VGA_PMOD_ASYNC_FIFO_DEBUG
  wait_counter_debug = wait_counter;
  async_fifo_valid_out_debug = fifo_read.valid;
  async_fifo_data_out_debug = rd_data;
  #endif
  
  // Serialize the n pixels to one at a time stream
  // Read pixel if VGA timing is active and wait is done
  static vga_signals_t vga_signals;
  uint1_t ser_out_data_ready = vga_signals.active & wait_done;
  pixel_serializer_o_t pixel_ser = pixel_serializer(rd_data.pixels, fifo_read.valid, ser_out_data_ready);
  ser_in_ready = pixel_ser.in_data_ready; // FEEDBACK

  // For now directly into regs
  pmod_register_outputs(vga_signals, pixel_ser.out_data);

  // Advance vga timing when wait is done
  if(wait_done)
  {
    // Stall if ready for data and wasnt valid there?
    // Shouldnt be needed....
    if(!ser_out_data_ready | (ser_out_data_ready & pixel_ser.out_data_valid))
    {
      vga_signals = vga_timing();
    }
  }
 
  // Count once valid pixels arrive at output
  if(pixel_ser.out_data_valid)
  {
    if(wait_counter > 0)
    {
      wait_counter -= 1;
    }
  }
}