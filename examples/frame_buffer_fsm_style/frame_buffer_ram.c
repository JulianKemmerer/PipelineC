// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application'

// This demo starts off as basic as possible, 1 bit per pixel
// essentially a 'chasing the beam' design reading 
// from LUTs/LUTRAM instead of output from render_pixel pipeline
// ...with an extra read/write port wires for the application too
// The user/application RAM port will use a valid+ready handshake
// to be compatible for other RAM styles later, BRAM, off chip memory, etc
// Global wires for use once anywhere in code
//  Inputs
uint1_t frame_buffer_wr_data_in;
uint16_t frame_buffer_x_in;
uint16_t frame_buffer_y_in;
uint1_t frame_buffer_wr_enable_in; // 0=read
uint1_t frame_buffer_inputs_valid_in;
uint1_t frame_buffer_outputs_ready_in;
//  Outputs
uint1_t frame_buffer_rd_data_out;
uint1_t frame_buffer_outputs_valid_out;
uint1_t frame_buffer_inputs_ready_out;

// RAM init data from file
#include "frame_buf_init_data.h"

// Need a RAM with two read ports
// need to manually write VHDL code the synthesis tool supports
// since multiple read ports have not been built into PipelineC yet
// https://github.com/JulianKemmerer/PipelineC/issues/93
typedef struct frame_buf_ram_outputs_t
{
  uint1_t read_data0;
  uint1_t read_data1;
}frame_buf_ram_outputs_t;
#include "xstr.h" // xstr func for putting quotes around macro things
frame_buf_ram_outputs_t frame_buf_ram(
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

// Helper function to flatten 2D x,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  return (x*FRAME_HEIGHT) + y;
}

// Function argument input is VGA chasing the beam always reading
// return value is read pixel data for display
// User applicaiton uses frame_buffer_ wires directly
// Needs to be --comb for valid+ready handshake for now
uint1_t frame_buf_function(
  uint16_t vga_x, uint16_t vga_y
){
  // RAM is 0 latency LUTRAM
  // Connect handshake directly in 0 latency as well
  frame_buffer_outputs_valid_out = frame_buffer_inputs_valid_in;
  //frame_buffer_inputs_ready_out = frame_buffer_outputs_ready_in;
  // ^ Can cause timing loops when combined with 0 latency...
  // fake it always ready for now while RAM is simple 0 cycle
  frame_buffer_inputs_ready_out = 1;

  // Handshake validates write enable
  uint1_t gated_wr_en = frame_buffer_wr_enable_in & (frame_buffer_inputs_valid_in & frame_buffer_outputs_ready_in);

  // Convert x,y pos to addr
  uint32_t vga_addr = pos_to_addr(vga_x, vga_y);
  uint32_t frame_buffer_addr = pos_to_addr(frame_buffer_x_in, frame_buffer_y_in);

  // Do RAM lookups
  // First port is for user application, is read+write
  // Second port is read only for the frame buffer vga display
  frame_buf_ram_outputs_t ram_outputs 
    = frame_buf_ram(frame_buffer_addr, 
                    frame_buffer_wr_data_in, 
                    gated_wr_en,
                    vga_addr);

  // Drive output signals with RAM values
  frame_buffer_rd_data_out = ram_outputs.read_data0;
  return ram_outputs.read_data1;
}

// TODO make macros for repeated code in frame_buf_read_write and line_buf_read_write

// Helper FSM func for read/writing the frame buffer using global wires
// TODO simplify once RAM is not able to do 0 cycle latency
uint1_t frame_buf_read_write(uint16_t x, uint16_t y, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs and ready for outputs
  frame_buffer_inputs_valid_in = 1;
  frame_buffer_outputs_ready_in = 1;
  frame_buffer_wr_data_in = wr_data;
  frame_buffer_x_in = x;
  frame_buffer_y_in = y;
  frame_buffer_wr_enable_in = wr_en;
  
  // Wait for inputs to be accepted
  while(!frame_buffer_inputs_ready_out)
  {
    // Werent accepted, then not yet ready for 0 latency output because waiting
    frame_buffer_outputs_ready_in = 0;
    __clk();
  }
  // Inputs are being accepted now, so ready for 0 latency output
  uint1_t rv;
  // Signal ready for output and check valid
  frame_buffer_outputs_ready_in = 1;
  if(frame_buffer_outputs_valid_out)
  {
    // Take output now
    rv = frame_buffer_rd_data_out;
  }
  else
  {
    // Need to wait some clocks for output
    // Make sure not to leave input valid/enable set while waiting
    __clk();
    frame_buffer_inputs_valid_in = 0;
    frame_buffer_wr_enable_in = 0;
    // Wait for output valid
    while(!frame_buffer_outputs_valid_out)
    {
      __clk();
    }
    // Output valid now
    rv = frame_buffer_rd_data_out;
  }
  // Make sure not to leave valid/enable/ready set by clearing it next clock
  __clk();
  frame_buffer_inputs_valid_in = 0;
  frame_buffer_wr_enable_in = 0;
  frame_buffer_outputs_ready_in = 0;
  
  return rv;
}
// Derived fsm from func, there can only be a single instance of it
#include "frame_buf_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define frame_buf_read(x, y) frame_buf_read_write(x, y, 0, 0)
#define frame_buf_write(x, y, wr_data) frame_buf_read_write(x, y, wr_data, 1)

