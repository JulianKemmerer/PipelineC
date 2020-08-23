// This is the main program for driving the work computation
// gcc -I ../../../../ -Wall -pthread work_test.c -o work_test

#include <math.h>
#include <time.h> // Fix time measurement code
#include <pthread.h>
#define NUM_THREADS 8 // for cpu testing, 2 threads per 4 cores?

// Use uart to send/receive messages
#include "../uart/uart_msg_sw.c"

// Definition of work related stuff
#include "work.h"

// Software specific helper functions to convert msg bytes to/from 'work' inputs/outputs
// TODO gen all includes inside work_*_bytes.h
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/int16_t_bytes_t.h/int16_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/work_inputs_t_bytes_t.h/work_inputs_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/work_outputs_t_bytes_t.h/work_outputs_t_bytes.h"

// Work inputs
int n = 1;
work_inputs_t* inputs;
uart_msg_t* fpga_input_msgs;
// Work output pairs cpu vs fpga(as msg too)
work_outputs_t* cpu_outputs;
uart_msg_t* fpga_output_msgs;
work_outputs_t* fpga_outputs;

// Thread writing all the input msgs as fast as possible
void* fpga_writer()
{
  for(int i = 0; i < n; i++)
  {
    // Write bytes to the FPGA
    msg_write(&(fpga_input_msgs[i]));
  }
  pthread_exit(NULL);
}

// Thread reading all the output msgs as fast as possible
void* fpga_reader()
{
  for(int i = 0; i < n; i++)
  {
    // Read bytes from the FPGA
    msg_read(&(fpga_output_msgs[i]));
    // Convert to work output (probably slow memcpy)
    bytes_to_work_outputs_t(&(fpga_output_msgs[i].data[0]), &(fpga_outputs[i]));
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
  
  // Wait for reading thread to return after final msg
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
  // Loop and do accumulating
  for(int work_i=args->start_work_index; work_i<=end_work_i; work_i++)
  {
    work_cpu(&(inputs[work_i]),&(cpu_outputs[work_i]));
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
  // Join threads and do final accumulate
  void* status;
  for(t=0; t<NUM_THREADS; t++)
  {
    pthread_join(threads[t], &status);
  }
}

// Init + do some work + close
int main(int argc, char **argv) 
{
  // Init msgs to/from FPGA
  init_msgs();
  
  // Prepare N work inputs, and 2 output pairs (cpu vs fpga)
  if(argc>1)
  {
    char *n_str = argv[1];
    n = atoi(n_str); 
  }
  n = n * NUM_THREADS;
  
  // Prepare work inputs (as msgs too), and 2 output pairs cpu vs fpga(as msg too)
  inputs = (work_inputs_t*)malloc(n*sizeof(work_inputs_t));
  fpga_input_msgs = (uart_msg_t*)malloc(n*sizeof(uart_msg_t));
  cpu_outputs = (work_outputs_t*)malloc(n*sizeof(work_outputs_t));
  fpga_output_msgs = (uart_msg_t*)malloc(n*sizeof(uart_msg_t));
  fpga_outputs = (work_outputs_t*)malloc(n*sizeof(work_outputs_t));
  for(int i = 0; i < n; i++)
  {
    inputs[i] = work_inputs_init(i);
    work_inputs_t_to_bytes(&(inputs[i]), &(fpga_input_msgs[i].data[0]));
  }
  
  // Time things
  clock_t t;
  double time_taken;
  
  // Start time
  t = clock(); 
  // Do the work on the cpu
  float cpu_sum = 0.0;
  cpu_work(&cpu_sum);
  // End time
  t = clock() - t; 
  time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
  printf("CPU took %f seconds to execute \n", time_taken); 
  double cpu_time = time_taken;

  // Start time
  t = clock(); 
  // Do the work on the FPGA
  float fpga_sum = 0.0;
  fpga_works(&fpga_sum);
  // End time
  t = clock() - t; 
  time_taken = ((double)t)/CLOCKS_PER_SEC; // in seconds
  printf("FPGA took %f seconds to execute \n", time_taken);
  double fpga_time = time_taken;  
  
  // Speedy?
  printf("Speedup: %f\n",cpu_time/fpga_time);  
  
  // Compare the outputs
  int num_bad = 0;
  for(int i = 0; i < n; i++)
  {
    if(compare_bad(i,cpu_outputs[i],fpga_outputs[i]))
    {
      num_bad++;
      if(num_bad>5) break;
    }
  }

  // Close direct memory access to/from FPGA
  close_msgs();
  
  /* Last thing that main() should do */
  pthread_exit(NULL);   
}
