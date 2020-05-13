// This is the main program for driving a loopback test

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
      printf("Output %d does not match at %d! FPGA: %u, CPU: %u\n", i, fpga.data[v], cpu.data[v]);
      break;
    }
	}
	return bad;
}

// Do loopback using the FPGA hardware
dma_msg_t loopback_fpga(dma_msg_t input)
{
	// Write those DMA bytes to the FPGA
	dma_write(input);
	// Read a DMA bytes back from FPGA
	dma_msg_t read_msg;
	read_msg = dma_read();
	return read_msg;
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init direct memory access to/from FPGA
	init_dma();
	
	// Do something using the function 'work_fpga()'
	// which uses the FPGA to compute the 'work()' function
	
	// Prepare N work inputs, and 2 output pairs (cpu vs fpga)
	int n = 100000;
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

	// Start time
	t = clock(); 
	// Do the work on the FPGA
	for(int i = 0; i < n; i++)
	{
		fpga_outputs[i] = loopback_fpga(inputs[i]);
	}
	// End time
	t = clock() - t; 
  time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
  printf("FPGA took %f seconds to execute \n", time_taken);
  double fpga_time = time_taken;
  
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
