#pragma once
#ifndef __VGA_TIMING_H__
#define __VGA_TIMING_H__


#ifndef FRAME_WIDTH
#define FRAME_WIDTH 1920
#define FRAME_HEIGHT 1080
#endif

// Constants and logic to produce VGA signals at fixed resolution

////***640x480@60Hz***//  Requires 25 MHz clock
#if FRAME_HEIGHT == 480
#define PIXEL_CLK_MHZ 25.0

#define H_FP 16 //H front porch width (pixels)
#define H_PW 96 //H sync pulse width (pixels)
#define H_MAX 800 //H total period (pixels)

#define V_FP 10 //V front porch width (lines)
#define V_PW 2 //V sync pulse width (lines)
#define V_MAX 525 //V total period (lines)

#define H_POL 0
#define V_POL 0
#endif


////***800x600@60Hz***//  Requires 40 MHz clock
/*
#define PIXEL_CLK_MHZ 40.0
#define FRAME_WIDTH 800
#define FRAME_HEIGHT 600

#define H_FP 40 //H front porch width (pixels)
#define H_PW 128 //H sync pulse width (pixels)
#define H_MAX 1056 //H total period (pixels)

#define V_FP 1 //V front porch width (lines)
#define V_PW 4 //V sync pulse width (lines)
#define V_MAX 628 //V total period (lines)

#define H_POL 1
#define V_POL 1
*/

////***1280x720@60Hz***// Requires 74.25 MHz clock
/*
#define PIXEL_CLK_MHZ 74.25
#define FRAME_WIDTH 1280
#define FRAME_HEIGHT 720

#define H_FP 110 //H front porch width (pixels)
#define H_PW 40 //H sync pulse width (pixels)
#define H_MAX 1650 //H total period (pixels)

#define V_FP 5 //V front porch width (lines)
#define V_PW 5 //V sync pulse width (lines)
#define V_MAX 750 //V total period (lines)

#define H_POL 1
#define V_POL 1
*/

////***1280x1024@60Hz***// Requires 108 MHz clock
//#define PIXEL_CLK_MHZ 108.0
//#define FRAME_WIDTH 1280
//#define FRAME_HEIGHT 1024

//#define H_FP 48 //H front porch width (pixels)
//#define H_PW 112 //H sync pulse width (pixels)
//#define H_MAX 1688 //H total period (pixels)

//#define V_FP 1 //V front porch width (lines)
//#define V_PW 3 //V sync pulse width (lines)
//#define V_MAX 1066 //V total period (lines)

//#define H_POL 1
//#define V_POL 1


//***1920x1080@60Hz***// Requires 148.5 MHz pxl_clk

#if FRAME_HEIGHT == 1080
#define PIXEL_CLK_MHZ 148.5

#define H_FP 88 //H front porch width (pixels)
#define H_PW 44 //H sync pulse width (pixels)
#define H_MAX 2200 //H total period (pixels)

#define V_FP 4 //V front porch width (lines)
#define V_PW 5 //V sync pulse width (lines)
#define V_MAX 1125 //V total period (lines)

#define H_POL 1
#define V_POL 1
#endif

// VGA timing module
typedef struct vga_pos_t
{
  uint12_t x;
  uint12_t y;
}vga_pos_t;
typedef struct vga_signals_t
{
  vga_pos_t pos;
  uint1_t hsync;
  uint1_t vsync;
  uint1_t active;
  uint1_t start_of_frame;
  uint1_t end_of_frame;
}vga_signals_t;

#ifdef __PIPELINEC__
vga_signals_t vga_timing()
{
  uint1_t active;
  
  static uint12_t h_cntr_reg;
  static uint12_t v_cntr_reg;
  
  static uint1_t h_sync_reg = !H_POL;
  static uint1_t v_sync_reg = !V_POL;

  vga_signals_t o;
  o.hsync = h_sync_reg;
  o.vsync = v_sync_reg;
  o.pos.x = h_cntr_reg;
  o.pos.y = v_cntr_reg;
  active = 0;
  if((h_cntr_reg < FRAME_WIDTH) & (v_cntr_reg < FRAME_HEIGHT))
  {
    active = 1;
  }
  o.active = active;
  o.start_of_frame = (h_cntr_reg==0) & (v_cntr_reg==0);
  o.end_of_frame = (h_cntr_reg==(FRAME_WIDTH-1)) & (v_cntr_reg==(FRAME_HEIGHT-1));
  
  if((h_cntr_reg >= (H_FP + FRAME_WIDTH - 1)) & (h_cntr_reg < (H_FP + FRAME_WIDTH + H_PW - 1)))
  {
    h_sync_reg = H_POL;
  }
  else
  {
    h_sync_reg = !(H_POL);
  }

  if((v_cntr_reg >= (V_FP + FRAME_HEIGHT - 1)) & (v_cntr_reg < (V_FP + FRAME_HEIGHT + V_PW - 1)))
  {
    v_sync_reg = V_POL;
  }
  else
  {
    v_sync_reg = !(V_POL);
  }

  if((h_cntr_reg == (H_MAX - 1)) & (v_cntr_reg == (V_MAX - 1)))
  {
    v_cntr_reg = 0;
  }
  else if(h_cntr_reg == (H_MAX - 1))
  {
    v_cntr_reg = v_cntr_reg + 1;
  }

  if(h_cntr_reg == (H_MAX - 1))
  {
    h_cntr_reg = 0;
  }
  else
  {
    h_cntr_reg = h_cntr_reg + 1;
  }
  
  return o;
}
#endif // ifdef __PIPELINEC__

#ifndef __PIPELINEC__
// Software timing that includes frame pixels only (no front/back porch) timing
inline vga_signals_t vga_timing()
{
  static vga_signals_t current_timing;
  if(++current_timing.pos.x > FRAME_WIDTH)
  {
    current_timing.pos.x = 0;
    if(++current_timing.pos.y > FRAME_HEIGHT)
    {
      current_timing.pos.y = 0;
    }
  }
  current_timing.active = current_timing.pos.x < FRAME_WIDTH && current_timing.pos.y < FRAME_HEIGHT;
  current_timing.start_of_frame = (current_timing.pos.x==0) && (current_timing.pos.y==0);
  current_timing.end_of_frame = (current_timing.pos.x==(FRAME_WIDTH-1)) && (current_timing.pos.y==(FRAME_HEIGHT-1));
  return current_timing;
}
#endif
#endif
