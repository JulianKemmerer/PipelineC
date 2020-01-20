// This is the main program for driving the work computation

#include "dma_msg_sw.c"
#include "work_sw.c"

// Helper to init an input data
float max_val = 100.0;
work_inputs_t work_inputs_init(int i)
{
	// Randomizeish float values to sum
	work_inputs_t inputs;
	for(int v=0;v<16;v++)
	{
		inputs.values[v] = (float)rand()/(float)(RAND_MAX/max_val); // rand[0..100]
	}
	return inputs;
}

// Helper to compare two output datas
void compare(int i, work_outputs_t cpu, work_outputs_t fpga)
{
	float ep = max_val / 10000.0; // 1/10000th of range;
	if(abs(fpga.sum - cpu.sum) > ep)
	{
		prinf("Output %d does not match! FPGA: %f, CPU: %f\n", i, fpga.sum, cpu.sum);
	}
}

// Do work() using the FPGA hardware
work_outputs_t work_fpga(work_inputs_t inputs)
{
	// Convert input into bytes
	dma_msg_t write_msg;
	write_msg = inputs_to_bytes(inputs);
	// Write those DMA bytes to the FPGA
	dma_write(write_msg);
	// Read a DMA bytes back from FPGA
	dma_msg_t read_msg;
	read_msg = dma_read();
	// Convert bytes to outputs and return
	work_outputs_t work_outputs;
	work_outputs = bytes_to_outputs(read_msg);
	return work_outputs;
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
	work_inputs_t* inputs = (work_inputs_t*)malloc(n*sizeof(work_inputs_t));
	work_outputs_t* cpu_outputs = (work_outputs_t*)malloc(n*sizeof(work_outputs_t));
	work_outputs_t* fpga_outputs = (work_outputs_t*)malloc(n*sizeof(work_outputs_t));
	for(int i = 0; i < n; i++)
	{
		inputs[i] = work_inputs_init(i);
	}
	
	// Do the work on the cpu
	for(int i = 0; i < n; i++)
	{
		cpu_outputs[i] = work(inputs[i]);
	}
	
	// Do the work on the FPGA
	for(int i = 0; i < n; i++)
	{
		fpga_outputs[i] = work_fpga(inputs[i]);
	}
	
	// Compare the outputs
	for(int i = 0; i < n; i++)
	{
		compare(i,cpu_outputs[i],fpga_outputs[i]);
	}

	// Close direct memory access to/from FPGA
	close_dma();    
}
