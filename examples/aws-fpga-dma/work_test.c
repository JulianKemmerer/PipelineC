// This is the main program for driving the work computation

#include <math.h>
#include <time.h>
#include <pthread.h>
#define NUM_THREADS 8 // 2 thread per 4 cores?

#include "dma_msg_sw.c"
#include "work_sw.c"

// Helper to init a work_inputs_t
float max_val = 100.0;
work_inputs_t work_inputs_init(int i)
{
  // Randomizeish float values to sum
  work_inputs_t inputs;
  for(int v=0;v<N_SUM;v++)
  {
    inputs.values[v] = (float)rand()/(float)(RAND_MAX/max_val); // rand[0..100]
  }
  return inputs;
}

// Helper to compare two output datas
int compare_bad(int i, work_outputs_t cpu, work_outputs_t fpga)
{
  float ep = max_val / 1000.0; // 1/1000th of range;
  if(fabs(fpga.sum - cpu.sum) > ep)
  {
    printf("Output %d does not match! FPGA: %f, CPU: %f\n", i, fpga.sum, cpu.sum);
    printf("  FPGA: 0x%x\n",*(unsigned int*)&fpga.sum);
    printf("  CPU:  0x%x\n",*(unsigned int*)&cpu.sum);
    return 1;
  }
  return 0;
}

// Work inputs (as dma msgs too)
int n_works = 100000 * NUM_THREADS;
//int n_values = n_works * N_SUM;
work_inputs_t* inputs;
dma_msg_t* fpga_input_msgs;
// Work output pairs cpu vs fpga(as dma msg too)
work_outputs_t* cpu_outputs;
dma_msg_t* fpga_output_msgs;
work_outputs_t* fpga_outputs;

// Thread writing all the dma msgs as fast as possible
void* fpga_writer()
{
  for(int i = 0; i < n_works; i++)
  {
    // Write DMA bytes to the FPGA
    dma_write(&(fpga_input_msgs[i]));
  }
  pthread_exit(NULL);
}

// Thread reading all the dma msgs as fast as possible
// And does some accumuating
void* fpga_reader(void* sum_ptr)
{
  float* sum = (float*)sum_ptr;
  *sum = 0.0;
  for(int i = 0; i < n_works; i++)
  {
    // Read DMA bytes from the FPGA
    dma_read(&(fpga_output_msgs[i]));
    // Convert to work output (probably slow memcpy)
    bytes_to_work_outputs_t(&(fpga_output_msgs[i]), &(fpga_outputs[i]));
    // Accumulate
    *sum += fpga_outputs[i].sum;
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
  rc = pthread_create(&read_thread, NULL, fpga_reader, (void*)sum);
  if (rc){
    printf("ERROR; return code from pthread_create() is %d\n", rc);
    exit(-1);
  }
  
  // Wait for reading thread to return after final sum
  void* status;
  rc = pthread_join(read_thread, &status);
}

// CPU work accumuation done on a single thread
typedef struct cpu_thread_args_t
{
  float* thread_sum;
  int start_work_index;
  int num_works;
}cpu_thread_args_t;
void* cpu_thread(void *args_ptr)
{
  // What part of the work to do?
  cpu_thread_args_t* args = (cpu_thread_args_t*)args_ptr;
  *(args->thread_sum) = 0.0;
  int end_work_i = args->start_work_index + args->num_works - 1;
  // Loop and do accumulating
  for(int work_i=args->start_work_index; work_i<=end_work_i; work_i++)
  {
    float work_sum = 0.0;
    for(int i = 0; i<N_SUM; i++)
    {
      work_sum += inputs[work_i].values[i];
    }
    *(args->thread_sum) += work_sum;
    cpu_outputs[work_i].sum = work_sum;
  } 
  
  pthread_exit(NULL);
}

// CPU work done on NUM_THREADS equally partitioned
void cpu_work(float* sum)
{
  // Allocated threads and vars
  pthread_t threads[NUM_THREADS];
  float thread_sums[NUM_THREADS];
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
    thread_args[t].thread_sum = &thread_sums[t];
    thread_args[t].start_work_index = (works_per_thread*t);
    thread_args[t].num_works = works_per_thread;
    int rc = pthread_create(&threads[t], NULL, cpu_thread, (void*)&thread_args[t]);
    if (rc){
      printf("ERROR; return code from pthread_create() is %d\n", rc);
      exit(-1);
    }
  }
  // Join threads and do final accumulate
  *sum = 0.0;
  void* status;
  for(t=0; t<NUM_THREADS; t++)
  {
    pthread_join(threads[t], &status);
    *sum += *(thread_args[t].thread_sum);
  }
}

// Init + do some work + close
int main(int argc, char **argv) 
{
  // Init direct memory access to/from FPGA
  init_dma();
  
  // Prepare work inputs (as dma msgs too), and 2 output pairs cpu vs fpga(as dma msg too)
  inputs = (work_inputs_t*)malloc(n_works*sizeof(work_inputs_t));
  fpga_input_msgs = (dma_msg_t*)malloc(n_works*sizeof(dma_msg_t));
  cpu_outputs = (work_outputs_t*)malloc(n_works*sizeof(work_outputs_t));
  fpga_output_msgs = (dma_msg_t*)malloc(n_works*sizeof(dma_msg_t));
  fpga_outputs = (work_outputs_t*)malloc(n_works*sizeof(work_outputs_t));
  for(int i = 0; i < n_works; i++)
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
