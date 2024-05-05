//////////////////////////////////////////////////////////////////////////////////
// COPIED FROM examples/shared_resource_bus/axi_frame_buffer/*
typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t; // 24bpp color, does get correctly packed at 4 bytes sizeof()
#define FRAME_WIDTH 800
#define FRAME_HEIGHT 600
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

void kernel(int x, int y, pixel_t* p){
  // Invert all colors
  // Kenrel right now doesnt depend on x,y position
  p->r = ~p->r;
  p->g = ~p->g;
  p->b = ~p->b;
  //return p;
}

// Helper to do frame sync
void threads_frame_sync(){
  // Signal done by driving the frame signal 
  // with its expected value
  int32_t expected_value = *FRAME_SIGNAL;
  *FRAME_SIGNAL = expected_value;
  // And wait for a new different expect value
  while(*FRAME_SIGNAL == expected_value){}
  return;
}


// Pack and unpack pixel type for ram_read/ram_write
void frame_buf_read(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  //uint32_t addr,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  // TODO reduce copies / use mmio regs directly?
  uint32_t read_data[RISCV_RAM_NUM_BURST_WORDS] = {0};
  ram_read(addr, read_data, num_pixels);
  //pixel_t pixel;
  for (uint32_t i = 0; i < num_pixels; i++)
  {
    pixel[i].a = read_data[i] >> (0*8);
    pixel[i].r = read_data[i] >> (1*8);
    pixel[i].g = read_data[i] >> (2*8);
    pixel[i].b = read_data[i] >> (3*8);
  }  
  //return pixel;
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  uint8_t num_pixels,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data[RISCV_RAM_NUM_BURST_WORDS] = {0};// = 0;
  // TODO reduce copies / use mmio regs directly?
  for (uint32_t i = 0; i < num_pixels; i++)
  {
    write_data[i] |= ((uint32_t)pixel[i].a<<(0*8));
    write_data[i] |= ((uint32_t)pixel[i].r<<(1*8));
    write_data[i] |= ((uint32_t)pixel[i].g<<(2*8));
    write_data[i] |= ((uint32_t)pixel[i].b<<(3*8));
  }
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, write_data, num_pixels);
}

