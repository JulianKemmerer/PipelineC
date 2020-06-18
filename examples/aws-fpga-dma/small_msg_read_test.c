// This is the main program for driving a small msg read test

#include <math.h>
#include <time.h>

#include "dma_msg_sw.c"
#include "work_sw.c"

#define SMALL DMA_MSG_SIZE

dma_msg_t inc_read_msg(dma_msg_t msg)
{
  // Zero out
  dma_msg_t msg_out;
  for(int v=0;v<DMA_MSG_SIZE;v++)
	{
		msg_out.data[v] = 0;
	}
  // Increment small part of message
  for(int v=0;v<SMALL;v++)
	{
		msg_out.data[v] = msg.data[v] + 1;
	}
	return msg_out;
}

// Helper to compare two output datas
int compare_bad(int i, dma_msg_t expected, dma_msg_t fpga)
{
  int bad = 0;
  for(int v=0;v<DMA_MSG_SIZE;v++)
	{
		if(fpga.data[v] != expected.data[v])
    {
      bad = 1;
      printf("Output %d does not match at %d! FPGA: %d, EXPECTED: %d\n", i, v, fpga.data[v], expected.data[v]);
      break;
    }
	}
	return bad;
}

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init direct memory access to/from FPGA
	init_dma();
	
	// Do something using the function 'work_fpga()'
	// which uses the FPGA to compute the 'work()' function
  dma_msg_t expected_read_msg = DMA_MSG_T_NULL();
  
  // Loop of reading message and writing it back modified
  int n = 10000;
  for(int i = 0; i < n; i++)
	{
		// Read
    dma_msg_t read_msg;
    dma_read(&read_msg);
    // Compare
    if(compare_bad(i,expected_read_msg,read_msg))
		{
			break;
		}
    // Write modified msg
    expected_read_msg = inc_read_msg(read_msg);
    dma_write(&expected_read_msg);
	}

	// Close direct memory access to/from FPGA
	close_dma();    
}
