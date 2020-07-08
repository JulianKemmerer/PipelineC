// This is the main program for driving a multithreaded loopback test

#include <math.h>
#include <time.h>
#include <pthread.h>
#define NUM_THREADS 8 // 2 thread per 4 cores?

#include "dma_msg_sw.c"

/*
SINGLE MSG BUFFER IN FPGA - NOT FASTER THAN SINGLE THREAD
n: 80000 
DMA_MSG_SIZE: 4096 
Total bytes: 327680000 
CPU took 0.270000 seconds to execute 
CPU iteration time: 0.000003 seconds
CPU bytes per sec: 1213629629.629630 B/s
FPGA took 3.550000 seconds to execute 
FPGA iteration time: 0.000044 seconds
FPGA bytes per sec: 92304225.352113 B/s
Speedup: 0.076056

250 MHz not really much faster?
n: 80000 
DMA_MSG_SIZE: 4096 
Total bytes: 327680000 
CPU took 0.200000 seconds to execute 
CPU iteration time: 0.000003 seconds
CPU bytes per sec: 1638400000.000000 B/s
FPGA took 3.350000 seconds to execute 
FPGA iteration time: 0.000042 seconds
FPGA bytes per sec: 97814925.373134 B/s
Speedup: 0.059701
*/

// Helper to init an input data
dma_msg_t input_init(int i)
{
	// Randomize values
	dma_msg_t input;
	for(int v=0;v<DMA_MSG_SIZE;v++)
	{
		input.data[v] = i; //rand();
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
  /*
  if(!bad)
  {
    printf("Output %d does match at %d! FPGA: %d, CPU: %d\n", i, 0, fpga.data[0], cpu.data[0]);
  }
  */
	return bad;
}

// How much work to do?
int n = 1;
// Input messages
dma_msg_t* inputs;
// Work output pairs cpu vs fpga(as dma msg too)
dma_msg_t* cpu_outputs;
dma_msg_t* fpga_outputs;

// Thread writing all the dma msgs as fast as possible
void* fpga_writer()
{
  for(int i = 0; i < n; i++)
  {
    // Write DMA bytes to the FPGA
    dma_write(&(inputs[i]));
  }
  pthread_exit(NULL);
}

// Thread reading all the dma msgs as fast as possible
void* fpga_reader()
{
  for(int i = 0; i < n; i++)
  {
    // Read DMA bytes from the FPGA
    dma_read(&(fpga_outputs[i]));
  }
  pthread_exit(NULL);
}

// Do work()'s using the FPGA hardware
void fpga_works()
{
  // Start thread writing inputs into work pipeline
  pthread_t write_thread;
  int rc = pthread_create(&write_thread, NULL, fpga_writer, NULL);
  if (rc){
    printf("ERROR; return code from pthread_create() is %d\n", rc);
    exit(-1);
  }  
  // Start another thread reading outputs from work pipeline
  pthread_t read_thread;
  rc = pthread_create(&read_thread, NULL, fpga_reader, NULL);
  if (rc){
    printf("ERROR; return code from pthread_create() is %d\n", rc);
    exit(-1);
  }
  
  // Wait for reading thread to return
  void* status;
  rc = pthread_join(read_thread, &status);
}

// CPU work done on a single thread
typedef struct cpu_thread_args_t
{
  int start_work_index;
  int num_works;
}cpu_thread_args_t;
void* cpu_thread(void *args_ptr)
{
  // What part of the work to do?
  cpu_thread_args_t* args = (cpu_thread_args_t*)args_ptr;
  int end_work_i = args->start_work_index + args->num_works - 1;
  // Loop and do 'loopback copying'
  for(int work_i=args->start_work_index; work_i<=end_work_i; work_i++)
  {
    cpu_outputs[work_i] = inputs[work_i];
  } 
  
  pthread_exit(NULL);
}

// CPU work done on NUM_THREADS equally partitioned
void cpu_work()
{
  // Allocated threads and vars
  pthread_t threads[NUM_THREADS];
  cpu_thread_args_t thread_args[NUM_THREADS];
  
  // How much work per thread?
  if(n%NUM_THREADS != 0)
  {
     printf("ERROR: Bad number of works per thread\n");
     exit(-1);
  }
  int works_per_thread = n / NUM_THREADS;
  
  // Start threads
  int t;
  for(t=0; t<NUM_THREADS; t++){
    //printf("Creating CPU thread %d\n", t);
    thread_args[t].start_work_index = (works_per_thread*t);
    thread_args[t].num_works = works_per_thread;
    int rc = pthread_create(&threads[t], NULL, cpu_thread, (void*)&thread_args[t]);
    if (rc){
      printf("ERROR; return code from pthread_create() is %d\n", rc);
      exit(-1);
    }
  }
  // Join threads
  void* status;
  for(t=0; t<NUM_THREADS; t++)
  {
    pthread_join(threads[t], &status);
  }
}

// Init + do some work + close
int main(int argc, char **argv) 
{
  // Init direct memory access to/from FPGA
  init_dma();
  
  // Prepare N work inputs, and 2 output pairs (cpu vs fpga)
  if(argc>1)
  {
    char *n_str = argv[1];
    n = atoi(n_str); 
  }
  n = n * NUM_THREADS;
  
  // Prepare work inputs and 2 output pairs cpu vs fpga
  int total_bytes = n * DMA_MSG_SIZE;
  printf("n: %d \n", n); 
  printf("DMA_MSG_SIZE: %d \n", DMA_MSG_SIZE);
  printf("Total bytes: %d \n", total_bytes);
	inputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
	cpu_outputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
	fpga_outputs = (dma_msg_t*)malloc(n*sizeof(dma_msg_t));
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
  cpu_work();
  // End time
  t = clock() - t; 
  time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
  printf("CPU took %f seconds to execute \n", time_taken); 
	double cpu_time = time_taken;
	double cpu_per_iter = cpu_time / (float)n;
	printf("CPU iteration time: %f seconds\n", cpu_per_iter);
	double cpu_bytes_per_sec = (float)total_bytes / cpu_time;
	printf("CPU bytes per sec: %f B/s\n", cpu_bytes_per_sec);

  // Start time
  t = clock(); 
  // Do the work on the FPGA
  fpga_works();
  // End time
  t = clock() - t; 
  time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
  printf("FPGA took %f seconds to execute \n", time_taken);
	double fpga_time = time_taken;
	double fpga_per_iter = fpga_time / (float)n;
	printf("FPGA iteration time: %f seconds\n", fpga_per_iter);
	double fpga_bytes_per_sec = (float)total_bytes / fpga_time;
	printf("FPGA bytes per sec: %f B/s\n", fpga_bytes_per_sec);
  
  // Speedy?
  printf("Speedup: %f\n",cpu_time/fpga_time);  
  
  // Compare the outputs
  int num_bad = 0;
  for(int i = 0; i < n; i++)
  {
    if(compare_bad(i,cpu_outputs[i],fpga_outputs[i]))
    {
      num_bad++;
      if(num_bad>10) break;
    }
  }

  // Close direct memory access to/from FPGA
  close_dma();
  
  /* Last thing that main() should do */
  pthread_exit(NULL);   
}
