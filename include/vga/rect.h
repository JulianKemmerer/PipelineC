typedef struct rect_t
{
  vga_pos_t pos;
  vga_pos_t dim;
} rect_t;

// Is point inside rect?
inline uint1_t rect_contains(rect_t rect, vga_pos_t pos)
{
  uint1_t rv = 0;
  if(((pos.x >= rect.pos.x) && (pos.x < (rect.pos.x + rect.dim.x))) &&
     ((pos.y >= rect.pos.y) && (pos.y < (rect.pos.y + rect.dim.y))))
  {
    rv = 1;
  }
  return rv;
}

// Absolute point to relative point in rect
inline vga_pos_t rect_rel_pos(rect_t rect, vga_pos_t pos)
{
  vga_pos_t rel_pos;
  rel_pos.x = pos.x - rect.pos.x;
  rel_pos.y = pos.y - rect.pos.y;
  return rel_pos;
}

// Do two rectangles collide?
inline uint1_t rects_collide(rect_t r0, rect_t r1)
{
  uint12_t r0_left = r0.pos.x;
  uint12_t r0_right = r0.pos.x + r0.dim.x;
  uint12_t r0_top = r0.pos.y;
  uint12_t r0_bottom = r0.pos.y + r0.dim.y;
  //
  uint12_t r1_left = r1.pos.x;
  uint12_t r1_right = r1.pos.x + r1.dim.x;
  uint12_t r1_top = r1.pos.y;
  uint12_t r1_bottom = r1.pos.y + r1.dim.y;
  
  return !((r0_right < r1_left) | (r0_bottom < r1_top) | (r0_left > r1_right) | (r0_top > r1_bottom));
}

// A rectangle moving with velocity in certain direction
typedef struct rect_animated_t
{
  rect_t rect;
  vga_pos_t vel;
  uint1_t vel_x_dir;
  uint1_t vel_y_dir;
} rect_animated_t;
#define LEFT 0
#define RIGHT 1
#define UP 0
#define DOWN 1

// How rectangle moves, with bounds checks going negative since using unsigned numbers
inline rect_animated_t rect_move(rect_animated_t state)
{  
  if(state.vel_x_dir == RIGHT)
  {
    state.rect.pos.x = state.rect.pos.x + state.vel.x;
  }
  else
  {
    if(state.rect.pos.x > state.vel.x)
    {
      state.rect.pos.x = state.rect.pos.x - state.vel.x;
    }
    else
    {
      state.rect.pos.x = 0;
    }
  }
  if(state.vel_y_dir == DOWN)
  {
    state.rect.pos.y = state.rect.pos.y + state.vel.y;
  }
  else
  {
    if(state.rect.pos.y > state.vel.y)
    {
      state.rect.pos.y = state.rect.pos.y - state.vel.y;
    }
    else
    {
      state.rect.pos.y = 0;
    }
  }
  return state;
}
