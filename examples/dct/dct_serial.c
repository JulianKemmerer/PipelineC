#include "dct.h"

// This is the unrolled version of the original dct copy-and-pasted algorithm
// PipelineC iterations of dctTransformUnrolled are used
// to unroll the calculation serially in O(n^4) time

// Iterators in a struct becomes handy
typedef struct dct_iters_t
{
	dct_iter_t i;
	dct_iter_t j;
	dct_iter_t k;
	dct_iter_t l;
} dct_iters_t;

// Since not always base-2, need special logic to do increment and rollover
typedef struct dct_iter_increment_t
{
	// Pre increment flag if this is last iteration (all iters reset)
	uint1_t done;
	// Incremented iterators
	dct_iters_t iters;
	// Flag if iterators reset
	uint1_t reset_l;
	uint1_t reset_k;
	uint1_t reset_j;
	uint1_t reset_i;
} dct_iter_increment_t;
dct_iter_increment_t dct_iter_increment(dct_iters_t iters)
{
	dct_iter_increment_t rv;
	rv.iters = iters;
		
	// Increment lookup pointer
	// Which iterators should increment/reset this iteration?
	// l
	uint1_t increment_l;
	increment_l = 1; // Increment starts here
	rv.reset_l = (iters.l==(DCT_N-1)) & increment_l;
	// k
	uint1_t increment_k;
	increment_k = rv.reset_l;
	rv.reset_k = (iters.k==(DCT_M-1)) & increment_k;
	// j
	uint1_t increment_j;
	increment_j = rv.reset_k;
	rv.reset_j = (iters.j==(DCT_N-1)) & increment_j;
	// i
	uint1_t increment_i;
	increment_i = rv.reset_j;
	rv.reset_i = (iters.i==(DCT_M-1)) & increment_i;
	
	// Increment iterators as needed
	if(increment_i)
	{
		rv.iters.i = iters.i + 1;
	}
	if(increment_j)
	{
		rv.iters.j = iters.j + 1;
	}
	if(increment_k)
	{
		rv.iters.k = iters.k + 1;
	}
	if(increment_l)
	{
		rv.iters.l = iters.l + 1;
	}		
	
	// Reset iterators as needed
	if(rv.reset_i)
	{
		rv.iters.i = 0;
	}
	if(rv.reset_j)
	{
		rv.iters.j = 0;
	}
	if(rv.reset_k)
	{
		rv.iters.k = 0;
	}
	if(rv.reset_l)
	{
		rv.iters.l = 0;
	}	
	
	
	// Done if increment would reset all iterators
	rv.done = rv.reset_i & rv.reset_j & rv.reset_k & rv.reset_l;
	
	return rv;
}

// (ci * cj) and the cosine multiplier are 
// calculated in advance and stored in lookup tables
typedef struct dct_consts_t
{
	float const_val;
	float cos_val;
} dct_consts_t;



// Dont want constant lookups to be tied into the slow volatile cycle of the summation
// Must, manually for now, isolate lookup related stuff in global functions
// These functions operate in each clock cycle/iteration to do the following:
//		increment iterators as needed
//      do lookups from memory (2 clock BRAM in this case)

// This is the logic for incrementing the iterators when requested
// Instead of local variables holding the iterators and result
// global variables now maintain that state across iterations
dct_iters_t dct_curr_addr;
typedef struct dct_incrementer_t
{
	// Pre increment iterators
	dct_iters_t curr_iters;
	// Info on incremented values
	dct_iter_increment_t increment;
} dct_incrementer_t;
dct_incrementer_t dct_incrementer(uint1_t do_increment)
{
	dct_incrementer_t rv;
	
	// Calculate what an increment would do
	rv.increment = dct_iter_increment(dct_curr_addr);
	
	// Current (pre increment iterators)
	rv.curr_iters = dct_curr_addr;
	
	// Use incremented iterators as current when increment requested	
	if(do_increment)
	{
		dct_curr_addr = rv.increment.iters;
	}
	
	return rv;
}


// This is the logic for looking up constants from BRAM
// In this case BRAM takes two clock cycles to access.
// Instead of actually waiting 2 clocks between lookups do lookups 2 in advance 
// (can do since lookup order known in advance)
// This makes things a bit complicated and essentially like writing HDL

