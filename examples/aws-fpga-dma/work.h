// This describes the work to be done:
// 	Input data format
// 	Output data format
// 	The actual computation 'work' to be done
#pragma once

// Do work on inputs to form outputs
typedef struct work_inputs_t
{
  float values[16];
} work_inputs_t;
typedef struct work_outputs_t
{
  float sum;
} work_outputs_t;
work_outputs_t work(work_inputs_t inputs)
{
	// Sum 16 values 'as parallel as possible' using a binary tree
	//    Level 0: 16 input values
	// 		Level 1: 8 adders in parallel
	//    Level 2: 4 adders in parallel
	//    Level 3: 2 adders in parallel
	//    Level 4: 1 final adder
	
	// PipelineC generates a piplined binary tree of 15 floating point adders
	
	// All the nodes of the tree in arrays so can be written using loops
	// 5 levels, max of 16 values in parallel
	float nodes[5][16]; // Unused elements optimize away
	
	// Assign inputs to level 0
	uint8_t i;
	for(i=0; i<16; i=i+1)
	{
		nodes[0][i] = inputs.values[i];
	}
	
	// Do the computation starting at level 1
	uint8_t n_adds;
	n_adds = 8;
	uint8_t level;
	for(level=1; level<5; level=level+1)
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
	outputs.sum = nodes[4][0];
	return outputs;
}


