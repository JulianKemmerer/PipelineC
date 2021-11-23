// Is it legal to call this Pong?
// You know whats up with this paddle and ball game.

#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

// Access to board buttons
#include "../buttons/buttons.c"
// Top level IO wiring + VGA resolution timing logic+types
#include "vga_pmod.c"
// Helper types+funcs for rectangles
#include "rect.h"

// Paddle dimensions+color
#define PADDLE_WIDTH (FRAME_WIDTH/50)
#define PADDLE_HEIGHT (FRAME_HEIGHT/8)
#define PADDLE_L_RED 0xF
#define PADDLE_L_GREEN 0xF
#define PADDLE_L_BLUE 0xF
#define PADDLE_L_X_POS PADDLE_WIDTH
#define PADDLE_R_RED 0xF
#define PADDLE_R_GREEN 0xF
#define PADDLE_R_BLUE 0xF
#define PADDLE_R_X_POS (FRAME_WIDTH - (2*PADDLE_WIDTH))
#define PADDLE_VEL_INC 1
#define BTN_POS_INC 2

// Ball dimensions+color
#define BALL_WIDTH (FRAME_WIDTH/50)
#define BALL_HEIGHT BALL_WIDTH
#define BALL_RED 0xF
#define BALL_GREEN 0xF
#define BALL_BLUE 0xF

// Is the ball in left goal?
uint1_t ball_in_l_goal(rect_animated_t ball)
{
  return (ball.vel_x_dir==LEFT) & (ball.rect.pos.x < (PADDLE_L_X_POS+PADDLE_WIDTH));
}

// Is the ball in right goal?
uint1_t ball_in_r_goal(rect_animated_t ball)
{
  return (ball.vel_x_dir==RIGHT) & ((ball.rect.pos.x + BALL_WIDTH) > PADDLE_R_X_POS);
}

// Ball hit top of frame?
uint1_t ball_hit_roof(rect_animated_t ball)
{
  return (ball.vel_y_dir==UP) & (ball.rect.pos.y == 0);
}

// Ball hit bottom of frame?
uint1_t ball_hit_floor(rect_animated_t ball)
{
  return (ball.vel_y_dir==DOWN) & (ball.rect.pos.y >= (FRAME_HEIGHT-BALL_HEIGHT));
}

// How to adjust speed from user hit
vga_pos_t ball_paddle_inc_vel(vga_pos_t vel)
{
  // Add velocity to ball from whack
  if(vel.x > 0)
  {
    vel.x += PADDLE_VEL_INC;
  }
  if(vel.y > 0)
  {
    vel.y += PADDLE_VEL_INC;
  }
  return vel;
}

// User input buttons
typedef struct user_input_t
{
  uint1_t paddle_r_up;
  uint1_t paddle_r_down;
  uint1_t paddle_l_up;
  uint1_t paddle_l_down;
}user_input_t;
user_input_t get_user_input()
{
  uint4_t btns;
  WIRE_READ(uint4_t, btns, buttons)
  user_input_t i;
  // Select which buttons are up and down
  i.paddle_r_up = btns >> 0;
  i.paddle_r_down = btns >> 1;
  i.paddle_l_up = btns >> 2;
  i.paddle_l_down = btns >> 3;
  return i;
}

typedef struct game_state_t
{
  rect_animated_t ball;
  rect_animated_t lpaddle;
  rect_animated_t rpaddle;
}game_state_t;