// Current address for the lookup
dct_iters_t dct_lookup_addr;
// Buffer to hold 2 entries in advance
dct_consts_t dct_const_buffer[2];
// Pointer into that buffer
uint2_t dct_const_buffer_offset;
// Flag that the 2 entries in advance is done
uint1_t dct_first_two_done;
// (ci * cj) lookup data
float dct_const_lookup[DCT_M][DCT_N]; // TODO implement const initialization
// Cosine multiplier lookup
float dct_cos_lookup[DCT_M][DCT_N][DCT_M][DCT_N]; // TODO implement const initialization
// Delay incoming valid indicator 2 clocks to align with BRAM output 2 clocks later
uint1_t dct_lookup_valid_delay[2];
// Need to fake the write data since this doesnt include loading the BRAMs (implement later)
float dct_fake_wr1;
float dct_fake_wr2;
// Lookup is always returning the next valid constants
// And will increment when requested
dct_consts_t dct_lookup(uint1_t do_increment)
{
	// Always have values ready in first entry since done 2 in advance
	dct_consts_t rv;	
	rv = dct_const_buffer[0];
		
	// If incrementing this iteration then shift current output out of of buffer
	if(do_increment)
	{
		// Do shift
		dct_const_buffer[0] = dct_const_buffer[1];		
		// Decrement buffer write pointer to reflect shift
		dct_const_buffer_offset = dct_const_buffer_offset - 1;
	}

	// Do lookup from BRAM (2 clock delay) to get constants
	// Start doing this two in advance, then upon each increment request
	// Use valid indicator to know when individual lookups are output
	uint1_t addr_valid;
	addr_valid = 0;
	if(do_increment | !dct_first_two_done)
	{
		// Lookup address is valid
		addr_valid = 1;
		// Record when done with first two in advance
		dct_first_two_done =  dct_first_two_done | // Keep old value
		                     (
							  (dct_lookup_addr.i == 0) &
							  (dct_lookup_addr.j == 0) & 
							  (dct_lookup_addr.k == 0) & 
							  (dct_lookup_addr.l == 1)			  
						     );
	}
	
	// Do lookup with maybe valid address
	// Delay valid output two cycles so 
	// we know when it aligns with the BRAM output
	// Output aligned with [0], insert current addr_valid at end
	uint1_t lookup_2delayed_valid;
	lookup_2delayed_valid = dct_lookup_valid_delay[0];
	dct_lookup_valid_delay[0] = dct_lookup_valid_delay[1];
	dct_lookup_valid_delay[1] = addr_valid;

	// BRAMs for (ci * cj)
	float const_val_2delayed;
	const_val_2delayed = dct_const_lookup_RAM_SP_RF_2(dct_lookup_addr.i, dct_lookup_addr.j, dct_fake_wr1, addr_valid); // Write port doesnt matter
	// BRAMs for cosine multiplier
	float cos_val_2delayed;
	cos_val_2delayed = dct_cos_lookup_RAM_SP_RF_2(dct_lookup_addr.i, dct_lookup_addr.j, dct_lookup_addr.k, dct_lookup_addr.l, dct_fake_wr2, addr_valid); // Write port doesnt matter
	// Doesnt matter
	dct_fake_wr1 = cos_val_2delayed; 
	dct_fake_wr2 = const_val_2delayed;	

	// Put output from lookup at current write offset in buffer
	//  then increment write pointer
	if(lookup_2delayed_valid)
	{
		// Put in buffer
		dct_const_buffer[dct_const_buffer_offset].const_val = const_val_2delayed;
		dct_const_buffer[dct_const_buffer_offset].cos_val = cos_val_2delayed;
		// Increment buffer write pointer after write
		dct_const_buffer_offset = dct_const_buffer_offset + 1;
	}
	
	// Increment LOOKUP addresses when requested	
	// or if still getting first two entries
	if(do_increment | !dct_first_two_done)
	{
		dct_iter_increment_t next_lookup_addr;
		next_lookup_addr = dct_iter_increment(dct_lookup_addr);
		// Use incremented iterators as next lookup address
		dct_lookup_addr = next_lookup_addr.iters;
	}
	
	return rv;
}


// Combine the funcs for lookup and increment
// This is the "isolated global funciton logic" mentioned above
typedef struct dct_lookup_increment_t
{
	// Constant lookup values for this iteration
	dct_consts_t lookup;
	// Iterator values for this iteration
	// from the logic managing incrementing the iterators
	dct_incrementer_t incrementer;
} dct_lookup_increment_t;
dct_lookup_increment_t dct_lookup_increment(uint1_t do_increment)
{
	dct_lookup_increment_t rv;

	// Lookup current constants and maybe ask to get new ones next 
	rv.lookup = dct_lookup(do_increment);
	
	// Read/Increment iterators
	rv.incrementer = dct_incrementer(do_increment);
	
	return rv;
}

// Finally we reach the core of the DCT algorithm.
// Unrolled for your viewing pleasure.

// Input 'matrix' and start=1 to begin calculation
// Input 'matrix' must stay constant until return .done

