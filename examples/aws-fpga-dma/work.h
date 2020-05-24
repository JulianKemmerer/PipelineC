// This describes the work to be done:
// 	Input data format
// 	Output data format
// 	The actual computation 'work' to be done
#pragma once

// Do work on inputs to form outputs
#define FLOAT_SIZE 4
#define N_SUM (DMA_MSG_SIZE/FLOAT_SIZE)
#define LOG2_DMA_MSG_SIZE_DIV_FLOAT_SIZE_PLUS1 7 //15 //12 //11 //10 //9 // log2(N_SUM)+1
typedef struct work_inputs_t
{
  float values[N_SUM];
} work_inputs_t;
typedef struct work_outputs_t
{
  float sum;
} work_outputs_t;
work_outputs_t work(work_inputs_t inputs)
{
	// Sum N values 'as parallel as possible' using a binary tree
	// Ex. N=16
	//    Level 0: 16 input values
	// 		Level 1: 8 adders in parallel
	//    Level 2: 4 adders in parallel
	//    Level 3: 2 adders in parallel
	//    Level 4: 1 final adder
	// 	PipelineC generates a piplined binary tree of 15 floating point adders
	
	// All the nodes of the tree in arrays so can be written using loops
	// log2(N) levels, max of N values in parallel
	float nodes[LOG2_DMA_MSG_SIZE_DIV_FLOAT_SIZE_PLUS1][N_SUM]; // Unused elements optimize away
	
	// Assign inputs to level 0
	uint32_t i;
	for(i=0; i<N_SUM; i=i+1)
	{
		nodes[0][i] = inputs.values[i];
	}
	
	// Do the computation starting at level 1
	uint32_t n_adds;
	n_adds = N_SUM/2;
	uint32_t level;
	for(level=1; level<LOG2_DMA_MSG_SIZE_DIV_FLOAT_SIZE_PLUS1; level=level+1)
	{	
		// Parallel sums
		for(i=0; i<n_adds; i=i+1)
		{
			nodes[level][i] = nodes[level-1][i*2] + nodes[level-1][(i*2)+1];
		}
		
		// Each level decreases adders by half
		n_adds = n_adds / 2;
	}
	
	// Return the last node in tree
	work_outputs_t outputs;
	outputs.sum = nodes[LOG2_DMA_MSG_SIZE_DIV_FLOAT_SIZE_PLUS1-1][0];
	return outputs;
}


