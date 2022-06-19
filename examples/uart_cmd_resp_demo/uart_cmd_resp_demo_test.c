/*
// Include PipelineC repo root and output directory from your run
gcc uart_cmd_resp_demo_test.c -o uart_cmd_resp_demo_test -I ../../ -I ~/pipelinec_output
sudo ./uart_cmd_resp_demo_test
Baud: B115200 
cmd.cmd = 1
cmd.addr = 420
cmd.data = 15
resp.cmd = 1
resp.addr = 420
resp.data = 15
*/

// Helper software c code for uart
#include "uart/uart_sw.c"

// Include types like command+response uart_cmd_resp_t
#include "uart_cmd_resp_demo.h"
// Auto gen header with to-from bytes conversion funcs (for software C code)
#include "type_bytes_t.h/uart_cmd_resp_t_bytes_t.h/uart_cmd_resp_t_bytes.h"

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init uart to/from FPGA
	init_uart();
	
	// Prepare a command to lite all 4 leds
	uart_cmd_resp_t cmd;
	cmd.addr = LEDS_ADDR;
	cmd.cmd = WRITE_CMD;
	cmd.data = 0b1111;

	// Send command as UART bytes
	uint8_t cmd_bytes[uart_cmd_resp_t_SIZE];
	uart_cmd_resp_t_to_bytes(&cmd, &cmd_bytes[0]);
	uart_write(&cmd_bytes[0], uart_cmd_resp_t_SIZE);
	printf("cmd.cmd = %d\n", cmd.cmd);
	printf("cmd.addr = %d\n", cmd.addr);
	printf("cmd.data = %d\n", cmd.data);

	// Read response as UART bytes
	uint8_t resp_bytes[uart_cmd_resp_t_SIZE];
	uart_read(&resp_bytes[0], uart_cmd_resp_t_SIZE);
	uart_cmd_resp_t resp;
	bytes_to_uart_cmd_resp_t(&resp_bytes[0], &resp);
	// Print response fields
	printf("resp.cmd = %d\n", resp.cmd);
	printf("resp.addr = %d\n", resp.addr);
	printf("resp.data = %d\n", resp.data);

	// Close uart to/from FPGA
	close_uart();    
}

