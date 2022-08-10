// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application'

// This demo starts off as basic as possible, 1 bit per pixel
// essentially a 'chasing the beam' design reading 
// from LUTs/LUTRAM instead of output from render_pixel pipeline
// ...with an extra read/write port wires for the application too
// Global wires for use once anywhere in code
uint1_t frame_buffer_wr_data_in;
uint16_t frame_buffer_x_in;
uint16_t frame_buffer_y_in;
uint1_t frame_buffer_wr_enable_in; // 0=read
uint1_t frame_buffer_rd_data_out;

// RAM init data from file
#include "frame_buf_init_data.h" //FRAME_BUF_INIT_DATA

// Need a RAM with two read ports
// need to manually write VHDL code the synthesis tool supports
// since multiple read ports have not been built into PipelineC yet
// https://github.com/JulianKemmerer/PipelineC/issues/93
typedef struct frame_buf_outputs_t
{
  uint1_t read_data0;
  uint1_t read_data1;
}frame_buf_outputs_t;
#include "xstr.h" // xstr func for putting quotes around macro things
frame_buf_outputs_t frame_buf_function(
  uint32_t addr0,
  uint1_t wr_data0, uint1_t wr_en0, 
  uint32_t addr1
  //uint1_t wr_data1, uint1_t wr_en1 // Port1 is read-only
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr((FRAME_WIDTH*FRAME_HEIGHT)) "; \n\
  type ram_t is array(0 to SIZE-1) of std_logic; \n\
  signal the_ram : ram_t := " FRAME_BUF_INIT_DATA "; \n\
  --signal the_ram : std_logic_vector(SIZE-1 downto 0); \n\
begin \n\
  return_output.read_data0(0) <= the_ram(to_integer(addr0)); \n\
  return_output.read_data1(0) <= the_ram(to_integer(addr1)); \n\
  process(clk) \n\
  begin \n\
    if rising_edge(clk) then \n\
      if CLOCK_ENABLE(0)='1' then \n\
        if wr_en0(0) = '1' then \n\
          the_ram(to_integer(addr0)) <= wr_data0(0); \n\
        end if; \n\
      end if; \n\
    end if; \n\
  end process; \n\
");
}

// Helper FSM func for read/writing the frame buffer using global wires
uint1_t frame_buf_read_write(uint16_t x, uint16_t y, uint1_t wr_data, uint1_t wr_en)
{
  // Supply user values to the RAM port, zero latency get result
  frame_buffer_wr_data_in = wr_data;
  frame_buffer_x_in = x;
  frame_buffer_y_in = y;
  frame_buffer_wr_enable_in = wr_en;
  uint1_t rv = frame_buffer_rd_data_out;
  // Make sure not to leave write enable set by clearing it next clock
  __clk();
  frame_buffer_wr_enable_in = 0;
  return rv;
}
// Derived fsm from main, there can only be a single instance of it
#include "frame_buf_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define frame_buf_read(x, y) frame_buf_read_write(x, y, 0, 0)
#define frame_buf_write(x, y, wr_data) frame_buf_read_write(x, y, wr_data, 1)