/* TODO



// Pack and unpack pixel type for ram_read/ram_write
// Multiple in flight version
void frame_buf_read_start(
  uint32_t x, uint32_t y
  //uint32_t addr
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_read(addr);
}
void frame_buf_read_finish(pixel_t* pixel){
  uint32_t read_data;
  finish_ram_read(&read_data);
  //pixel_t pixel;
  pixel->a = read_data >> (0*8);
  pixel->r = read_data >> (1*8);
  pixel->g = read_data >> (2*8);
  pixel->b = read_data >> (3*8);
  //return pixel;
}
// Multiple in flight version
void frame_buf_write_start(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel->a<<(0*8));
  write_data |= ((uint32_t)pixel->r<<(1*8));
  write_data |= ((uint32_t)pixel->g<<(2*8));
  write_data |= ((uint32_t)pixel->b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  start_ram_write(addr, write_data);
}
void frame_buf_write_finish(){
  finish_ram_write();
}


#define BUFFER_N_PIXELS 16
void read_pixel_buf(int x, int y, pixel_t* pixel_buf){
  // Start N reads
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_read_start(x+i, y);
  }
  // Finish N reads
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_read_finish(&(pixel_buf[i]));
  }
}
void write_pixel_buf(int x, int y, pixel_t* pixel_buf){
  // Start N writes
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_write_start(x+i, y, &(pixel_buf[i]));
  }
  // Finish N writes
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_write_finish();
  }
}


// Pack and unpack pixel type for ram_read/ram_write
void frame_buf_read(
  uint32_t x, uint32_t y,
  //uint32_t addr,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  uint32_t read_data;
  ram_read(addr, &read_data);
  //pixel_t pixel;
  pixel->a = read_data >> (0*8);
  pixel->r = read_data >> (1*8);
  pixel->g = read_data >> (2*8);
  pixel->b = read_data >> (3*8);
  //return pixel;
}
// Multiple in flight version
void frame_buf_read_start(
  uint32_t x, uint32_t y
  //uint32_t addr
){
  uint32_t addr = pos_to_addr(x, y);
  start_ram_read(addr);
}
void frame_buf_read_finish(pixel_t* pixel){
  uint32_t read_data;
  finish_ram_read(&read_data);
  //pixel_t pixel;
  pixel->a = read_data >> (0*8);
  pixel->r = read_data >> (1*8);
  pixel->g = read_data >> (2*8);
  pixel->b = read_data >> (3*8);
  //return pixel;
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel->a<<(0*8));
  write_data |= ((uint32_t)pixel->r<<(1*8));
  write_data |= ((uint32_t)pixel->g<<(2*8));
  write_data |= ((uint32_t)pixel->b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, write_data);
}
// Multiple in flight version
void frame_buf_write_start(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel->a<<(0*8));
  write_data |= ((uint32_t)pixel->r<<(1*8));
  write_data |= ((uint32_t)pixel->g<<(2*8));
  write_data |= ((uint32_t)pixel->b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  start_ram_write(addr, write_data);
}
void frame_buf_write_finish(){
  finish_ram_write();
}

// Helper to do frame sync
void threads_frame_sync(){
  // Signal done by driving the frame signal 
  // with its expected value
  int32_t expected_value = *FRAME_SIGNAL;
  *FRAME_SIGNAL = expected_value;
  // And wait for a new different expect value
  while(*FRAME_SIGNAL == expected_value){}
  return;
}

void kernel(int x, int y, pixel_t* p){
  // Invert all colors
  // Kenrel right now doesnt depend on x,y position
  p->r = ~p->r;
  p->g = ~p->g;
  p->b = ~p->b;
  //return p;
}

#define BUFFER_N_PIXELS 16 // Shared res bus depth
void read_pixel_buf(int x, int y, pixel_t* pixel_buf){
  // Assumes reads can burst up to buffer size
  // since shared res bus has fifos
  // Calculate base address
  uint32_t base_addr = pos_to_addr(x, y);
  // Start N reads
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    RAM_RD_REQ->addr = addr+i;
    RAM_RD_REQ->valid = 1;
  }
  // Finish N reads
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_read_finish(&(pixel_buf[i]));
  }
}
void write_pixel_buf(int x, int y, pixel_t* pixel_buf){
  // Assumes can burst up to buffer size
  // since shared res bus has fifos
  // Calculate base address
  uint32_t base_addr = pos_to_addr(x, y);
  // Start N writes
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    // Start
    RAM_WR_REQ->addr = addr+i;
    RAM_WR_REQ->data = pixel_buf[i];
    RAM_WR_REQ->valid = 1;
  }
  // Finish N writes
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    frame_buf_write_finish();
  }
}



// Pack and unpack pixel type for ram_read/ram_write
void frame_buf_read(
  uint32_t x, uint32_t y,
  //uint32_t addr,
  pixel_t* pixel
){
  uint32_t addr = pos_to_addr(x, y);
  uint32_t read_data;
  ram_read(addr, &read_data);
  //pixel_t pixel;
  pixel->a = read_data >> (0*8);
  pixel->r = read_data >> (1*8);
  pixel->g = read_data >> (2*8);
  pixel->b = read_data >> (3*8);
  //return pixel;
}
// Multiple in flight version
riscv_valid_flag_t try_frame_buf_read_start(
  uint32_t x, uint32_t y
  //uint32_t addr
){
  uint32_t addr = pos_to_addr(x, y);
  return try_start_ram_read(addr);
}
riscv_valid_flag_t try_frame_buf_read_finish(pixel_t* pixel){
  uint32_t read_data;
  if(!try_finish_ram_read(&read_data)) return 0;
  //pixel_t pixel;
  pixel->a = read_data >> (0*8);
  pixel->r = read_data >> (1*8);
  pixel->g = read_data >> (2*8);
  pixel->b = read_data >> (3*8);
  //return pixel;
  return 1;
}
void frame_buf_write(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel->a<<(0*8));
  write_data |= ((uint32_t)pixel->r<<(1*8));
  write_data |= ((uint32_t)pixel->g<<(2*8));
  write_data |= ((uint32_t)pixel->b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  ram_write(addr, write_data);
}
// Multiple in flight version
riscv_valid_flag_t try_frame_buf_write_start(
  uint32_t x, uint32_t y,
  //uint32_t addr, 
  pixel_t* pixel
){
  uint32_t write_data = 0;
  write_data |= ((uint32_t)pixel->a<<(0*8));
  write_data |= ((uint32_t)pixel->r<<(1*8));
  write_data |= ((uint32_t)pixel->g<<(2*8));
  write_data |= ((uint32_t)pixel->b<<(3*8));
  uint32_t addr = pos_to_addr(x, y);
  return try_start_ram_write(addr, write_data);
}
riscv_valid_flag_t try_frame_buf_write_finish(){
  return try_finish_ram_write();
}



#define BUFFER_N_PIXELS 16 //Assumes BUFFER_N_PIXELS=shared bus fifo size = 16
void start_read_pixel_buf(int x, int y){
  // Assumes BUFFER_N_PIXELS=shared bus fifo size
  // can burst up to buffer size
  // Calculate base address
  uint32_t base_addr = pos_to_addr(x, y);
  // Start N reads
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    RAM_RD_REQ->addr = base_addr+(i<<BYTES_PER_PIXEL_LOG2);
    RAM_RD_REQ->valid = 1;
  }
}
void start_write_pixel_buf(int x, int y, pixel_t* pixel_buf){
  // Assumes BUFFER_N_PIXELS=shared bus fifo size
  // can burst up to buffer size
  // Calculate base address
  uint32_t base_addr = pos_to_addr(x, y);
  // Start N writes
  for(int i=0; i < BUFFER_N_PIXELS; i++){
    uint32_t write_data = 0;
    write_data |= ((uint32_t)pixel_buf[i].a<<(0*8));
    write_data |= ((uint32_t)pixel_buf[i].r<<(1*8));
    write_data |= ((uint32_t)pixel_buf[i].g<<(2*8));
    write_data |= ((uint32_t)pixel_buf[i].b<<(3*8));
    // Start
    RAM_WR_REQ->addr = base_addr+(i<<BYTES_PER_PIXEL_LOG2);
    RAM_WR_REQ->data = write_data;
    RAM_WR_REQ->valid = 1;
  }
}

*/