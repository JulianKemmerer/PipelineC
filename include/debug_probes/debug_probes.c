// gcc debug_probes.c -o debug_probes -I ../ -I ../../ -I ~/pipelinec_output
// sudo ./debug_probes 0

#include <stdint.h>
#include <math.h>

// 'Software' side of uart
#define UART_TTY_DEVICE "/dev/ttyACM1"
#define UART_BAUD B115200
#include "uart/uart_sw.c"

// Info about user probes in hardware
#include "examples/pico-ice/ice_makefile_pipelinec/eth_debug_probes.h"
#define probe0 payload_debug
#define probe1 mac_debug

// And final constants for debug probes as describes below
#include "debug_probes/debug_probes.h"

void write_cmd(probes_cmd_t cmd)
{
  // Convert to bytes
  uint8_t buff[probes_cmd_t_SIZE];
  probes_cmd_t_to_bytes(&cmd, buff);
  // Write those bytes
  uart_write(buff, probes_cmd_t_SIZE); 
}

void do_cmd(probes_cmd_t cmd)
{
  // Read or write buffer (only read implemented for now)
  uint8_t buff[MAX_PROBE_SIZE]; 
  
  // Read how many bytes?
  size_t probe_num_bytes = 0;
  if(cmd.probe_id == 0) probe_num_bytes = PROBE0_SIZE;
  #ifdef probe1
  if(cmd.probe_id == 1) probe_num_bytes = PROBE1_SIZE;
  #endif
  #ifdef probe2
  #error "More probes!"
  #endif
  
  // Do read of n bytes
  uart_read(buff, probe_num_bytes);
  
  // Print the probe
  if(cmd.probe_id == 0) 
  {
    probe0_t probe0;
    probe0_bytes_to_type(buff,&probe0);
    probe0_print(probe0);
  }
  #ifdef probe1
  if(cmd.probe_id == 1) 
  {
    probe1_t probe1;
    probe1_bytes_to_type(buff,&probe1);
    probe1_print(probe1);
  }
  #endif
  #ifdef probe2
  #error "More probes!"
  #endif
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init uart to/from FPGA
	init_uart();
  
  // Which probe from cmd line
  int probe_id = 0;
  if(argc>1)
  {
    char* n_str = argv[1];
    probe_id = atoi(n_str); 
  }  
	
	// Make a command for that probe
  probes_cmd_t cmd;
  cmd.probe_id = probe_id;
  
  // Write the command
  write_cmd(cmd);
  
  // Do what the command requires
  do_cmd(cmd); 

	// Close uart to/from FPGA
	close_uart();
}
