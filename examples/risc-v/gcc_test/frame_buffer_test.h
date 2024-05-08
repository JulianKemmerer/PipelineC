//////////////////////////////////////////////////////////////////////////////////
// COPIED FROM examples/shared_resource_bus/axi_frame_buffer/*
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, does get correctly packed at 4 bytes sizeof()
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
// Tile down by 2,4,8 times etc to fit into on chip ram for now
#define TILE_FACTOR 1 // 4x to fit in 100T BRAM, x8 to not have Verilator build explode in RAM use?
#define TILE_FACTOR_LOG2 0
#define NUM_X_TILES (FRAME_WIDTH/TILE_FACTOR)
#define NUM_Y_TILES (FRAME_HEIGHT/TILE_FACTOR)
#define BYTES_PER_PIXEL 4
#define BYTES_PER_PIXEL_LOG2 2
#define AXI_BUS_BYTE_WIDTH sizeof(uint32_t)
#define AXI_RAM_DEPTH (((NUM_X_TILES*NUM_Y_TILES)*BYTES_PER_PIXEL)/AXI_BUS_BYTE_WIDTH)
#define MEM_SIZE (AXI_RAM_DEPTH*AXI_BUS_BYTE_WIDTH) // DDR=268435456 // 2^28 bytes , 256MB DDR3 = 28b address
// Pixel x,y pos to pixel index
static inline __attribute__((always_inline)) uint32_t pos_to_pixel_index(uint32_t x, uint32_t y)
{
  uint32_t x_tile_index = x >> TILE_FACTOR_LOG2;
  uint32_t y_tile_index = y >> TILE_FACTOR_LOG2;
  return (y_tile_index*NUM_X_TILES) + x_tile_index;
}
// Pixel index to address in RAM
static inline __attribute__((always_inline)) uint32_t pixel_index_to_addr(uint32_t index)
{
  // Each pixel is a 32b (4 byte) word
  uint32_t addr = index << BYTES_PER_PIXEL_LOG2;
  return addr;
}
// Pixel x,y to pixel ram address
static inline __attribute__((always_inline)) uint32_t pos_to_addr(uint32_t x, uint32_t y)
{
  uint32_t pixel_index = pos_to_pixel_index(x, y);
  uint32_t addr = pixel_index_to_addr(pixel_index);
  return addr;
}
//////////////////////////////////////////////////////////////////////////////////

//#define ENABLE_PIXEL_IN_READ

#define min(x,y)\
(x) < (y) ? (x) : (y)

void kernel(
  uint32_t x, uint32_t y,
  uint32_t frame_count,
  pixel_t* p_in, // Only valid if ENABLE_PIXEL_IN_READ
  pixel_t* p_out
){
  // Example uses 71x40 blocky resolution
  // match to roughly 1/8th of 640x480 = 80x60 // TODO zoom out to /7 or /6?
  // TODO real full resolution demo?
  x = x / 8;
  y = y / 8;
  // TODO real time from clock?
  int t = frame_count << 6;
  // Thanks internet!
  // https://www.shadertoy.com/view/4ft3Wn
  //-------------------------    
  // animation
  //-------------------------    
  int tt = min(4095,512+(t&4095));
  // vert
  int ft = tt&1023;
  int it = 1023-((tt>>2)&0xff00);
  int q = 1023-ft;
  q = (q*ft)>>10;
  q = (q*it)>>10;
  q = (q*it)>>10;
  int v0 = q>>3;
  // hori
  q = 4095-tt;
  q = (q*q)>>10;
  int u0 = q>>8;
  

  int R, B;

  //-------------------------    
  // Section A (2 MUL, 3 ADD)
  //-------------------------    
  int u = x-36-u0;
  int v = 18-y;
  int z = v-v0;
  int u2 = u*u;
  int v2 = z*z;
  int h = u2 + v2;
  //-------------------------  
  
  if( h < 200 ) 
  {
      //-------------------------------------
      // Section B, Sphere (4/7 MUL, 5/9 ADD)
      //-------------------------------------
      R = 420;
      B = 520;

      int t = 5200 + h*8;
      int p = (t*u)>>7;
      int q = (t*z)>>7;
      
      // bounce light
      int w = 18 + (((p*5-q*13))>>9) - (v0>>1);
      if( w>0 ) R += w*w;
      
      // sky light / ambient occlusion
      int o = q + 900 + (v0<<4);
      R = (R*o)>>12;
      B = (B*o)>>12;

      // sun/key light
      if( p > -q )
      {
          int w = (p+q)>>3;
          R += w;
          B += w;
      }
      //-------------------------  
}
  else if( v<0 )
  {
      //-------------------------------------
      // Section C, Ground (5/9 MUL, 6/9 ADD)
      //-------------------------------------
      R = 150 + 2*v;
      B = 50;

      int p = h + 8*v2;
      int c = -v*(240+16*v0) - p;

      // sky light / ambient occlusion
      if( c>1200 )
      {
          int o = (25*c)>>3;
          o = (c*(7840-o)>>9) - 8560;
          R = (R*o)>>10;
          B = (B*o)>>10;
      }

      // sun/key light with soft shadow
      int w = 4*v + 50;
      int r = u - w;
      int d = r*r + (u+v0)*(w+24+v0) - 90;
      if( d>0 ) R += d;
  }
  else
  {
      //------------------------------
      // Section D, Sky (1 MUL, 2 ADD)
      //------------------------------
      int c = x + 4*y;
      R = 132 + c;
      B = 192 + c;
      //-------------------------  
  }
  
  //-------------------------
  // Section E (3 MUL, 1 ADD)
  //-------------------------
  R = min(R,255);
  B = min(B,255);
  
  int G = (R*11 + 5*B)>>4;
  //-------------------------  

  //return vec3(R,G,B);
  // TODO write alpha channel too so maybe will be done as one 32b store?
  p_out->r = R;
  p_out->g = G;
  p_out->b = B;
}

// Helper to do frame sync
void threads_frame_sync(){
  // Signal done by driving the frame signal 
  // with its expected value
  int32_t expected_value = *FRAME_SIGNAL;
  *FRAME_SIGNAL = expected_value;
  // And wait for a new different expect value
  while(*FRAME_SIGNAL == expected_value){}
}


void frame_buf_read(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  ram_read(addr, (uint32_t*)pixel, num_pixels);
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, (uint32_t*)pixel, num_pixels);
}
void frame_buf_write_start(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_write(addr, (uint32_t*)pixel, num_pixels);
}
riscv_valid_flag_t try_frame_buf_write_finish(uint32_t num_words){
  return try_finish_ram_write(num_words);
}
void frame_buf_write_finish(
  uint32_t num_pixels
){
  finish_ram_write(num_pixels);
}
void frame_buf_read_start(
  uint32_t x, uint32_t y,
  uint32_t num_pixels
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_read(addr, num_pixels);
}
void frame_buf_read_finish(pixel_t* pixel, uint8_t num_pixels){
  finish_ram_read((uint32_t*)pixel, num_pixels);
}
