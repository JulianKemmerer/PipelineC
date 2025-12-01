#include "vga/vga_wires_4b.c"

// Configure the VGA timing to use
// 640x480 is a 25MHz pixel clock
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
#include "vga/vga_timing.h"