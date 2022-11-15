// Define the frame buffer RAM
#include "uintN_t.h"
#include "arrays.h"
#include "ram.h" // For DECL_RAM_DP_RW_R macros
#include "frame_buffer.h" // For frame size and other config

// Frame buffer is a RAM that both
// 1) allows pixels to be read at full 'chasing the beam' 
//    equivalent rate for streaming pixels for display
// 2) allows arbitrary rate reading and writing of pixels
//    by some computation process 'application' (CPU in this demo)
// RAM init data from file
#include "gcc_test/gol/frame_buf_init_data.h"
// Configure frame buffer RAM based on latency and number of ports
// 3 PORT
#ifdef FRAME_BUFFER_PORT2_RD_ONLY
#if FRAME_BUFFER_LATENCY == 0
DECL_RAM_TP_RW_R_R_0(
#elif FRAME_BUFFER_LATENCY == 1
DECL_RAM_TP_RW_R_R_1(
#endif
#else // Normal dual port CPU RW port and VGA read port
#if FRAME_BUFFER_LATENCY == 0
DECL_RAM_DP_RW_R_0(
#elif FRAME_BUFFER_LATENCY == 1
DECL_RAM_DP_RW_R_1(
#elif FRAME_BUFFER_LATENCY == 2
DECL_RAM_DP_RW_R_2(
#endif
#endif
  uint1_t,
  frame_buf_ram,
  FRAME_WIDTH*FRAME_HEIGHT,
  FRAME_BUF_INIT_DATA
)

// Helper function to flatten 2D x,y positions into 1D RAM addresses
uint32_t pos_to_addr(uint16_t x, uint16_t y)
{
  return (x*FRAME_HEIGHT) + y;
}

// Uses async fifo to buffer VGA pmod signals into pixel clock domain
#include "vga/vga_pmod_async_fifo.c"

// Frame buffer port types
typedef struct frame_buffer_inputs_t{
  uint16_t x;
  uint16_t y;
  uint1_t wr_data;
  uint1_t wr_en;
  uint1_t valid;
}frame_buffer_inputs_t;
typedef struct frame_buffer_outputs_t{
  // Inputs corresponding to output data
  frame_buffer_inputs_t inputs; 
  // The output data
  uint1_t rd_data;
}frame_buffer_outputs_t;

// Frame buffer CPU application/user global wires for use once anywhere in code
//  Inputs
frame_buffer_inputs_t cpu_frame_buffer_in;
//  Outputs
frame_buffer_outputs_t cpu_frame_buffer_out;

// Extra ports
#if FRAME_BUFFER_NUM_EXTRA_PORTS > 0
frame_buffer_inputs_t frame_buffer_extra_in_ports[FRAME_BUFFER_NUM_EXTRA_PORTS];
frame_buffer_outputs_t frame_buffer_extra_out_ports[FRAME_BUFFER_NUM_EXTRA_PORTS];
#endif

// Logic for wiring up VGA chasing the beam signals and user frame buffer wires
// User application uses frame_buffer_ wires directly
MAIN_MHZ(frame_buf_function, CPU_CLK_MHZ)
void frame_buf_function()
{
  // VGA timing for fixed resolution, with stall signals
  vga_signals_t vga_signals = vga_timing();

  // Convert VGA timing position
  // and application x,y pos to RAM addresses
  frame_buffer_inputs_t cpu_signals = cpu_frame_buffer_in;
  uint32_t cpu_addr = pos_to_addr(cpu_signals.x, cpu_signals.y);
  uint32_t vga_addr = pos_to_addr(vga_signals.pos.x, vga_signals.pos.y);

  // Frame buffer extra ports are maybe registered, does pos_to_addr too
  #if FRAME_BUFFER_NUM_EXTRA_PORTS > 0
  frame_buffer_inputs_t extra_inputs[FRAME_BUFFER_NUM_EXTRA_PORTS];
  uint32_t extra_addrs[FRAME_BUFFER_NUM_EXTRA_PORTS]; 
  extra_inputs = frame_buffer_extra_in_ports;
  uint32_t i;
  for(i=0;i<FRAME_BUFFER_NUM_EXTRA_PORTS;i+=1){
    extra_addrs[i] = pos_to_addr(frame_buffer_extra_in_ports[i].x, frame_buffer_extra_in_ports[i].y);
  }
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  ARRAY_IN_REG(frame_buffer_inputs_t, FRAME_BUFFER_NUM_EXTRA_PORTS, extra_inputs, extra_inputs)
  ARRAY_IN_REG(uint32_t, FRAME_BUFFER_NUM_EXTRA_PORTS, extra_addrs, extra_addrs)
  #endif
  #endif

  // Do RAM lookups
  // First port is for user CPU application, is read+write
  // Second port is read only for the frame buffer vga display
  // Third+ ports are generic extra ports
  frame_buf_ram_outputs_t ram_outputs
    = frame_buf_ram(// Port0
                    cpu_addr, 
                    cpu_signals.wr_data, 
                    cpu_signals.wr_en,
                    cpu_signals.valid,
                    #if FRAME_BUFFER_LATENCY == 2
                    TODO fix ports
                    #endif
                    #if FRAME_BUFFER_LATENCY >= 1
                    1, // Always output regs enabled
                    #endif
                    // Port1   
                    vga_addr,
                    vga_signals.valid // Inputs always valid
                    #if FRAME_BUFFER_LATENCY == 2
                    TODO fix ports
                    #endif
                    #if FRAME_BUFFER_LATENCY >= 1
                    , 1 // Always output regs enabled
                    #endif
                    // Port2, first extra port
                    #if FRAME_BUFFER_NUM_EXTRA_PORTS >= 1
                    , extra_addrs[0]
                    , extra_inputs[0].valid
                    #if FRAME_BUFFER_LATENCY >= 1
                    , 1 // Always output regs enabled
                    #endif
                    #endif
                    );

  // Delay input signals to match ram output latency
  // Drive signals from end/output delay regs
  // Shift array up to make room, and then put new at buf[0]
  #if FRAME_BUFFER_LATENCY > 0
  DELAY_VAR(frame_buffer_inputs_t, cpu_signals, FRAME_BUFFER_LATENCY)
  DELAY_VAR(vga_signals_t, vga_signals, FRAME_BUFFER_LATENCY)
  #if FRAME_BUFFER_NUM_EXTRA_PORTS > 0
  DELAY_ARRAY(frame_buffer_inputs_t, FRAME_BUFFER_NUM_EXTRA_PORTS, extra_inputs, FRAME_BUFFER_LATENCY)
  #endif
  #endif
  
  // Drive output signals with RAM values (already delayed FRAME_BUFFER_LATENCY)
  // and with signals manually delayed FRAME_BUFFER_LATENCY cycles

  // Port0 CPU frame buffer outputs back to CPU
  cpu_frame_buffer_out.inputs.wr_data = ram_outputs.wr_data0;
  cpu_frame_buffer_out.inputs.wr_en = ram_outputs.wr_en0;
  cpu_frame_buffer_out.inputs.valid = ram_outputs.valid0;
  cpu_frame_buffer_out.rd_data = ram_outputs.rd_data0;
  cpu_frame_buffer_out.inputs.x = cpu_signals.x; 
  cpu_frame_buffer_out.inputs.y = cpu_signals.y;

  // Port1 VGA final connection to output display pmod
  // Default black=0 unless pixel is white=1
  pixel_t color = {0};
  uint1_t vga_pixel = ram_outputs.rd_data1;
  if(vga_pixel)
  {
    color.r = 255;
    color.g = 255;
    color.b = 255;
  }
  pmod_async_fifo_write(vga_signals, color);

  // Port2 extra port frame buffer outputs delayed FRAME_BUFFER_LATENCY
  // (some from RAM, some from delay regs)
  #if FRAME_BUFFER_NUM_EXTRA_PORTS > 0
  frame_buffer_outputs_t extra_outputs[FRAME_BUFFER_NUM_EXTRA_PORTS];
  for(i=0;i<FRAME_BUFFER_NUM_EXTRA_PORTS;i+=1){
    extra_outputs[i].inputs = extra_inputs[i];
    // Port2 is first extra port, read only
    if(i==0){
      //extra_outputs_reg[i].inputs.wr_data = ram_outputs.wr_data2;
      //extra_outputs_reg[i].inputs.wr_en = ram_outputs.wr_en2;
      extra_outputs[i].inputs.valid = ram_outputs.valid2;
      extra_outputs[i].rd_data = ram_outputs.rd_data2;
    }
    #if FRAME_BUFFER_NUM_EXTRA_PORTS > 1
    TODO more ports
    #endif
  }
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  ARRAY_OUT_REG(frame_buffer_outputs_t, FRAME_BUFFER_NUM_EXTRA_PORTS, frame_buffer_extra_out_ports, extra_outputs)
  #else
  frame_buffer_extra_out_ports = extra_outputs;
  #endif
  #endif
}

// FSM style functionality for using read only first extra port, [0]
#ifdef FRAME_BUFFER_PORT2_RD_ONLY
#define FRAME_BUFFER_RW_FSM_STYLE_PORT 0
#define frame_buf_read_write_in_port frame_buffer_extra_in_ports[FRAME_BUFFER_RW_FSM_STYLE_PORT]
#define frame_buf_read_write_out_port frame_buffer_extra_out_ports[FRAME_BUFFER_RW_FSM_STYLE_PORT]
// Helper FSM func for read/writing the frame buffer using global wires
uint1_t frame_buf_read_write(uint16_t x, uint16_t y, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs into RAM for a cycle
  frame_buf_read_write_in_port.valid = 1;
  frame_buf_read_write_in_port.wr_data = wr_data;
  frame_buf_read_write_in_port.x = x;
  frame_buf_read_write_in_port.y = y;
  frame_buf_read_write_in_port.wr_en = wr_en;
  // (0 latency data is available now)
  __clk();
  // Cleared in the next cycle
  frame_buf_read_write_in_port.valid = 0;

  // Now is 1 cycle latency, maybe need extra cycle 
  #if FRAME_BUFFER_LATENCY == 2
  __clk();
  #endif

  // Finally account for additional IO regs
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  __clk(); // In delay
  __clk(); // Out delay
  #endif

  // Data is ready now
  return frame_buf_read_write_out_port.rd_data;
}
// Derived fsm from func, there can only be a single instance of it
#include "frame_buf_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define frame_buf_read(x, y) frame_buf_read_write(x, y, 0, 0)
//TEMP NO WRITE #define frame_buf_write(x, y, wr_data) frame_buf_read_write(x, y, wr_data, 1)
#endif


// Similar structure for two-line buffer RAM/s

// Configure latency to match frame buffer
#if FRAME_BUFFER_LATENCY == 0
#if LINE_BUFS_NUM_EXTRA_PORTS > 0
TODO
#else
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_0
#endif
#elif FRAME_BUFFER_LATENCY == 1
#if LINE_BUFS_NUM_EXTRA_PORTS > 0
DECL_RAM_DP_RW_RW_1(
  uint1_t,
  line_buf_ram,
  FRAME_WIDTH,
  RAM_INIT_INT_ZEROS
)
#else
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_1
#endif
#elif FRAME_BUFFER_LATENCY == 2
#if LINE_BUFS_NUM_EXTRA_PORTS > 0
TODO
#else
#define line_buf_RAM(num) line_buf##num##_RAM_SP_RF_2
#endif
#endif

// Line buffer port input and output types
typedef struct line_bufs_inputs_t{
  uint1_t line_sel;
  uint16_t x;
  uint1_t wr_data;
  uint1_t wr_en; // 0=read
  uint1_t valid;
}line_bufs_inputs_t;
typedef struct line_bufs_outputs_t{
  // Inputs corresponding to outputs
  line_bufs_inputs_t inputs;
  uint1_t rd_data;
}line_bufs_outputs_t;

// Global wires for use once anywhere in code
// In+Out wires to+from the CPU
line_bufs_inputs_t cpu_line_bufs_in;
line_bufs_outputs_t cpu_line_bufs_out;
// Extra ports
#if LINE_BUFS_NUM_EXTRA_PORTS > 0
line_bufs_inputs_t line_bufs_extra_in_ports[LINE_BUFS_NUM_EXTRA_PORTS];
line_bufs_outputs_t line_bufs_extra_out_ports[LINE_BUFS_NUM_EXTRA_PORTS];
#endif

// Line buffer used only by application via global wires (never called directly)
// So need stand alone func to wire things up (similar to frame buffer wiring)
MAIN_MHZ(line_bufs_function, CPU_CLK_MHZ)
void line_bufs_function()
{
  // Do RAM lookups, same delay as frame buffer
  // Always one RW port at least
  uint1_t port0_read_val;
  line_bufs_inputs_t cpu_inputs = cpu_line_bufs_in;
  
  // Extra ports?
  #if LINE_BUFS_NUM_EXTRA_PORTS > 0
  line_bufs_inputs_t extra_inputs[LINE_BUFS_NUM_EXTRA_PORTS];
  // Input registers on extra ports?
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  ARRAY_IN_REG(line_bufs_inputs_t, LINE_BUFS_NUM_EXTRA_PORTS, extra_inputs, line_bufs_extra_in_ports)
  #else
  extra_inputs = line_bufs_extra_in_ports;
  #endif
  // Port0 is CPU. Port1 is first extra port
  // A ram for each line buffer
  // need to gate valid signals, and select output with line select
  uint1_t extra_ports_read_val[LINE_BUFS_NUM_EXTRA_PORTS];
  uint1_t port0_line0_sel = cpu_inputs.line_sel==0;
  uint1_t port0_line1_sel = cpu_inputs.line_sel==1;
  uint1_t extra_port_line0_sel[LINE_BUFS_NUM_EXTRA_PORTS];
  uint1_t extra_port_line1_sel[LINE_BUFS_NUM_EXTRA_PORTS];
  uint32_t i;
  for(i = 0; i < LINE_BUFS_NUM_EXTRA_PORTS; i+=1)
  {
    extra_port_line0_sel[i] = extra_inputs[i].line_sel==0;
    extra_port_line1_sel[i] = extra_inputs[i].line_sel==1;
  }
  line_buf_ram_outputs_t line_buf0_out = line_buf_ram(
              cpu_inputs.x, 
              cpu_inputs.wr_data, 
              cpu_inputs.wr_en, 
              cpu_inputs.valid & port0_line0_sel,
              1
              #if LINE_BUFS_NUM_EXTRA_PORTS >= 1
              ,
              extra_inputs[0].x,
              extra_inputs[0].wr_data,
              extra_inputs[0].wr_en, 
              extra_inputs[0].valid & extra_port_line0_sel[0],
              1
              #endif
            );
  line_buf_ram_outputs_t line_buf1_out = line_buf_ram(
              cpu_inputs.x, 
              cpu_inputs.wr_data, 
              cpu_inputs.wr_en, 
              cpu_inputs.valid & port0_line1_sel,
              1
              #if LINE_BUFS_NUM_EXTRA_PORTS >= 1
              ,
              extra_inputs[0].x,
              extra_inputs[0].wr_data,
              extra_inputs[0].wr_en, 
              extra_inputs[0].valid & extra_port_line1_sel[0],
              1
              #endif
            );
  // Select output based on line select
  // Extra ports start at Port1
  if(port0_line0_sel)
    port0_read_val = line_buf0_out.rd_data0;
  else if(port0_line1_sel)
    port0_read_val = line_buf1_out.rd_data0;
  #if LINE_BUFS_NUM_EXTRA_PORTS >= 1
  if(extra_port_line0_sel[0])
    extra_ports_read_val[0] = line_buf0_out.rd_data1;
  else if(extra_port_line1_sel[0])
    extra_ports_read_val[0] = line_buf1_out.rd_data1;
  #endif 
  #else
  // No extra ports, just one RW port
  // Single port built in as _RAM_SP_RF (single port, read first)
  // Two line buffers inside one func for now
  static uint1_t line_buf0[FRAME_WIDTH];
  static uint1_t line_buf1[FRAME_WIDTH];
  if (cpu_inputs.line_sel) {
    port0_read_val = line_buf_RAM(1)(cpu_inputs.x, cpu_inputs.wr_data, cpu_inputs.wr_en & cpu_inputs.valid);
  } else {
    port0_read_val = line_buf_RAM(0)(cpu_inputs.x, cpu_inputs.wr_data, cpu_inputs.wr_en & cpu_inputs.valid);
  }
  #endif

  // Port0 is CPU, extra ports start at port1
  // Delay input signals to align with RAM outputs after FRAME_BUFFER_LATENCY
  // Zero delay direct connect:
  #if FRAME_BUFFER_LATENCY > 0
  // >=1 clock cycle of delay for inputs
  DELAY_VAR(line_bufs_inputs_t, cpu_inputs, FRAME_BUFFER_LATENCY)
  #if LINE_BUFS_NUM_EXTRA_PORTS > 0
  DELAY_ARRAY(
    line_bufs_inputs_t, LINE_BUFS_NUM_EXTRA_PORTS,
    extra_inputs, FRAME_BUFFER_LATENCY)
  #endif
  #endif

  // Drive output signals with RAM outputs and other delayed signals
  // Port0 is CPU
  cpu_line_bufs_out.rd_data = port0_read_val;
  cpu_line_bufs_out.inputs = cpu_inputs;
  // Extra ports:
  #if LINE_BUFS_NUM_EXTRA_PORTS > 0
  line_bufs_outputs_t extra_outputs[LINE_BUFS_NUM_EXTRA_PORTS];
  for(i = 0; i < LINE_BUFS_NUM_EXTRA_PORTS; i+=1)
  {
    extra_outputs[i].rd_data = extra_ports_read_val[i];
    extra_outputs[i].inputs = extra_inputs[i];
  }
  // Finally extra outputs might have output register
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  ARRAY_OUT_REG(line_bufs_outputs_t, LINE_BUFS_NUM_EXTRA_PORTS, line_bufs_extra_out_ports, extra_outputs)
  #else
  line_bufs_extra_out_ports = extra_outputs;
  #endif
  #endif
}

// FSM style functionality for using read|write first extra line buffers port
#ifdef LINE_BUFS_PORT1_RW
#define LINE_BUFS_RW_FSM_STYLE_PORT 0
#define line_bufs_read_write_in_port line_bufs_extra_in_ports[LINE_BUFS_RW_FSM_STYLE_PORT]
#define line_bufs_read_write_out_port line_bufs_extra_out_ports[LINE_BUFS_RW_FSM_STYLE_PORT]
// Helper FSM func for read/writing the line buffers using global wires
uint1_t line_bufs_read_write(uint16_t line_sel, uint16_t x, uint1_t wr_data, uint1_t wr_en)
{
  // Start transaction by signalling valid inputs into RAM for a cycle
  line_bufs_read_write_in_port.valid = 1;
  line_bufs_read_write_in_port.line_sel = line_sel;
  line_bufs_read_write_in_port.x = x;
  line_bufs_read_write_in_port.wr_data = wr_data;
  line_bufs_read_write_in_port.wr_en = wr_en;
  // (0 latency data is available now)
  __clk();
  // Cleared in the next cycle
  line_bufs_read_write_in_port.valid = 0;

  // Now is 1 cycle latency, maybe need extra cycle 
  #if FRAME_BUFFER_LATENCY == 2
  __clk();
  #endif

  // Finally account for additional IO regs
  #ifdef FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS
  __clk(); // In delay
  __clk(); // Out delay
  #endif

  // Data is ready now
  return line_bufs_read_write_out_port.rd_data;
}
// Derived fsm from func, there can only be a single instance of it
#include "line_bufs_read_write_SINGLE_INST.h"
// Use macros to help avoid nested multiple instances of function by inlining
#define line_buf_read(line_sel, x) line_bufs_read_write(line_sel, x, 0, 0)
#define line_buf_write(line_sel, x, wr_data) line_bufs_read_write(line_sel, x, wr_data, 1)
#endif
