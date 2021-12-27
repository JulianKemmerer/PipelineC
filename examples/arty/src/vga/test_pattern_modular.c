// Organized and modular version of test_pattern.c
#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#endif

// See top level IO wiring in
#include "vga_pmod.c"

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
    if((box_x_dir == 1 and (box_x_tmp == BOX_X_MAX - 1)) | (box_x_dir == 0 and (box_x_tmp == BOX_X_MIN + 1)))
    {
      box_x_dir = !(box_x_dir);
    }
    if((box_y_dir == 1 and (box_y_tmp == BOX_Y_MAX - 1)) | (box_y_dir == 0 and (box_y_tmp == BOX_Y_MIN + 1))) 
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
inline color_12b_t get_pixel_color(uint1_t active, vga_pos_t pos, vga_pos_t box_pos)
{
  uint4_t vga_red;
  uint4_t vga_green;
  uint4_t vga_blue;
  
  uint1_t pixel_in_box;
  pixel_in_box = 0;
  if(((pos.x >= box_pos.x) and (pos.x < (box_pos.x + BOX_WIDTH))) and
     ((pos.y >= box_pos.y) and (pos.y < (box_pos.y + BOX_WIDTH))))
  {
    pixel_in_box = 1;
  }  
  
  vga_red = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and uint12_8_8(pos.x) == 1))
  {
    vga_red = uint12_5_2(pos.x);
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1)))
  {
    vga_red = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1))))
  {
    vga_red = 0b1111;
  }
     
  vga_blue = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and  uint12_6_6(pos.x) == 1))
  {
    vga_blue = uint12_5_2(pos.x); 
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1)))
  {
    vga_blue = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1))))
  {
    vga_blue = 0b1111;
  }                      
                         
  vga_green = 0;
  if(active == 1 and ((pos.x < 512 and pos.y < 256) and uint12_7_7(pos.x) == 1))
  {
    vga_green = uint12_5_2(pos.x); 
  }
  else if(active == 1 and ((pos.x < 512 and !(pos.y < 256)) and !(pixel_in_box == 1))) 
  {
    vga_green = 0b1111;
  }
  else if(active == 1 and ((!(pos.x < 512) and (uint12_8_8(pos.y) == 1 and uint12_3_3(pos.x) == 1)) |
           (!(pos.x < 512) and (uint12_8_8(pos.y) == 0 and uint12_3_3(pos.y) == 1)))) 
  {
    vga_green = 0b1111;
  }
  
  color_12b_t c;
  c.r = vga_red;
  c.g = vga_green;
  c.b = vga_blue;
  return c;
}

// The test pattern driving entity
// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Logic to make a box move
  vga_pos_t box_pos = moving_box_logic();
  
  // Color pixel at x,y 
  color_12b_t color = get_pixel_color(vga_signals.active, vga_signals.pos, box_pos);
  
  // Drive output signals/registers
  pixel_t pixel;
  pixel.r = color.r << 4;
  pixel.g = color.g << 4;
  pixel.b = color.b << 4;
  pmod_register_outputs(vga_signals, pixel);
}
