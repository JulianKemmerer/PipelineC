// Is it legal to call this Pong?
// You know whats up with this paddle and ball game.

#ifdef __PIPELINEC__
#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"
// Access to board buttons
#include "../buttons/buttons.c"
// Top level IO wiring + VGA resolution timing logic+types
#include "vga_pmod.c"
#endif

// Helper types+funcs for rectangles
#include "rect.h"

// Paddle dimensions+color
#define PADDLE_WIDTH (FRAME_WIDTH/50)
#define PADDLE_HEIGHT (FRAME_HEIGHT/8)
#define PADDLE_L_RED 0xFF
#define PADDLE_L_GREEN 0xFF
#define PADDLE_L_BLUE 0xFF
#define PADDLE_L_X_POS PADDLE_WIDTH
#define PADDLE_R_RED 0xFF
#define PADDLE_R_GREEN 0xFF
#define PADDLE_R_BLUE 0xFF
#define PADDLE_R_X_POS (FRAME_WIDTH - (2*PADDLE_WIDTH))
#define PADDLE_VEL_MULT 1.1
#define BTN_POS_INC 2

// Ball dimensions+color
#define BALL_WIDTH (FRAME_WIDTH/50)
#define BALL_HEIGHT BALL_WIDTH
#define BALL_RED 0xFF
#define BALL_GREEN 0xFF
#define BALL_BLUE 0xFF

// User input buttons
typedef struct user_input_t
{
  uint1_t paddle_r_up;
  uint1_t paddle_r_down;
  uint1_t paddle_l_up;
  uint1_t paddle_l_down;
}user_input_t;

inline user_input_t get_user_input()
{
  // Read buttons wire/board IO port
  uint4_t btns;
  user_input_t i;
  // TODO user IO for running as C code
  // For now only exists in hardware
  #ifdef __PIPELINEC__
  WIRE_READ(uint4_t, btns, buttons)
  // Select which buttons are up and down
  i.paddle_r_up = btns >> 0;
  i.paddle_r_down = btns >> 1;
  i.paddle_l_up = btns >> 2;
  i.paddle_l_down = btns >> 3;
  #endif
  return i;
}

// State of objects in the game
typedef struct game_state_t
{
  rect_animated_t ball;
  rect_animated_t lpaddle;
  rect_animated_t rpaddle;
}game_state_t;

// Logic for coloring pixel given state
inline pixel_t render_pixel(vga_pos_t pos, game_state_t state)
{
  // Default zeros/black background
  pixel_t c;
  c.a = 0;
  c.r = 0;
  c.g = 0;
  c.b = 0;
  
  // Left paddle?
  if(rect_contains(state.lpaddle.rect, pos))
  {
    c.r = PADDLE_L_RED;
    c.g = PADDLE_L_GREEN;
    c.b = PADDLE_L_BLUE;
  }
  // Right paddle?
  else if(rect_contains(state.rpaddle.rect, pos))
  {
    c.r = PADDLE_R_RED;
    c.g = PADDLE_R_GREEN;
    c.b = PADDLE_R_BLUE;
  }
  // Ball?
  else if(rect_contains(state.ball.rect, pos))
  {
    c.r = BALL_RED;
    c.g = BALL_GREEN;
    c.b = BALL_BLUE;
  }
  
  return c;
}

// Is the ball in left goal?
inline uint1_t ball_in_l_goal(rect_animated_t ball)
{
  return (ball.vel_x_dir==LEFT) & (ball.rect.pos.x < (PADDLE_L_X_POS+PADDLE_WIDTH));
}

// Is the ball in right goal?
inline uint1_t ball_in_r_goal(rect_animated_t ball)
{
  return (ball.vel_x_dir==RIGHT) & ((ball.rect.pos.x + BALL_WIDTH) > PADDLE_R_X_POS);
}

// Ball hit top of frame?
inline uint1_t ball_hit_roof(rect_animated_t ball)
{
  return (ball.vel_y_dir==UP) & (ball.rect.pos.y == 0);
}

// Ball hit bottom of frame?
inline uint1_t ball_hit_floor(rect_animated_t ball)
{
  return (ball.vel_y_dir==DOWN) & (ball.rect.pos.y >= (FRAME_HEIGHT-BALL_HEIGHT));
}

// How to adjust speed from user hit

inline vga_pos_t ball_paddle_inc_vel(vga_pos_t vel)
{
  // Add velocity to ball from whack
  // Intentionally complex version.
  // Lets work in floats
  float vel_x = vel.x;
  float vel_y = vel.y;
  
  vel_x *= PADDLE_VEL_MULT;
  vel_y *= PADDLE_VEL_MULT;
  
  vga_pos_t vel_new;
  vel_new.x = (int32_t)vel_x;
  vel_new.y = (int32_t)vel_x;
  
  // Adjust for the dumb fact that velocity is integer 0,1,2
  // Multiplying for ex. 10% increment on 1 is still 1
  // TODO fix so above multiply is used/useful
  if(vel_new.x==vel.x)
  {
    vel_new.x += 1;
  }
  if(vel_new.y==vel.y)
  {
    vel_new.y += 1;
  }

  return vel_new;
}

