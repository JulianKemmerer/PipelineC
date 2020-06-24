// This is the main program for driving a loopback test
/*
DMA_MSG_SIZE: 256 
Total bytes: 2560000 
CPU took 0.000000 seconds to execute 
CPU iteration time: 0.000000 seconds
CPU bytes per sec: inf seconds
FPGA took 0.390000 seconds to execute 
FPGA iteration time: 0.000039 seconds
FPGA bytes per sec: 6564102.564103 seconds
Speedup: 0.000000

n: 100000 
DMA_MSG_SIZE: 4096 
Total bytes: 409600000 
CPU took 0.160000 seconds to execute 
CPU iteration time: 0.000002 seconds
CPU bytes per sec: 2560000000.000000 seconds
FPGA took 4.310000 seconds to execute 
FPGA iteration time: 0.000043 seconds
FPGA bytes per sec: 95034802.784223 seconds
Speedup: 0.037123
*/

#include <math.h>
#include <time.h>

#include "dma_msg_sw.c"
#include "work_sw.c"

// Helper to init an input data
dma_msg_t input_init(int i)
{
	// Randomizeish values to sum
	dma_msg_t input;
	for(int v=0;v<DMA_MSG_SIZE;v++)
	{
		input.data[v] = rand();
	}
	return input;
}

// Helper to compare two output datas
int compare_bad(int i, dma_msg_t cpu, dma_msg_t fpga)
{
  int bad = 0;
  for(int v=0;v<DMA_MSG_SIZE;v++)
	{
		if(fpga.data[v] != cpu.data[v])
    {
      bad = 1;
      printf("Output %d does not match at %d! FPGA: %d, CPU: %d\n", i, v, fpga.data[v], cpu.data[v]);
      break;
    }
	}
	return bad;
}

// Do loopback using the FPGA hardware
void loopback_fpga(dma_msg_t* input, dma_msg_t* output)
{
	// Write those DMA bytes to the FPGA
	dma_write(input);
	// Read a DMA bytes back from FPGA
  dma_read(output);
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init direct memory access to/from FPGA
	init_dma();
	
	// Do something using the function 'work_fpga()'
	// which uses the FPGA to compute the 'work()' function
	
	// Prepare N work inputs, and 2 output pairs (cpu vs fpga)
	int n = 1;
  if(argc>1)
  {
    char *n_str = argv[1];
    n = atoi(n_str); 
  }  
  
	int total_bytes = n * DMA_MSG_SIZE;
  printf("n: %d \n", n); 
  printf("DMA_MSG_SIZE: %d \n", DMA_MSG_SIZE);
  printf("Total bytes: %d \n", total_bytes);
	dma_msg_t* inputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
	dma_msg_t* cpu_outputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
	dma_msg_t* fpga_outputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
	for(int i = 0; i < n; i++)
	{
		inputs[i] = input_init(i);
	}
	
	// Time things
	clock_t t;
	double time_taken;
	
	// Start time
	t = clock(); 
	// Do the work on the cpu
	for(int i = 0; i < n; i++)
	{
		cpu_outputs[i] = inputs[i];
	}
	// End time
	t = clock() - t; 
	time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
	printf("CPU took %f seconds to execute \n", time_taken); 
	double cpu_time = time_taken;
	double cpu_per_iter = cpu_time / (float)n;
	printf("CPU iteration time: %f seconds\n", cpu_per_iter);
	double cpu_bytes_per_sec = (float)total_bytes / cpu_time;
	printf("CPU bytes per sec: %f seconds\n", cpu_bytes_per_sec);


	// Start time
	t = clock(); 
	// Do the work on the FPGA
	for(int i = 0; i < n; i++)
	{
    loopback_fpga(&(inputs[i]),&(fpga_outputs[i]));
	}
	// End time
	t = clock() - t; 
	time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
	printf("FPGA took %f seconds to execute \n", time_taken);
	double fpga_time = time_taken;
	double fpga_per_iter = fpga_time / (float)n;
	printf("FPGA iteration time: %f seconds\n", fpga_per_iter);
	double fpga_bytes_per_sec = (float)total_bytes / fpga_time;
	printf("FPGA bytes per sec: %f seconds\n", fpga_bytes_per_sec);
  
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

	// Close direct memory access to/from FPGA
	close_dma();    
}
