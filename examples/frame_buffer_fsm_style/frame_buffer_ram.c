// Uses VGA pmod signals
#include "vga/vga_pmod.c"

// Helper function to flatten 2D x,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  return (x*FRAME_HEIGHT) + y;
}

// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application'

// This demo starts off as basic as possible, 1 bit per pixel
// essentially a 'chasing the beam' design reading 
// from a RAM instead of output from render_pixel pipeline
// Then adds a simultaneous extra read/write port wires for the "application" too
// The user/application RAM port will use a valid+ready handshake
// to be compatible for other RAM styles later, BRAM, off chip memory, etc

// RAM init data from file
#include "frame_buf_init_data.h"

// Need a RAM with two read ports
// need to manually write VHDL code the synthesis tool supports
// since multiple read ports have not been built into PipelineC yet
// https://github.com/JulianKemmerer/PipelineC/issues/93
// TODO: Use ram.h preprocessor macros for same as below decl...
typedef struct frame_buf_ram_outputs_t
{
  uint1_t read_data0;
  uint1_t read_data1;
}frame_buf_ram_outputs_t;
#include "xstr.h" // xstr func for putting quotes around macro things
frame_buf_ram_outputs_t frame_buf_ram(
  uint32_t addr0,
  uint1_t wr_data0, uint1_t wr_en0,
  uint1_t out_reg_en0, 
  uint32_t addr1
  //uint1_t wr_data1, uint1_t wr_en1 // Port1 is read-only
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr((FRAME_WIDTH*FRAME_HEIGHT)) "; \n\
  type ram_t is array(0 to SIZE-1) of std_logic; \n\
  signal the_ram : ram_t := " FRAME_BUF_INIT_DATA "; \n\
  --signal the_ram : std_logic_vector(SIZE-1 downto 0); \n\
begin \n\
  process(clk) \n\
  begin \n\
    if rising_edge(clk) then \n\
      if CLOCK_ENABLE(0)='1' then \n\
        if wr_en0(0) = '1' then \n\
          the_ram(to_integer(addr0)) <= wr_data0(0); \n\
        end if; \n\
        if out_reg_en0(0)='1' then \n\
          return_output.read_data0(0) <= the_ram(to_integer(addr0)); \n\
        end if; \n\
        return_output.read_data1(0) <= the_ram(to_integer(addr1)); \n\
      end if; \n\
    end if; \n\
  end process; \n\
");
}

// Frame buffer application/user global wires for use once anywhere in code
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

// Logic for wiring up VGA chasing the beam signals and user frame buffer wires
// Function argument input is VGA chasing the beam always reading 
// return value is vga read pixel data for display
// User application uses frame_buffer_ wires directly
typedef struct frame_buf_outputs_t{
  uint1_t read_val;
  vga_signals_t vga_signals;
} frame_buf_outputs_t;
frame_buf_outputs_t frame_buf_function(vga_signals_t vga_signals)
{
  // RAM is 1 clk latency BRAM
  // Use registers to delay VGA signals to be aligned with return value next cycle
  static vga_signals_t vga_signals_delayed;
  // Similarly delay reg for valid signal and used for ready status
  static uint1_t frame_buf_delayed_signals_valid;

  // Only ready for new inputs if delay buffer isnt used
  frame_buffer_inputs_ready_out = !frame_buf_delayed_signals_valid;

  // Input handshake validates RAM write enable
  uint1_t input_xfer_now = frame_buffer_inputs_valid_in & frame_buffer_inputs_ready_out;
  uint1_t gated_wr_en = frame_buffer_wr_enable_in & input_xfer_now;
  
  // RAMs output/delay reg is allowed to change
  // for incoming inputs or outgoing outputs
  uint1_t ram_out_reg_en = frame_buffer_inputs_ready_out | frame_buffer_outputs_ready_in;

  // Convert x,y pos to RAM addresses
  uint32_t vga_addr = pos_to_addr(vga_signals.pos.x, vga_signals.pos.y);
  uint32_t frame_buffer_addr = pos_to_addr(frame_buffer_x_in, frame_buffer_y_in);

  // Do RAM lookups, 1 clk delay
  // First port is for user application 'frame buffer', is read+write
  // Second port is read only for the always reading vga display
  frame_buf_ram_outputs_t ram_outputs 
    = frame_buf_ram(frame_buffer_addr, 
                    frame_buffer_wr_data_in, gated_wr_en,
                    ram_out_reg_en,
                    vga_addr);

  // Drive output signals with signals delayed 1 clk
  frame_buffer_rd_data_out = ram_outputs.read_data0;
  frame_buffer_outputs_valid_out = frame_buf_delayed_signals_valid;
  frame_buf_outputs_t rv;
  rv.read_val = ram_outputs.read_data1;
  rv.vga_signals = vga_signals_delayed;

  // Input/delay regs
  vga_signals_delayed = vga_signals;
  // Valid delay reg is written by input ready, cleared by output ready
  if(frame_buffer_inputs_ready_out)
  {
    frame_buf_delayed_signals_valid = frame_buffer_inputs_valid_in;
  }
  else if(frame_buffer_outputs_ready_in)
  {
    frame_buf_delayed_signals_valid = 0;
  }

  return rv;
}

