typedef enum dvp_rgb565_decoder_state_t{
  WAIT_VSYNC,
  WAIT_FRAME,
  OUTPUT_PIXELS
}dvp_rgb565_decoder_state_t;
typedef struct dvp_rgb565_decoder_t{
  uint5_t r;
  uint6_t g;
  uint5_t b;
  uint16_t x;
  uint16_t y;
  uint1_t pixel_valid;
  uint16_t width;
  uint16_t height;
  uint1_t frame_size_valid;
} dvp_rgb565_decoder_t;
dvp_rgb565_decoder_t dvp_rgb565_decoder(
  uint1_t data[8],
  uint1_t href,
  uint1_t vsync,
  uint1_t vsync_pol,
  uint1_t cam_init_done
){
  dvp_rgb565_decoder_t o;

  // Assume vsync polarity is about idle inactive state?
  uint1_t vsync_active_level = ~vsync_pol;

  static uint16_t href_cycles_width; // width * 2
  o.width = href_cycles_width >> 1;
  static uint16_t href_cycles_counter; // x * 2
  o.x = href_cycles_counter >> 1;
  static uint16_t height;
  o.height = height;
  static uint16_t href_falling_edge_counter; // y
  o.y = href_falling_edge_counter;
  static uint1_t is_first_byte = 1;
  if(href){
    href_cycles_counter = href_cycles_counter + 1;
  }else{
    // href falling edge ends line
    if(href_cycles_counter > 0){ 
      href_cycles_width = href_cycles_counter;
      href_falling_edge_counter = href_falling_edge_counter + 1;
      href_cycles_counter = 0;
      is_first_byte = 1;
    }
  }
  // vsync transition to active level ends frame
  if(vsync==vsync_active_level){
    if(href_falling_edge_counter > 0){ 
      height = href_falling_edge_counter;
      href_falling_edge_counter = 0;
    }
  }

  static dvp_rgb565_decoder_state_t state;
  static uint1_t first_byte[8];
  static uint1_t second_byte[8];
  
  static uint1_t vs_reg;
  if(state==WAIT_VSYNC){
    // vsync transition from active to inactive level starts frame
    // Waits for cam init done too
    if((vsync==~vsync_active_level) & (vs_reg==vsync_active_level) & cam_init_done){
      state = WAIT_FRAME;
    }
    vs_reg = vsync;
  }else if(state==WAIT_FRAME){
    // vsync active ends frame
    if(vsync==vsync_active_level){
      state = OUTPUT_PIXELS;
    }
  }else if(state==OUTPUT_PIXELS){
    o.frame_size_valid = 1;
    if(href){
      if(is_first_byte){
        first_byte = data;
        is_first_byte = 0;
      }else{
        second_byte = data;
        o.pixel_valid = 1;
        is_first_byte = 1;
      }
      // RGB565 decode
      uint1_t r_bits[5];
      r_bits[4] = first_byte[7];
      r_bits[3] = first_byte[6];
      r_bits[2] = first_byte[5];
      r_bits[1] = first_byte[4];
      r_bits[0] = first_byte[3];
      o.r = uint1_array5_le(r_bits);
      uint1_t g_bits[6];
      g_bits[5] = first_byte[2];
      g_bits[4] = first_byte[1];
      g_bits[3] = first_byte[0];
      g_bits[2] = second_byte[7];
      g_bits[1] = second_byte[6];
      g_bits[0] = second_byte[5];
      o.g = uint1_array6_le(g_bits);
      uint1_t b_bits[5];
      b_bits[4] = second_byte[4];
      b_bits[3] = second_byte[3];
      b_bits[2] = second_byte[2];
      b_bits[1] = second_byte[1];
      b_bits[0] = second_byte[0];
      o.b = uint1_array5_le(b_bits);
    }
  }

  return o;
}