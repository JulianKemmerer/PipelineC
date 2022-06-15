// gcc uart_loopback_test.c -o uart_loopback_test -I ../
// sudo ./uart_loopback_test 100

#include <math.h>
#include <time.h> // TODO fix time measurements

// 'Software' side of uart message sending include
#include "uart/uart_msg_sw.c"

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

// Do loopback using the FPGA hardware
void loopback_fpga(uart_msg_t* input, uart_msg_t* output)
{
	// Write bytes to the FPGA
	msg_write(input);
	// Read bytes back from FPGA
  msg_read(output);
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init msgs to/from FPGA
	init_msgs();
	
	// Do something using the function 'work_fpga()'
	// which uses the FPGA to compute the 'work()' function
	
	// Prepare N work inputs, and 2 output pairs (cpu vs fpga)
	int n = 1;
  if(argc>1)
  {
    char *n_str = argv[1];
    n = atoi(n_str); 
  }  
  
	int total_bytes = n * UART_MSG_SIZE;
  printf("n: %d \n", n); 
  printf("UART_MSG_SIZE: %d \n", UART_MSG_SIZE);
  printf("Total bytes: %d \n", total_bytes);
	uart_msg_t* inputs = (uart_msg_t*)malloc(n*sizeof(uart_msg_t));
	uart_msg_t* cpu_outputs = (uart_msg_t*)malloc(n*sizeof(uart_msg_t));
	uart_msg_t* fpga_outputs = (uart_msg_t*)malloc(n*sizeof(uart_msg_t));
	for(int i = 0; i < n; i++)
	{
		inputs[i] = input_init(i);
	}
	
	// Time things
	time_t t;
	double time_taken;
	
	// Start time
	t = time(NULL); 
	// Do the work on the cpu
	for(int i = 0; i < n; i++)
	{
		cpu_outputs[i] = inputs[i];
	}
	// End time
	t = time(NULL) - t; 
	time_taken = ((double)t); //CLOCKS_PER_SEC; // in seconds
	printf("CPU took %f seconds to execute \n", time_taken); 
	double cpu_time = time_taken;
	double cpu_per_iter = cpu_time / (float)n;
	printf("CPU iteration time: %f seconds\n", cpu_per_iter);
	double cpu_bytes_per_sec = (float)total_bytes / cpu_time;
	printf("CPU bytes per sec: %f B/s\n", cpu_bytes_per_sec);


	// Start time
	t = time(NULL); 
	// Do the work on the FPGA
	for(int i = 0; i < n; i++)
	{
    loopback_fpga(&(inputs[i]),&(fpga_outputs[i]));
	}
	// End time
	t = time(NULL) - t; 
	time_taken = ((double)t); //CLOCKS_PER_SEC; // in seconds
	printf("FPGA took %f seconds to execute \n", time_taken);
	double fpga_time = time_taken;
	double fpga_per_iter = fpga_time / (float)n;
	printf("FPGA iteration time: %f seconds\n", fpga_per_iter);
	double fpga_bytes_per_sec = (float)total_bytes / fpga_time;
	printf("FPGA bytes per sec: %f B/s\n", fpga_bytes_per_sec);
  
  // Speedy?
  printf("Speedup: %f\n",cpu_time/fpga_time);  
	
	// Compare the outputs
	for(int i = 0; i < n; i++)
	{
		if(compare_bad(i,cpu_outputs[i],fpga_outputs[i]))
		{
			break;
		}
	}

	// Close msgs to/from FPGA
	close_msgs();    
}

