// Simple design essentially copy-pasting the VHDL VGA test pattern design from Digilent
// https://github.com/Digilent/Arty-Pmod-VGA/blob/master/src/hdl/top.vhd
// https://digilent.com/reference/learn/programmable-logic/tutorials/arty-pmod-vga-demo/start
// (test pattern color order does not match exactly but seems to be pmod board revision thing?
// not worried about it at the moment since later experiments seem to have colors working fine)
// Was also slightly modified to output 24bpp color (for DVI pmod) (doesnt look exactly like Digilent)
#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#endif
#include "pixel.h"

// Moving box module
#define BOX_WIDTH 8
#define BOX_CLK_DIV 1000000 //MAX=(2^25 - 1)
#define BOX_X_MAX (512 - BOX_WIDTH)
#define BOX_Y_MAX (FRAME_HEIGHT - BOX_WIDTH)
#define BOX_X_MIN 0
#define BOX_Y_MIN 256
#define BOX_X_INIT 0
#define BOX_Y_INIT 400
inline vga_pos_t moving_box_logic()
{  
  static uint12_t box_x_reg = BOX_X_INIT;
  static uint1_t box_x_dir = 1;
  static uint12_t box_y_reg = BOX_Y_INIT;
  static uint1_t box_y_dir = 1;
  static uint25_t box_cntr_reg;
  
  vga_pos_t box_pos;
  box_pos.x = box_x_reg;
  box_pos.y = box_y_reg;
  
  uint1_t update_box;
  update_box = 0;
  if(box_cntr_reg == (BOX_CLK_DIV - 1))
  {
    update_box = 1;
  }
 
  // Save box x,y for comparing during direction logic
  uint12_t box_x_tmp;
  uint12_t box_y_tmp;
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
    if((box_x_dir == 1 && (box_x_tmp == BOX_X_MAX - 1)) | (box_x_dir == 0 && (box_x_tmp == BOX_X_MIN + 1)))
    {
      box_x_dir = !(box_x_dir);
    }
    if((box_y_dir == 1 && (box_y_tmp == BOX_Y_MAX - 1)) | (box_y_dir == 0 && (box_y_tmp == BOX_Y_MIN + 1))) 
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
  
  return box_pos;
}

// Logic for coloring pixels
inline pixel_t get_pixel_color(uint1_t active, vga_pos_t pos, vga_pos_t box_pos)
{
  uint8_t vga_red;
  uint8_t vga_green;
  uint8_t vga_blue;
  
  uint1_t pixel_in_box;
  pixel_in_box = 0;
  if(((pos.x >= box_pos.x) && (pos.x < (box_pos.x + BOX_WIDTH))) &&
     ((pos.y >= box_pos.y) && (pos.y < (box_pos.y + BOX_WIDTH))))
  {
    pixel_in_box = 1;
  }  
  
  vga_red = 0;
  if(active == 1 && ((pos.x < 512 && pos.y < 256) && uint12_8_8(pos.x) == 1))
  {
    vga_red = uint12_7_0(pos.x);
  }
  else if(active == 1 && ((pos.x < 512 && !(pos.y < 256)) && !(pixel_in_box == 1)))
  {
    vga_red = 0b11111111;
  }
  else if(active == 1 && ((!(pos.x < 512) && (uint12_8_8(pos.y) == 1 && uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) && (uint12_8_8(pos.y) == 0 && uint12_3_3(pos.y) == 1))))
  {
    vga_red = 0b11111111;
  }
     
  vga_blue = 0;
  if(active == 1 && ((pos.x < 512 && pos.y < 256) &&  uint12_6_6(pos.x) == 1))
  {
    vga_blue = uint12_7_0(pos.x); 
  }
  else if(active == 1 && ((pos.x < 512 && !(pos.y < 256)) && !(pixel_in_box == 1)))
  {
    vga_blue = 0b11111111;
  }
  else if(active == 1 && ((!(pos.x < 512) && (uint12_8_8(pos.y) == 1 && uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) && (uint12_8_8(pos.y) == 0 && uint12_3_3(pos.y) == 1))))
  {
    vga_blue = 0b11111111;
  }                      
                         
  vga_green = 0;
  if(active == 1 && ((pos.x < 512 && pos.y < 256) && uint12_7_7(pos.x) == 1))
  {
    vga_green = uint12_7_0(pos.x); 
  }
  else if(active == 1 && ((pos.x < 512 && !(pos.y < 256)) && !(pixel_in_box == 1))) 
  {
    vga_green = 0b11111111;
  }
  else if(active == 1 && ((!(pos.x < 512) && (uint12_8_8(pos.y) == 1 && uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) && (uint12_8_8(pos.y) == 0 && uint12_3_3(pos.y) == 1)))) 
  {
    vga_green = 0b11111111;
  }
  
  pixel_t p;
  p.r = vga_red;
  p.g = vga_green;
  p.b = vga_blue;
  return p;
}

/* Alternative test of RGB range
inline pixel_t get_pixel_color(uint1_t active, vga_pos_t pos, vga_pos_t box_pos)
{
  pixel_t p;

  if((pos.y >= ((0*FRAME_HEIGHT)/3)) & (pos.y < ((1*FRAME_HEIGHT)/3)))
  {
    p.r = pos.x;
  }
  else if((pos.y >= ((1*FRAME_HEIGHT)/3)) & (pos.y < ((2*FRAME_HEIGHT)/3)))
  {
    p.g = pos.x;
  }
  else if((pos.y >= ((2*FRAME_HEIGHT)/3)) & (pos.y < ((3*FRAME_HEIGHT)/3)))
  {
    p.b = pos.x;
  }

  return p;
}*/

typedef struct test_pattern_out_t{
  vga_signals_t vga_signals;
  pixel_t pixel;
}test_pattern_out_t;
test_pattern_out_t test_pattern(vga_signals_t vga_signals){
  // Logic to make a box move
  vga_pos_t box_pos = moving_box_logic();
  
  // Color pixel at x,y 
  pixel_t pixel = get_pixel_color(vga_signals.active, vga_signals.pos, box_pos);

  test_pattern_out_t o;
  o.vga_signals = vga_signals;
  o.pixel = pixel;
  return o;
}