// TODO make macros for repeated code in frame_buf_read_write and line_buf_read_write

// Helper FSM func for read/writing the frame buffer using global wires
uint1_t frame_buf_read_write(uint16_t x, uint16_t y, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs into RAM
  frame_buffer_inputs_valid_in = 1;
  frame_buffer_wr_data_in = wr_data;
  frame_buffer_x_in = x;
  frame_buffer_y_in = y;
  frame_buffer_wr_enable_in = wr_en;
  // Not ready for output from RAM yet
  frame_buffer_outputs_ready_in = 0;
  // Wait for inputs to be accepted
  while(!frame_buffer_inputs_ready_out)
  {
    __clk();
  }
  // Inputs are being accepted now, signal ready for upcoming output
  frame_buffer_outputs_ready_in = 1;
  // Make sure not to leave input valid set by clearing it next clock
  __clk();
  frame_buffer_inputs_valid_in = 0;
  // Wait for output valid
  while(!frame_buffer_outputs_valid_out)
  {
    __clk();
  }
  // Output valid now, return the read data
  return frame_buffer_rd_data_out;
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
// So need stand alone func to wire things up (very similar to frame buffer wiring)
#pragma MAIN line_bufs_function
void line_bufs_function()
{
  // RAM is 1 clk latency BRAM
  // Delay reg for valid signal and used for ready status
  static uint1_t delayed_signals_valid;

  // Only ready for new inputs if delay buffer isnt used
  line_bufs_inputs_ready_out = !delayed_signals_valid;

  // Input handshake validates RAM write enable
  uint1_t input_xfer_now = line_bufs_inputs_valid_in & line_bufs_inputs_ready_out;
  uint1_t gated_wr_en = line_bufs_wr_enable_in & input_xfer_now;
  
  // RAMs output/delay reg is allowed to change
  // for incoming inputs or outgoing outputs
  uint1_t ram_out_reg_en = line_bufs_inputs_ready_out | line_bufs_outputs_ready_in;

  // Do RAM lookups, 1 clk delay
  // Is built in as _RAM_SP_RF_1 (single port, read first, 1 clocks)
  // Two line buffers inside one func for now
  static uint1_t line_buf0[FRAME_WIDTH];
  static uint1_t line_buf1[FRAME_WIDTH];
  uint1_t read_val;
  if(ram_out_reg_en)
  {
    if (line_bufs_line_sel_in) {
      read_val = line_buf1_RAM_SP_RF_1(line_bufs_x_in, line_bufs_wr_data_in, gated_wr_en);
    } else {
      read_val = line_buf0_RAM_SP_RF_1(line_bufs_x_in, line_bufs_wr_data_in, gated_wr_en);
    }
  }

  // Drive output signals with signals delayed 1 clk
  line_bufs_rd_data_out = read_val;
  line_bufs_outputs_valid_out = delayed_signals_valid;
  
  // Valid delay reg is written by input ready, cleared by output ready
  if(line_bufs_inputs_ready_out)
  {
    delayed_signals_valid = line_bufs_inputs_valid_in;
  }
  else if(line_bufs_outputs_ready_in)
  {
    delayed_signals_valid = 0;
  }
}

// Line buffer is single read|write port
uint1_t line_buf_read_write(uint1_t line_sel, uint16_t x, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs into RAM
  line_bufs_inputs_valid_in = 1;
  line_bufs_line_sel_in = line_sel;
  line_bufs_x_in = x;
  line_bufs_wr_data_in = wr_data;
  line_bufs_wr_enable_in = wr_en;
  // Not ready for output from RAM yet
  line_bufs_outputs_ready_in = 0;
  // Wait for inputs to be accepted
  while(!line_bufs_inputs_ready_out)
  {
    __clk();
  }
  // Inputs are being accepted now, signal ready for upcoming output
  line_bufs_outputs_ready_in = 1;
  // Make sure not to leave input valid set by clearing it next clock
  __clk();
  line_bufs_inputs_valid_in = 0;
  // Wait for output valid
  while(!line_bufs_outputs_valid_out)
  {
    __clk();
  }
  // Output valid now, return the read data
  return line_bufs_rd_data_out;
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
