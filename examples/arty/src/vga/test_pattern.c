#include "compiler.h"
#include "uintN_t.h"

// Simple design mimicing the VGA test pattern design from Digilent
// https://digilent.com/reference/learn/programmable-logic/tutorials/arty-pmod-vga-demo/start
// https://github.com/Digilent/Arty-Pmod-VGA/blob/master/src/hdl/top.vhd

// See top level IO wiring in
#include "vga_pmod.c"

////***640x480@60Hz***//  Requires 25 MHz clock
//#define PIXEL_CLK_MHZ 25.0
//#define FRAME_WIDTH 640
//#define FRAME_HEIGHT 480

//#define H_FP 16 //H front porch width (pixels)
//#define H_PW 96 //H sync pulse width (pixels)
//#define H_MAX 800 //H total period (pixels)

//#define V_FP 10 //V front porch width (lines)
//#define V_PW 2 //V sync pulse width (lines)
//#define V_MAX 525 //V total period (lines)

//#define H_POL 0
//#define V_POL 0

////***800x600@60Hz***//  Requires 40 MHz clock
//#define PIXEL_CLK_MHZ 40.0
//#define FRAME_WIDTH 800
//#define FRAME_HEIGHT 600
//
//#define H_FP 40 //H front porch width (pixels)
//#define H_PW 128 //H sync pulse width (pixels)
//#define H_MAX 1056 //H total period (pixels)
//
//#define V_FP 1 //V front porch width (lines)
//#define V_PW 4 //V sync pulse width (lines)
//#define V_MAX 628 //V total period (lines)
//
//#define H_POL 1
//#define V_POL 1

////***1280x720@60Hz***// Requires 74.25 MHz clock
//#define PIXEL_CLK_MHZ 74.25
//#define FRAME_WIDTH 1280
//#define FRAME_HEIGHT 720
//
//#define H_FP 110 //H front porch width (pixels)
//#define H_PW 40 //H sync pulse width (pixels)
//#define H_MAX 1650 //H total period (pixels)
//
//#define V_FP 5 //V front porch width (lines)
//#define V_PW 5 //V sync pulse width (lines)
//#define V_MAX 750 //V total period (lines)
//
//#define H_POL 1
//#define V_POL 1

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
#define PIXEL_CLK_MHZ 148.5
#define FRAME_WIDTH 1920
#define FRAME_HEIGHT 1080

#define H_FP 88 //H front porch width (pixels)
#define H_PW 44 //H sync pulse width (pixels)
#define H_MAX 2200 //H total period (pixels)

#define V_FP 4 //V front porch width (lines)
#define V_PW 5 //V sync pulse width (lines)
#define V_MAX 1125 //V total period (lines)

#define H_POL 1
#define V_POL 1

//Moving Box constants
#define BOX_WIDTH 8
#define BOX_CLK_DIV 1000000 //MAX=(2^25 - 1)

#define BOX_X_MAX (512 - BOX_WIDTH)
#define BOX_Y_MAX (FRAME_HEIGHT - BOX_WIDTH)

#define BOX_X_MIN 0
#define BOX_Y_MIN 256

#define BOX_X_INIT 0
#define BOX_Y_INIT 400

// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
// The test pattern driving entity
void app()
{
  // Wires and registers
  
  uint1_t active;

  static uint12_t h_cntr_reg;
  static uint12_t v_cntr_reg;

  static uint1_t h_sync_reg = !H_POL;
  static uint1_t v_sync_reg = !V_POL;

  static uint1_t h_sync_dly_reg = !H_POL;
  static uint1_t v_sync_dly_reg = !V_POL;

  static uint4_t vga_red_reg;
  static uint4_t vga_green_reg;
  static uint4_t vga_blue_reg;

  uint4_t vga_red;
  uint4_t vga_green;
  uint4_t vga_blue;

  static uint12_t box_x_reg = BOX_X_INIT;
  static uint1_t box_x_dir = 1;
  static uint12_t box_y_reg = BOX_Y_INIT;
  static uint1_t box_y_dir = 1;
  static uint25_t box_cntr_reg;
  uint12_t box_x_tmp;
  uint12_t box_y_tmp;

  uint1_t update_box;
  uint1_t pixel_in_box;

  // Connect to VGA PMOD board IO via app_to_vga wire
  app_to_vga_t o;
  o.hs = h_sync_dly_reg;
  o.vs = v_sync_dly_reg;
  o.r = vga_red_reg;
  o.g = vga_green_reg;
  o.b = vga_blue_reg;
  WIRE_WRITE(app_to_vga_t, app_to_vga, o)
  
  //----------------------------------------------------
  //-----         MOVING BOX LOGIC                //----
  //----------------------------------------------------
  
  update_box = 0;
  if(box_cntr_reg == (BOX_CLK_DIV - 1))
  {
    update_box = 1;
  }
 
  pixel_in_box = 0;
  if(((h_cntr_reg >= box_x_reg) & (h_cntr_reg < (box_x_reg + BOX_WIDTH))) &
     ((v_cntr_reg >= box_y_reg) & (v_cntr_reg < (box_y_reg + BOX_WIDTH))))
  {
    pixel_in_box = 1;
  }
  
  // Save box x,y for comparing during direction logic
  box_x_tmp = box_x_reg;
  box_y_tmp = box_y_reg;
  
  if(update_box == 1)
  {
    if(box_x_dir == 1)
    {
      box_x_reg = box_x_reg + 1;
    }
    else
    {
      box_x_reg = box_x_reg - 1;
    }
    if(box_y_dir == 1)
    {
      box_y_reg = box_y_reg + 1;
    }
    else
    {
      box_y_reg = box_y_reg - 1;
    }
  }      
                  
  if(update_box == 1)
  {
    if((box_x_dir == 1 & (box_x_tmp == BOX_X_MAX - 1)) | (box_x_dir == 0 & (box_x_tmp == BOX_X_MIN + 1)))
    {
      box_x_dir = !(box_x_dir);
    }
    if((box_y_dir == 1 & (box_y_tmp == BOX_Y_MAX - 1)) | (box_y_dir == 0 & (box_y_tmp == BOX_Y_MIN + 1))) 
    {
      box_y_dir = !(box_y_dir);
    }
  }

  if(box_cntr_reg == (BOX_CLK_DIV - 1))
  {
    box_cntr_reg = 0;
  }
  else
  {
    box_cntr_reg = box_cntr_reg + 1;     
  }
  
  //--------------------------------------------------
  //-----         TEST PATTERN LOGIC           //-----
  //--------------------------------------------------
  
  active = 0;
  if((h_cntr_reg < FRAME_WIDTH) & (v_cntr_reg < FRAME_HEIGHT))
  {
    active = 1;
  }
  
  vga_red = 0;
  if(active == 1 & ((h_cntr_reg < 512 & v_cntr_reg < 256) & uint12_8_8(h_cntr_reg) == 1))
  {
    vga_red = uint12_5_2(h_cntr_reg);
  }
  else if(active == 1 & ((h_cntr_reg < 512 & !(v_cntr_reg < 256)) & !(pixel_in_box == 1)))
  {
    vga_red = 0b1111;
  }
  else if(active == 1 & ((!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 1 & uint12_3_3(h_cntr_reg) == 1)) |
           (!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 0 & uint12_3_3(v_cntr_reg) == 1))))
  {
    vga_red = 0b1111;
  }
     
  vga_blue = 0;
  if(active == 1 & ((h_cntr_reg < 512 & v_cntr_reg < 256) &  uint12_6_6(h_cntr_reg) == 1))
  {
    vga_blue = uint12_5_2(h_cntr_reg); 
  }
  else if(active == 1 & ((h_cntr_reg < 512 & !(v_cntr_reg < 256)) & !(pixel_in_box == 1)))
  {
    vga_blue = 0b1111;
  }
  else if(active == 1 & ((!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 1 & uint12_3_3(h_cntr_reg) == 1)) |
           (!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 0 & uint12_3_3(v_cntr_reg) == 1))))
  {
    vga_blue = 0b1111;
  }                      
                         
  vga_green = 0;
  if(active == 1 & ((h_cntr_reg < 512 & v_cntr_reg < 256) & uint12_7_7(h_cntr_reg) == 1))
  {
    vga_green = uint12_5_2(h_cntr_reg); 
  }
  else if(active == 1 & ((h_cntr_reg < 512 & !(v_cntr_reg < 256)) & !(pixel_in_box == 1))) 
  {
    vga_green = 0b1111;
  }
  else if(active == 1 & ((!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 1 & uint12_3_3(h_cntr_reg) == 1)) |
           (!(h_cntr_reg < 512) & (uint12_8_8(v_cntr_reg) == 0 & uint12_3_3(v_cntr_reg) == 1)))) 
  {
    vga_green = 0b1111;
  }
                
  //----------------------------------------------------
  //-----         SYNC GENERATION                 //----
  //----------------------------------------------------
  
  v_sync_dly_reg = v_sync_reg;
  h_sync_dly_reg = h_sync_reg;
 
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

  vga_red_reg = vga_red;
  vga_green_reg = vga_green;
  vga_blue_reg = vga_blue;
}



