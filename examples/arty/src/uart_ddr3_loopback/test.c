// gcc test.c -o test -I ../../../../
// sudo ./test

#include <math.h>
#include <time.h> // TODO fix time measurements

#include "test.h" // Header with test constants shared with hardware code

// 'Software' side of uart message stuff include
#include "../uart/uart_msg_sw.c"

// Helper to init an input data
uart_msg_t input_init(int i)
{
	// Randomizeish values to sum
	uart_msg_t input;
	for(int v=0;v<UART_MSG_SIZE;v++)
	{
		input.data[v] = rand();
	}
	return input;
}

// Helper to compare two output datas
int compare_bad(int i, uart_msg_t cpu, uart_msg_t fpga)
{
  int bad = 0;
  for(int v=0;v<UART_MSG_SIZE;v++)
	{
		if(fpga.data[v] != cpu.data[v])
    {
      bad = 1;
      printf("Output %d does not match at %d! FPGA: %d, CPU: %d\n", i, v, fpga.data[v], cpu.data[v]);
    }
	}
	return bad;
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init msgs to/from FPGA
	init_msgs();
	
	// Do something using the function 'work_fpga()'
	// which uses the FPGA to compute the 'work()' function
  
	int total_bytes = NUM_MSGS_TEST * UART_MSG_SIZE;
  printf("n: %d \n", NUM_MSGS_TEST); 
  printf("UART_MSG_SIZE: %d \n", UART_MSG_SIZE);
  printf("Total bytes: %d \n", total_bytes);
	uart_msg_t* inputs = (uart_msg_t*)malloc(NUM_MSGS_TEST*sizeof(uart_msg_t));
	uart_msg_t* cpu_outputs = (uart_msg_t*)malloc(NUM_MSGS_TEST*sizeof(uart_msg_t));
	uart_msg_t* fpga_outputs = (uart_msg_t*)malloc(NUM_MSGS_TEST*sizeof(uart_msg_t));
	for(int i = 0; i < NUM_MSGS_TEST; i++)
	{
		inputs[i] = input_init(i);
	}
  
  // Do the work on the cpy to compare to
	for(int i = 0; i < NUM_MSGS_TEST; i++)
	{
		cpu_outputs[i] = inputs[i];
	}
	
	// Time things
	time_t t;
	double time_taken;
	
	// Start time
	t = time(NULL); 
  
  // Write messages to FPGA
	for(int i = 0; i < NUM_MSGS_TEST; i++)
	{
    //printf("Write %d\n",i);
    msg_write(&(inputs[i]));
	}
  
  // Read messages from FPGA
	for(int i = 0; i < NUM_MSGS_TEST; i++)
	{
    //printf("Read %d\n",i);
    msg_read(&(fpga_outputs[i]));
	}
  
	// End time
	t = time(NULL) - t; 
	time_taken = ((double)t); //CLOCKS_PER_SEC; // in seconds
	printf("FPGA took %f seconds to execute \n", time_taken);
	double fpga_time = time_taken;
	double fpga_per_iter = fpga_time / (float)NUM_MSGS_TEST;
	printf("FPGA iteration time: %f seconds\n", fpga_per_iter);
	double fpga_bytes_per_sec = (float)total_bytes / fpga_time;
	printf("FPGA bytes per sec: %f B/s\n", fpga_bytes_per_sec);
	
	// Compare the outputs
	for(int i = 0; i < NUM_MSGS_TEST; i++)
	{
		if(compare_bad(i,cpu_outputs[i],fpga_outputs[i]))
		{
			break;
		}
	}

	// Close msgs to/from FPGA
	close_msgs();    
}