// 'sum' accumulates over iterations/clocks and should be pipelined
// So 'sum' must be a volatile global variable
// Keep track of when sum is valid and be read+written
volatile uint1_t dct_volatiles_valid;
// sum will temporarily store the sum of cosine signals
volatile float dct_sum;
// dct_result will store the discrete cosine transform
// Signal that this is the iteration containing the 'done' result 
typedef struct dct_done_t
{
	float matrix[DCT_M][DCT_N];
	uint1_t done;
} dct_done_t;
volatile dct_done_t dct_result;
dct_done_t dctTransformUnrolled(dct_pixel_t matrix[DCT_M][DCT_N], uint1_t start)
{
	// Assume not done yet
	dct_result.done = 0;
	
	// Start validates volatiles
	if(start)
	{
		dct_volatiles_valid = 1;
	}
	
	// Global func to handle getting to BRAM
	//     1) Lookup constants from BRAM (using iterators)
	//     2) Increment iterators
	// Returns next iterators and constants and will increment when requested
	dct_lookup_increment_t lookup_increment;
	uint1_t do_increment;
	// Only increment when volatiles valid
	do_increment = dct_volatiles_valid;
	lookup_increment = dct_lookup_increment(do_increment);
	
	// Unpack struct for ease of reading calculation code below
	float const_val;
	const_val = lookup_increment.lookup.const_val;
	float cos_val;
	cos_val = lookup_increment.lookup.cos_val;
	dct_iter_t i;
	i = lookup_increment.incrementer.curr_iters.i;
	dct_iter_t j;
	j = lookup_increment.incrementer.curr_iters.j;
	dct_iter_t k;
	k = lookup_increment.incrementer.curr_iters.k;
	dct_iter_t l;
	l = lookup_increment.incrementer.curr_iters.l;
	uint1_t reset_k;
	reset_k = lookup_increment.incrementer.increment.reset_k;
	uint1_t reset_l;
	reset_l = lookup_increment.incrementer.increment.reset_l;
	uint1_t done;
	done = lookup_increment.incrementer.increment.done;
	
	
	// Do math for this volatile iteration only when
	// can safely read+write volatiles
	if(dct_volatiles_valid)
	{
		// ~~~ The primary calculation ~~~:
		// 1) Float * cosine constant from lookup table  
		float dct1;
		dct1 = (float)matrix[k][l] * cos_val;
		// 2) Increment sum
		dct_sum = dct_sum + dct1;
		// 3) constant * Float and assign into the output matrix
		dct_result.matrix[i][j] = const_val * dct_sum;
		
		// Sum accumulates during the k and l loops
		// So reset when they are rolling over
		if(reset_k & reset_l)
		{
			dct_sum = 0.0;
		}
		
		// Done yet?
		dct_result.done = done;
		
		// Reset volatiles once done
		if(done)
		{
			dct_volatiles_valid = 0;
		}
	}
	
	return dct_result;
}


/*
// Cosine multiplier lookup table for unrolled version of above algorithm 
// (as opposed to actually doing cosine operation)
float dctCosLookup(dct_iter_t i_in, dct_iter_t j_in, dct_iter_t k_in, dct_iter_t l_in)
{
	// table evaluates to a constant
    float table[DCT_M][DCT_N][DCT_M][DCT_N];
    dct_iter_t i;
    dct_iter_t j;
    dct_iter_t k;
    dct_iter_t l;
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
			 for (k = 0; k < DCT_M; k=k+1) { 
                for (l = 0; l < DCT_N; l=l+1) { 
                    table[i][j][k][l] = ( cos((float)((2 * k + 1) * i) * DCT_PI / (float)(2 * DCT_M)) *  
										  cos((float)((2 * l + 1) * j) * DCT_PI / (float)(2 * DCT_N))
										);
                }
            } 
        } 
    }
    
    // Lookup into that table (LUTS)
    return table[i_in][j_in][k_in][l_in]; 
}

// (ci * cj) lookup table for unrolled version of above algorithm 
float dctConstLookup(dct_iter_t i_in, dct_iter_t j_in)
{
	// table evaluates to a constant
    float table[DCT_M][DCT_N];
    dct_iter_t i;
    dct_iter_t j;
    for (i = 0; i < DCT_M; i=i+1) { 
        for (j = 0; j < DCT_N; j=j+1) { 
			float ci;
			float cj;
			if (i == 0) 
                ci = 1.0 / sqrt(DCT_M); 
            else
                ci = sqrt(2) / sqrt(DCT_M);
            if (j == 0) 
                cj = 1.0 / sqrt(DCT_N);
            else
                cj = sqrt(2) / sqrt(DCT_N);
			table[i][j] = (ci*cj);
        } 
    }
    
    // Lookup into that table (LUTS)
    return table[i_in][j_in];
}# REPLACED LUTS WITH BRAMS ABOVE */
