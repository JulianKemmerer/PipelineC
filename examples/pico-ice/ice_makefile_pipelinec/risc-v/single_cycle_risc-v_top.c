// See configuration details like top level pin mapping in top.h
//#define DEFAULT_PI_UART
//#define DEFAULT_VGA_PMOD // TODO can't meet 25MHz pixel clock yet...
#include "../top.h"

#include "uintN_t.h"
#include "intN_t.h"

// RISC-V components
#include "examples/risc-v/risc-v.h"

// Include test gcc compiled program
#include "text_mem_init.h"
#include "data_mem_init.h"

// Declare memory map information
// Starts with shared with software memory map info
#include "mem_map.h"
// Define inputs and outputs
// Define MMIO inputs and outputs
typedef struct my_mmio_in_t{
  mm_status_regs_t status;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  mm_ctrl_regs_t ctrl;
}my_mmio_out_t;
// Define the hardware memory for those IO
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  // Outputs
  static riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  o.addr_is_mapped = 0; // since o is static regs

  // MM Control+status registers
  static mm_ctrl_regs_t ctrl;
  o.outputs.ctrl = ctrl; // output reg
  static mm_status_regs_t status;

  // Memory muxing/select logic
  // Uses helper comparing word address and driving a variable
  STRUCT_MM_ENTRY_NEW(MM_CTRL_REGS_ADDR, mm_ctrl_regs_t, ctrl, ctrl, addr, o.addr_is_mapped, o.rd_data)
  STRUCT_MM_ENTRY_NEW(MM_STATUS_REGS_ADDR, mm_status_regs_t, status, status, addr, o.addr_is_mapped, o.rd_data)

  // Input regs
  status = inputs.status;

  return o;
}

// Declare a RISCV core type using memory info
#define riscv_name              my_riscv
#define RISCV_IMEM_INIT         text_MEM_INIT
#define RISCV_IMEM_SIZE_BYTES   IMEM_SIZE     
#define RISCV_DMEM_INIT         data_MEM_INIT 
#define RISCV_DMEM_SIZE_BYTES   DMEM_SIZE     
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#include "examples/risc-v/risc-v_decl.h"

// Set clock of instances of CPU
MAIN_MHZ(my_cpu_top, PLL_CLK_MHZ)
void my_cpu_top()
{
  // Instance of core
  my_mmio_in_t in; // Disconnected for now
  my_riscv_out_t out = my_riscv(in);

  // Output LEDs for hardware debug
  // (active low on pico ice)
  led_g = out.mem_map_outputs.ctrl.led;
  static uint1_t mem_out_of_range;
  static uint1_t unknown_op;
  led_b = ~mem_out_of_range;
  led_r = ~unknown_op;
  mem_out_of_range |= out.mem_out_of_range;
  unknown_op |= out.unknown_op;
}

#ifdef DEFAULT_PI_UART
// UART part of demo
MAIN_MHZ(uart_main, PLL_CLK_MHZ)
void uart_main(){
  // Default loopback connect
  uart_tx_mac_word_in = uart_rx_mac_word_out;
  uart_rx_mac_out_ready = uart_tx_mac_in_ready;

  // Override .data to do case change demo
  char in_char = uart_rx_mac_word_out.data;
  char out_char = in_char;
  uint8_t case_diff = 'a' - 'A';
  if(in_char >= 'a' && in_char <= 'z'){
    out_char = in_char - case_diff;
  }else if(in_char >= 'A' && in_char <= 'Z'){
    out_char = in_char + case_diff;
  }
  uart_tx_mac_word_in.data = out_char;
}
#endif

#ifdef DEFAULT_VGA_PMOD
// VGA pmod part of demo
#include "vga/test_pattern.h"
// vga_timing() and PIXEL_CLK_MHZ from vga_timing.h in top.h
MAIN_MHZ(vga_pmod_main, PIXEL_CLK_MHZ) 
void vga_pmod_main(){
  // VGA timing for fixed resolution
  vga_signals_t vga_signals = vga_timing();
  
  // Test pattern from Digilent of color bars and bouncing box
  test_pattern_out_t test_pattern_out = test_pattern(vga_signals);
  
  // Drive output signals/registers
  vga_r = test_pattern_out.pixel.r;
  vga_g = test_pattern_out.pixel.g;
  vga_b = test_pattern_out.pixel.b;
  vga_hs = test_pattern_out.vga_signals.hsync;
  vga_vs = test_pattern_out.vga_signals.vsync;
}
#endif