/////////////////// GENERIC FRAME BUFFER DUAL PORT RAM ///////////////////////////////////

// VGA pmod stuff
#define FRAME_WIDTH 640
#define FRAME_HEIGHT 480
//#include "vga/vga_pmod_async_fifo.c"
#define RAM_PIXEL_BUFFER_SIZE 16 // number of pixels in x direction N_PIXELS
#define RAM_PIXEL_BUFFER_SIZE_LOG2 4
#define VGA_ASYNC_FIFO_N_PIXELS RAM_PIXEL_BUFFER_SIZE
#include "vga/vga_pmod_async_pixels_fifo.c" // Version that expects only x,y pixels, N at a time

// Unit of memory N pixels at a time
// Must be divisor of FRAME_WIDTH across x direction
typedef struct n_pixels_t{
  uint1_t data[RAM_PIXEL_BUFFER_SIZE];
}n_pixels_t;

// The frame buffer with multiple ports
#include "ram.h"
#define N_FRAME_BUF_PORTS 2
DECL_RAM_DP_RW_RW_1(
  n_pixels_t,
  frame_buf_ram,
  ((FRAME_WIDTH/RAM_PIXEL_BUFFER_SIZE)*FRAME_HEIGHT),
  "(others => (others => (others => (others => '1'))))"
)

// Helper function to flatten 2D x_buffer_index,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x_buffer_index, uint16_t y)
{
  return (y*(FRAME_WIDTH/RAM_PIXEL_BUFFER_SIZE)) + x_buffer_index;
}

// TODO dont need struct wrapper
typedef struct frame_buf_req_t
{
  uint32_t addr;
}frame_buf_req_t;
// TODO move into macros
#define id_t uint8_t

//  Inputs
typedef struct frame_buffer_in_ports_t{
  n_pixels_t wr_data; 
  //uint16_t x_buffer_index;
  //uint16_t y;
  frame_buf_req_t req; //uint32_t addr;
  uint1_t wr_enable; // 0=read
  id_t id;
  uint1_t valid;
}frame_buffer_in_ports_t;
//  Outputs
typedef struct frame_buffer_out_ports_t{
  n_pixels_t rd_data;
  uint1_t wr_enable; // 0=read
  id_t id;
  uint1_t valid;
}frame_buffer_out_ports_t;

// Frame buffer RAM application/user global wires for use once anywhere in code
frame_buffer_in_ports_t frame_buffer_in_ports[N_FRAME_BUF_PORTS];
frame_buffer_out_ports_t frame_buffer_out_ports[N_FRAME_BUF_PORTS];

// Frame buffer RAM
#define DEV_CLK_MHZ 100.0
MAIN_MHZ(frame_buffer_ram, DEV_CLK_MHZ)
void frame_buffer_ram()
{
  // 1 cycle of delay regs for ID field not included in RAM macro func
  static id_t id_reg[N_FRAME_BUF_PORTS];

  // Do RAM lookup
  frame_buf_ram_outputs_t frame_buf_ram_outputs = frame_buf_ram(
    frame_buffer_in_ports[0].req.addr, frame_buffer_in_ports[0].wr_data, frame_buffer_in_ports[0].wr_enable, frame_buffer_in_ports[0].valid,
    frame_buffer_in_ports[1].req.addr, frame_buffer_in_ports[1].wr_data, frame_buffer_in_ports[1].wr_enable, frame_buffer_in_ports[1].valid
  );

  // User output signals
  frame_buffer_out_ports[0].rd_data = frame_buf_ram_outputs.rd_data0;
  frame_buffer_out_ports[0].wr_enable = frame_buf_ram_outputs.wr_en0;
  frame_buffer_out_ports[0].id = id_reg[0];
  frame_buffer_out_ports[0].valid = frame_buf_ram_outputs.valid0;
  //
  frame_buffer_out_ports[1].rd_data = frame_buf_ram_outputs.rd_data1;
  frame_buffer_out_ports[1].wr_enable = frame_buf_ram_outputs.wr_en1;
  frame_buffer_out_ports[1].id = id_reg[1];
  frame_buffer_out_ports[1].valid = frame_buf_ram_outputs.valid1;

  // ID delay reg
  uint32_t i;
  for (i = 0; i < N_FRAME_BUF_PORTS; i+=1)
  {
    id_reg[i] = frame_buffer_in_ports[i].id;
  }
}
