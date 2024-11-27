// Logic for moving image rectangle that changes color

typedef struct rect_t
{
  vga_pos_t pos;
  uint1_t x_dir;
  uint1_t y_dir;
  uint25_t counter;
  uint3_t color_mode;
}rect_t;

// Image to use
#include "pipelinec_color.h" // See make_image_files.py
// Rect should be small enough
// to bounce a little on smallest 640x480 screens
#define RECT_W pipelinec_color_W
#define RECT_H pipelinec_color_H
#define RECT_X_MAX (FRAME_WIDTH - RECT_W)
#define RECT_Y_MAX (FRAME_HEIGHT - RECT_H)
#define RECT_X_MIN 0
#define RECT_Y_MIN 0
#define RECT_CLK_DIV 1000000 //MAX=(2^25 - 1)
// How many modes of 'color swapping'
#define NUM_COLOR_MODES 6
// Init consts for demo
#define X_UNIT ((FRAME_WIDTH-RECT_W)/NUM_IMAGES)
#define Y_UNIT RECT_H
#define RECT_INIT(rect_init) \
rect_init[0].pos.x = 0*X_UNIT; \
rect_init[0].pos.y = 1*Y_UNIT; \
rect_init[0].x_dir = 1; \
rect_init[0].y_dir = 0; \
rect_init[0].color_mode = 0;\
\
rect_init[1].pos.x = 1*X_UNIT; \
rect_init[1].pos.y = FRAME_HEIGHT - (2*Y_UNIT);\
rect_init[1].x_dir = 1; \
rect_init[1].y_dir = 0;\
rect_init[1].color_mode = 1;\
\
rect_init[2].pos.x = 2*X_UNIT; \
rect_init[2].pos.y = 2*Y_UNIT; \
rect_init[2].x_dir = 0; \
rect_init[2].y_dir = 1; \
rect_init[2].color_mode = 2;\
\
rect_init[3].pos.x = 3*X_UNIT;\
rect_init[3].pos.y = FRAME_HEIGHT - (3*Y_UNIT);\
rect_init[3].x_dir = 1; \
rect_init[3].y_dir = 1; \
rect_init[3].color_mode = 3;\
\
rect_init[4].pos.x = 4*X_UNIT; \
rect_init[4].pos.y = 3*Y_UNIT; \
rect_init[4].x_dir = 1; \
rect_init[4].y_dir = 1; \
rect_init[4].color_mode = 4;\
\
rect_init[5].pos.x = 5*X_UNIT; \
rect_init[5].pos.y = FRAME_HEIGHT - (4*Y_UNIT);\
rect_init[5].x_dir = 0; \
rect_init[5].y_dir = 0; \
rect_init[5].color_mode = 5;

// Is point inside rect?
uint1_t rect_contains(rect_t rect, vga_pos_t pos)
{
  uint1_t rv;
  if(((pos.x >= rect.pos.x) & (pos.x < (rect.pos.x + RECT_W))) &
     ((pos.y >= rect.pos.y) & (pos.y < (rect.pos.y + RECT_H))))
  {
    rv = 1;
  }
  return rv;
}

// Absolute point to relative point in rect
vga_pos_t rect_rel_pos(rect_t rect, vga_pos_t pos)
{
  vga_pos_t rel_pos;
  rel_pos.x = pos.x - rect.pos.x;
  rel_pos.y = pos.y - rect.pos.y;
  return rel_pos;
}

// Logic for coloring the rect given rel pos inside rect
color_12b_t rect_color(vga_pos_t rel_pos, uint3_t color_mode)
{
  // Func from from pipelinec_color.h
  uint32_t pixel_addr = pipelinec_color_pixel_addr(rel_pos);

  // In pipelineable luts, too slow for pycparser (and probabaly rest of PipelineC too)
  //color_12b_t pipelinec_color[pipelinec_color_W*pipelinec_color_H];
  // return pipelinec_color[pixel_addr]; 
  
  // As synthesis tool inferred (LUT)RAM
  pipelinec_color_DECL // Macro from pipelinec_color.h
  color_12b_t unused_write_data;
  // (LUT)RAM template function
  color_12b_t c = pipelinec_color_RAM_SP_RF_0(pixel_addr, unused_write_data, 0);
  
  // Apply color mode selection
  uint4_t color_mode_values[NUM_COLOR_MODES][3];
  // (hacky re-decl to support init list syntax)
  uint4_t color_values[3];
  uint4_t color_values[3] = {c.r, c.g, c.b}; color_mode_values[0] = color_values;
  uint4_t color_values[3] = {c.b, c.g, c.r}; color_mode_values[1] = color_values;
  uint4_t color_values[3] = {c.b, c.r, c.g}; color_mode_values[2] = color_values;
  uint4_t color_values[3] = {c.g, c.b, c.r}; color_mode_values[3] = color_values;
  uint4_t color_values[3] = {c.g, c.r, c.b}; color_mode_values[4] = color_values;
  uint4_t color_values[3] = {c.r, c.b, c.g}; color_mode_values[5] = color_values;
  color_values = color_mode_values[color_mode];
  color_12b_t rv_color;
  rv_color.r = color_values[0];
  rv_color.g = color_values[1];
  rv_color.b = color_values[2];
  return rv_color;
}

// Logic to make rectangle move
rect_t rect_move(rect_t reset_state)
{  
  static rect_t state;
  static uint1_t reset = 1;
  
  rect_t rv = state;
  
  // Only update position when animation speed says so
  uint1_t update_rect;
  update_rect = 0;
  if(state.counter == (RECT_CLK_DIV - 1))
  {
    update_rect = 1;
  }
 
  // Save rect x,y for comparing during direction logic
  uint12_t rect_x_tmp;
  uint12_t rect_y_tmp;
  rect_x_tmp = state.pos.x;
  rect_y_tmp = state.pos.y;
  
  // Default movement logic
  if(update_rect == 1)
  {
    if(state.x_dir == 1)
    {
      state.pos.x = state.pos.x + 1;
    }
    else
    {
      state.pos.x = state.pos.x - 1;
    }
    if(state.y_dir == 1)
    {
      state.pos.y = state.pos.y + 1;
    }
    else
    {
      state.pos.y = state.pos.y - 1;
    }
  }      
  
  // Collision and change direction
  if(update_rect == 1)
  {
    uint1_t colliding;
    if(((state.x_dir == 1) & (rect_x_tmp == RECT_X_MAX - 1)) | ((state.x_dir == 0) & (rect_x_tmp == RECT_X_MIN + 1)))
    {
      state.x_dir = !(state.x_dir);
      colliding = 1;
    }
    if(((state.y_dir == 1) & (rect_y_tmp == RECT_Y_MAX - 1)) | ((state.y_dir == 0) & (rect_y_tmp == RECT_Y_MIN + 1))) 
    {
      state.y_dir = !(state.y_dir);
      colliding = 1;
    }
    // Change color on collision
    if(colliding)
    {
      if(state.color_mode==(NUM_COLOR_MODES-1))
      {
        state.color_mode = 0;
      }
      else
      {
        state.color_mode += 1;
      }
    }
  }

  // Generic counter for animating motion over time
  if(state.counter == (RECT_CLK_DIV - 1))
  {
    state.counter = 0;
  }
  else
  {
    state.counter = state.counter + 1;     
  }
  
  // Reset logic
  if(reset)
  {
    state = reset_state;
  }
  // Power on reset in this case
  reset = 0;
  
  return rv;
}
