// gcc debug_probes.c -o debug_probes -I ../../../../
// sudo ./debug_probes 0

#include <stdint.h>
#include <math.h>

// 'Software' side of uart
#include "../uart/uart_sw.c"

// Some info from mem test app and generated helpers
#include "../ddr3/debug.h"
// Software side auto generated helpers for to from bytes
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint8_t_bytes_t.h/uint8_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint32_t_bytes_t.h/uint32_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/mem_test_state_t_bytes_t.h/mem_test_state_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/app_debug_t_bytes_t.h/app_debug_t_bytes.h"

// Probe info and generated helpers
#include "debug_probes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint8_t_bytes_t.h/uint8_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/probes_cmd_t_bytes_t.h/probes_cmd_t_bytes.h"
// PROBES
#include "probe0.h"
#include "probe1.h"

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
  if(cmd.probe_id == 1) probe_num_bytes = PROBE1_SIZE;
  
  // Do read of n bytes
  uart_read(buff, probe_num_bytes);
  
  // Print the probe
  if(cmd.probe_id == 0) 
  {
    probe0_t probe0;
    probe0_bytes_to_type(buff,&probe0);
    probe0_print(probe0)
  }
  if(cmd.probe_id == 1) 
  {
    probe1_t probe1;
    probe1_bytes_to_type(buff,&probe1);
    probe1_print(probe1)
  }
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
