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
#include "examples/pong/pong.h"

// Set design to run at pixel clock
MAIN_MHZ(app, PIXEL_CLK_MHZ)
void app()
{
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Reset register
  static uint1_t reset = 1; // Start in reset
  // State registers
  static game_state_t state;
  // Per clock game logic:
  // Render the pixel at x,y pos given state
  pixel_t color = render_pixel(vga_signals.pos, state);
  // Do animation state update, not every clock, but on every frame
  if(vga_signals.end_of_frame)
  {
    // Read input controls from user
    user_input_t user_input = get_user_input();
    //printf("user input: %d\n", (int) user_input.paddle_r_up);

    state = next_state_func(reset, state, user_input);
    reset = 0; // Out of reset after first frame
  }  
  
  // Drive output signals/registers
  pmod_register_outputs(vga_signals, color);
}