// Update the game state each clock (returns current state)
game_state_t do_animation(uint1_t end_of_frame, user_input_t user_input)
{
  // State registers
  static game_state_t state;
  // Wires for output and next state values
  game_state_t rv = state; // Output register
  game_state_t next_state = state;
  // Reset register and reset values
  static uint1_t reset = 1;
  game_state_t reset_state;
  // Ball in the middle
  reset_state.ball.rect.dim.x = BALL_WIDTH;
  reset_state.ball.rect.dim.y = BALL_HEIGHT;
  reset_state.ball.rect.pos.x = (FRAME_WIDTH/2) - (BALL_WIDTH/2);
  reset_state.ball.rect.pos.y = (FRAME_HEIGHT/2) - (BALL_HEIGHT/2);
  reset_state.ball.vel_x_dir = LEFT;
  reset_state.ball.vel.x = 1;
  reset_state.ball.vel_y_dir = UP;
  reset_state.ball.vel.y = 1;
  // Left paddle
  reset_state.lpaddle.rect.dim.x = PADDLE_WIDTH;
  reset_state.lpaddle.rect.dim.y = PADDLE_HEIGHT;
  reset_state.lpaddle.rect.pos.x = PADDLE_L_X_POS;
  reset_state.lpaddle.rect.pos.y = (FRAME_HEIGHT/2) - (PADDLE_HEIGHT/2);
  // Right paddle
  reset_state.rpaddle.rect.dim.x = PADDLE_WIDTH;
  reset_state.rpaddle.rect.dim.y = PADDLE_HEIGHT;
  reset_state.rpaddle.rect.pos.x = PADDLE_R_X_POS;
  reset_state.rpaddle.rect.pos.y = (FRAME_HEIGHT/2) - (PADDLE_HEIGHT/2);
    
  // Only do animation update, not every clock, but on every frame
  if(end_of_frame)
  {
    // Default animation of moving rectangles (no collision checking)
    next_state.ball = rect_move(state.ball);
    next_state.lpaddle = rect_move(state.lpaddle);
    next_state.rpaddle = rect_move(state.rpaddle);
    
    // Ball top and bottom bouncing
    // Stop ball, reverse direction
    if(ball_hit_roof(state.ball))
    {
      next_state.ball.rect.pos = state.ball.rect.pos;
      next_state.ball.vel_y_dir = DOWN;
    }
    else if(ball_hit_floor(state.ball))
    {
      next_state.ball.rect.pos = state.ball.rect.pos;
      next_state.ball.vel_y_dir = UP;
    }
    
    // Ball passing goal lines?
    if(ball_in_l_goal(state.ball))
    {
      if(rects_collide(state.ball.rect, state.lpaddle.rect))
      {
        // Bounce off left paddle
        next_state.ball.rect.pos = state.ball.rect.pos;
        next_state.ball.vel_x_dir = RIGHT;
        next_state.ball.vel = ball_paddle_inc_vel(state.ball.vel);
      }
      else
      {
        // Left scored on by right
        reset = 1; // Start over
        // TODO keep+display score
      }
    }
    else if(ball_in_r_goal(state.ball)) 
    {
      if(rects_collide(state.ball.rect, state.rpaddle.rect))
      {
        // Bounce off right paddle
        next_state.ball.rect.pos = state.ball.rect.pos;
        next_state.ball.vel_x_dir = LEFT;
        next_state.ball.vel = ball_paddle_inc_vel(state.ball.vel);
      }
      else
      {
        // Right scored on by left
        reset = 1; // Start over
        // TODO keep+display score
      }
    }    
    
    // Move paddles per user input, with screen limits
    // Right
    if(user_input.paddle_r_up & !user_input.paddle_r_down)
    {
      if(state.rpaddle.rect.pos.y >= BTN_POS_INC)
      {
        next_state.rpaddle.rect.pos.y = state.rpaddle.rect.pos.y - BTN_POS_INC;
      }
    }
    else if(user_input.paddle_r_down & !user_input.paddle_r_up)
    {
      if((state.rpaddle.rect.pos.y + BTN_POS_INC) <= (FRAME_HEIGHT-PADDLE_HEIGHT))
      {
        next_state.rpaddle.rect.pos.y = state.rpaddle.rect.pos.y + BTN_POS_INC;
      }
    }
    // Left
    if(user_input.paddle_l_up & !user_input.paddle_l_down)
    {
      if(state.lpaddle.rect.pos.y >= BTN_POS_INC)
      {
        next_state.lpaddle.rect.pos.y = state.lpaddle.rect.pos.y - BTN_POS_INC;
      }
    }
    else if(user_input.paddle_l_down & !user_input.paddle_l_up)
    {
      if((state.lpaddle.rect.pos.y + BTN_POS_INC) <= (FRAME_HEIGHT-PADDLE_HEIGHT))
      {
        next_state.lpaddle.rect.pos.y = state.lpaddle.rect.pos.y + BTN_POS_INC;
      }
    }
  }
  
  // Keep next state for next iter, do resets
  state = next_state;
  if(reset)
  {
    state = reset_state;
  }
  reset = 0;
  
  // Return output register value
  return rv;
}

// Logic for coloring pixels
color_12b_t get_pixel_color(
  vga_pos_t pos, 
  game_state_t state)
{
  // Default zeros/black background
  color_12b_t c;
  
  // Left paddle?
  if(rect_contains(state.lpaddle.rect, pos))
  {
    c.red = PADDLE_L_RED;
    c.green = PADDLE_L_GREEN;
    c.blue = PADDLE_L_BLUE;
  }
  // Right paddle?
  else if(rect_contains(state.rpaddle.rect, pos))
  {
    c.red = PADDLE_R_RED;
    c.green = PADDLE_R_GREEN;
    c.blue = PADDLE_R_BLUE;
  }
  // Ball?
  else if(rect_contains(state.ball.rect, pos))
  {
    c.red = BALL_RED;
    c.green = BALL_GREEN;
    c.blue = BALL_BLUE;
  }
  
  return c;
}

// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Input buttons from user
  user_input_t user_input = get_user_input();
  
  // Do animation of ball and paddles
  game_state_t curr_state = do_animation(vga_signals.end_of_frame, user_input);
  
  // Get pixel color at x,y
  color_12b_t color = get_pixel_color(vga_signals.pos, curr_state);
  
  // Drive output signals/registers
  vga_pmod_register_outputs(vga_signals, color);
}