// How to move paddle from user input, with screen limits
inline vga_pos_t move_paddle(vga_pos_t pos, uint1_t paddle_up, uint1_t paddle_down)
{
  if(paddle_up & !paddle_down)
  {
    if(pos.y >= BTN_POS_INC)
    {
      pos.y -= BTN_POS_INC;
    }
  }
  else if(paddle_down & !paddle_up)
  {
    if((pos.y + BTN_POS_INC) <= (FRAME_HEIGHT-PADDLE_HEIGHT))
    {
      pos.y += BTN_POS_INC;
    }
  }
  return pos;
}

// State to return to at reset
inline game_state_t reset_values()
{
  game_state_t state;
  // Ball in the middle
  state.ball.rect.dim.x = BALL_WIDTH;
  state.ball.rect.dim.y = BALL_HEIGHT;
  state.ball.rect.pos.x = (FRAME_WIDTH/2) - (BALL_WIDTH/2);
  state.ball.rect.pos.y = (FRAME_HEIGHT/2) - (BALL_HEIGHT/2);
  state.ball.vel_x_dir = LEFT;
  state.ball.vel.x = 1;
  state.ball.vel_y_dir = UP;
  state.ball.vel.y = 1;
  // Left paddle
  state.lpaddle.rect.dim.x = PADDLE_WIDTH;
  state.lpaddle.rect.dim.y = PADDLE_HEIGHT;
  state.lpaddle.rect.pos.x = PADDLE_L_X_POS;
  state.lpaddle.rect.pos.y = (FRAME_HEIGHT/2) - (PADDLE_HEIGHT/2);
  // Right paddle
  state.rpaddle.rect.dim.x = PADDLE_WIDTH;
  state.rpaddle.rect.dim.y = PADDLE_HEIGHT;
  state.rpaddle.rect.pos.x = PADDLE_R_X_POS;
  state.rpaddle.rect.pos.y = (FRAME_HEIGHT/2) - (PADDLE_HEIGHT/2);
  return state;
}

// Logic for animating game state over time
inline game_state_t next_state_func(uint1_t reset, game_state_t state, user_input_t user_input)
{
  // Next state starts off as keeping current state  
  game_state_t next_state = state;
  
  /*
  printf("ball pos: %d, %d vel: %d, %d, dir: %d, %d\n",
    (int) state.ball.rect.pos.x, (int) state.ball.rect.pos.y,
    (int) state.ball.vel.x, (int) state.ball.vel.y,
    (int) state.ball.vel_x_dir, (int) state.ball.vel_y_dir);
  */
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
  next_state.rpaddle.rect.pos = move_paddle(
                                  state.rpaddle.rect.pos, 
                                  user_input.paddle_r_up, 
                                  user_input.paddle_r_down);
  // Left
  next_state.lpaddle.rect.pos = move_paddle(
                                  state.lpaddle.rect.pos, 
                                  user_input.paddle_l_up, 
                                  user_input.paddle_l_down);
  
  // Reset condition?
  if(reset)
  {
    next_state = reset_values();
  }
  
  return next_state;
}

// Helper func with isolated local static var to hold state
// while do_state_update local volatile static state is updating.
game_state_t curr_state_buffer(game_state_t updated_state, uint1_t update_valid)
{
  // State reg
  static game_state_t state;
  game_state_t rv = state;
  // Updated occassionally
  if(update_valid)
  {
    state = updated_state;
  }
  return rv;
}

// Logic to update the state in a multiple cycle volatile feedback pipeline
inline game_state_t do_state_update(uint1_t reset, uint1_t end_of_frame)
{
  // Volatile state registers
  #ifdef __PIPELINEC__ // Not same as software volatile
  volatile 
  #endif
  static game_state_t state;
  
  // Use 'slow' end of frame pulse as 'now' valid flag occuring 
  // every N cycles > pipeline depth/latency
  uint1_t update_now = end_of_frame | reset;
  if(update_now)
  {
    // Read input controls from user
    user_input_t user_input = get_user_input();
    
    // Update state
    state = next_state_func(reset, state, user_input);
  }
  
  // Buffer/save state as it periodically is updated/output from above
  game_state_t curr_state = curr_state_buffer(state, update_now);
  
  // Overwrite potententially invalid volatile 'state' circulating in feedback
  // replacing it with always valid buffered curr state. 
  // This way state will be known good when the next frame occurs
  state = curr_state;
         
  return curr_state;
}

// Logic to start in reset and exit reset after first frame
uint1_t reset_state(uint1_t end_of_frame)
{
  // Reset register
  static uint1_t reset = 1; // Start in reset
  uint1_t rv = reset;
  if(end_of_frame)
  {
    reset = 0; // Out of reset after first frame
  }
  return rv;
}

// Set design main top level to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Per clock game logic:
  
  // Get reset state/status
  uint1_t reset = reset_state(vga_signals.end_of_frame);
  
  // Do state updating cycle (part of volatile multi cycle pipeline w/ state)
  game_state_t curr_state = do_state_update(reset, vga_signals.end_of_frame);

  // Render the pixel at x,y pos given buffered state
  pixel_t color = render_pixel(vga_signals.pos, curr_state);
  
  // Drive output signals/registers
  pmod_register_outputs(vga_signals, color);
}
