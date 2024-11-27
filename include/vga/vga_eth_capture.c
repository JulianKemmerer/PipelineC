// TODO include ethernet hooks

// Base buffer size is based on ethernet frame size ~1500 bytes for now
#define VGA_ETH_CAPTURE_PIXELS_PER_FRAME 498
typedef struct vga_eth_capture_frame_t{
  // Position of first pixel in following buffer
  vga_pos_t start_pos;
  pixel_t pixels[VGA_ETH_CAPTURE_PIXELS_PER_FRAME];
} vga_eth_capture_frame_t;


#define VGA_ETH_CAPTURE



// This code receives control ethernet frames

typedef struct vga_eth_capture_ctrl_t {
  // Position to start capturing pixels
  vga_pos_t start_pos;
  uint1_t next_frame;
} vga_eth_capture_ctrl_t;


// Include the design to capture VGA outputs from
#include "test_pattern.c"

#define CAPTURE_BUFFER_SIZE FRAME_WIDTH # 



// This code will buffer P pixels eventually into FIFO
// Runs on pixel clock
buffer_pixels()
{
  // Each clock buffer a pixel, maybe info fifo etc

}


