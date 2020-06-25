// This is the main program for driving a multithreaded loopback test

#include <math.h>
#include <time.h>
#include <pthread.h>
#define NUM_THREADS 8 // 2 thread per 4 cores?

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

// Input messages
dma_msg_t* inputs;
// Work output pairs cpu vs fpga(as dma msg too)
dma_msg_t* cpu_outputs;
dma_msg_t* fpga_outputs;

// Thread writing all the dma msgs as fast as possible
void* fpga_writer()
{
  for(int i = 0; i < n_works; i++)
  {
    // Write DMA bytes to the FPGA
    dma_write(&(inputs[i]));
  }
  pthread_exit(NULL);
}

// Thread reading all the dma msgs as fast as possible
void* fpga_reader(void* sum_ptr)
{
  for(int i = 0; i < n_works; i++)
  {
    // Read DMA bytes from the FPGA
    dma_read(&(fpga_outputs[i]));
  }
  pthread_exit(NULL);
}

// Do work()'s using the FPGA hardware
void fpga_works(float* sum)
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
  if(n_works%NUM_THREADS != 0)
  {
     printf("ERROR: Bad number of works per thread\n");
     exit(-1);
  }
  int works_per_thread = n_works / NUM_THREADS;
  
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
	int n = 1;
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
  float cpu_sum = 0.0;
  cpu_work();
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
  float fpga_sum = 0.0;
  fpga_works();
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
  int num_bad = 0;
  for(int i = 0; i < n_works; i++)
  {
    if(compare_bad(i,cpu_outputs[i],fpga_outputs[i]))
    {
      num_bad++;
      if(num_bad>5) break;
    }
  }

  // Close direct memory access to/from FPGA
  close_dma();
  
  /* Last thing that main() should do */
  pthread_exit(NULL);   
}
