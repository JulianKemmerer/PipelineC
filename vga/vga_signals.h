typedef struct vga_pos_t
{
  uint12_t x;
  uint12_t y;
}vga_pos_t;
typedef struct vga_signals_t
{
  vga_pos_t pos;
  uint1_t hsync;
  uint1_t vsync;
  uint1_t active;
  uint1_t start_of_frame;
  uint1_t end_of_frame;
  uint1_t valid;
}vga_signals_t;