// Similar structure for two-line buffer RAM/s
// Global wires for use once anywhere in code
//  Inputs
uint1_t line_bufs_line_sel_in;
uint16_t line_bufs_x_in;
uint1_t line_bufs_wr_data_in;
uint1_t line_bufs_wr_enable_in; // 0=read
uint1_t line_bufs_inputs_valid_in;
uint1_t line_bufs_outputs_ready_in;
//  Outputs
uint1_t line_bufs_rd_data_out;
uint1_t line_bufs_outputs_valid_out;
uint1_t line_bufs_inputs_ready_out;

// Line buffer used only by application via global wires (never called directly)
// So need stand alone func to wire things up
#pragma MAIN line_bufs_function
void line_bufs_function()
{
  // RAM is 0 latency LUTRAM
  // Connect handshake directly in 0 latency as well
  line_bufs_outputs_valid_out = line_bufs_inputs_valid_in;
  //line_bufs_inputs_ready_out = line_bufs_outputs_ready_in;
  // ^ Can cause timing loops when combined with 0 latency...
  // fake it always ready for now while RAM is simple 0 cycle
  line_bufs_inputs_ready_out = 1;

  // Handshake validates write enable
  uint1_t gated_wr_en = line_bufs_wr_enable_in & (line_bufs_inputs_valid_in & line_bufs_outputs_ready_in);

  // Do RAM lookup
  // Two line buffers inside one func for now
  static uint1_t line_buf0[FRAME_WIDTH];
  static uint1_t line_buf1[FRAME_WIDTH];
  uint1_t read_val;
  if (line_bufs_line_sel_in) {
    read_val = line_buf1_RAM_SP_RF_0(line_bufs_x_in, line_bufs_wr_data_in, gated_wr_en);
  } else {
    read_val = line_buf0_RAM_SP_RF_0(line_bufs_x_in, line_bufs_wr_data_in, gated_wr_en);
  }
  
  // Drive output signal with RAM value
  line_bufs_rd_data_out = read_val;
}

// Line buffer is single read|write port
// Is built in as _RAM_SP_RF_0 (single port, read first, 0 clocks)
uint1_t line_buf_read_write(uint1_t line_sel, uint16_t x, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs and ready for outputs
  line_bufs_inputs_valid_in = 1;
  line_bufs_outputs_ready_in = 1;
  line_bufs_line_sel_in = line_sel;
  line_bufs_wr_data_in = wr_data;
  line_bufs_x_in = x;
  line_bufs_wr_enable_in = wr_en;
  
  // Wait for inputs to be accepted
  while(!line_bufs_inputs_ready_out)
  {
    // Werent accepted, then not yet ready for 0 latency output because waiting
    line_bufs_outputs_ready_in = 0;
    __clk();
  }
  // Inputs are being accepted now, so ready for 0 latency output
  uint1_t rv;
  // Signal ready for output and check valid
  line_bufs_outputs_ready_in = 1;
  if(line_bufs_outputs_valid_out)
  {
    // Take output now
    rv = line_bufs_rd_data_out;
  }
  else
  {
    // Need to wait some clocks for output
    // Make sure not to leave input valid/enable set while waiting
    __clk();
    line_bufs_inputs_valid_in = 0;
    line_bufs_wr_enable_in = 0;
    // Wait for output valid
    while(!line_bufs_outputs_valid_out)
    {
      __clk();
    }
    // Output valid now
    rv = line_bufs_rd_data_out;
  }
  // Make sure not to leave valid/enable/ready set by clearing it next clock
  __clk();
  line_bufs_inputs_valid_in = 0;
  line_bufs_wr_enable_in = 0;
  line_bufs_outputs_ready_in = 0;
  
  return rv;
}
// Derived fsm from func, there can only be a single instance of it
#include "line_buf_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define line_buf_read(line_sel, x) line_buf_read_write(line_sel, x, 0, 0)
#define line_buf_write(line_sel, x, wr_data) line_buf_read_write(line_sel, x, wr_data, 1)


/*// A very inefficient all LUTs/muxes (no BRAM) zero latency ~frame buffer
  // https://github.com/JulianKemmerer/PipelineC/wiki/Arrays
  // Array access implemented uses muxes, ex. 640x480=307200
  // so read is implemented like a 307200->1 mux...
  // Actually each index is rounded to power of 2, so 640x480 becomes 1024x512
  //    frame_buffer_ram[10b x value][9b y value] 
  // is same as
  //    frame_buffer_ram[19b address]
  // ...very big/inefficient/slow...
  // 19b select for 524288->1 mux (only 307200 addresses used)...
  static pixel_t frame_buffer_ram[FRAME_WIDTH][FRAME_HEIGHT];
  pixel_t color = frame_buffer_ram[vga_signals.pos.x][vga_signals.pos.y];
  // The additonal read/write port for the main application
  frame_buffer_rd_data_out = frame_buffer_ram[frame_buffer_x_in][frame_buffer_y_in];
  if(frame_buffer_wr_enable_in)
  {
    frame_buffer_ram[frame_buffer_x_in][frame_buffer_y_in] = frame_buffer_wr_data_in;
  }
*/

/*// Allow for reading+writing N pixels at a time from a frame buffer port
// (could be turned into a line buffer)
#define FRAME_BUF_DATA_SIZE_PIXELS 1
typedef struct frame_buf_data_t
{
    pixel_t pixels[FRAME_BUF_DATA_SIZE_PIXELS];
}frame_buf_data_t; 
// Frame buffer RAM stores all pixels in chunks of FRAME_BUF_DATA_SIZE_PIXELS
#define TOTAL_PIXELS (FRAME_HEIGHT*FRAME_WIDTH)
#define FRAME_BUF_NUM_ENTRIES (TOTAL_PIXELS/FRAME_BUF_DATA_SIZE_PIXELS)
frame_buf_data_t frame_buffer[FRAME_BUF_NUM_ENTRIES];
*/
