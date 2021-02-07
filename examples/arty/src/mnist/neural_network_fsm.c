#include "uintN_t.h"
#include "wire.h"
#include "neural_network.h"

/*
for (i = 0; i < MNIST_LABELS; i+=1) 
{
    a.activations[i] = network.b[i];
    for (j = 0; j < MNIST_IMAGE_SIZE; j+=1) 
    {
        a.activations[i] += network.W[i][j] * PIXEL_SCALE(image.pixels[j]);
    }
}
*/
// Keep host memory loading / communication separate from computation NN core
// Memories face both sides computation and communication
// For now these memories are single port (only a read OR write at a time)

// Pixel memory (input data memory)
// Input
typedef struct nn_to_input_mem_t
{
  uint1_t ready;
  pixel_iter_t j;
  uint1_t valid;
}nn_to_input_mem_t;
nn_to_input_mem_t NN_TO_INPUT_MEM_T_NULL()
{
  nn_to_input_mem_t rv;
  rv.ready = 0;
  rv.j = 0;
  rv.valid = 0;
  return rv;
}
#include "nn_to_input_mem_t_array_N_t.h"
// Output
typedef struct input_mem_to_nn_t
{
  uint1_t ready;
  pixel_t pixel;
  uint1_t valid;
}input_mem_to_nn_t;
#include "input_mem_to_nn_t_array_N_t.h"
// Input
typedef struct comms_to_input_mem_t
{
  uint1_t wr_en;
  pixel_iter_t j;
  pixel_t pixel;
}comms_to_input_mem_t;
/*
// Output
typedef struct input_mem_to_comms_t
{
}input_mem_to_comms_t;
*/
// Global ports/wires
input_mem_to_nn_t input_mem_to_nn;
#include "input_mem_to_nn_clock_crossing.h"
nn_to_input_mem_t nn_to_input_mem;
#include "nn_to_input_mem_clock_crossing.h"
/*typedef struct input_mem_t{
  input_mem_to_comms_t to_comms;
}input_mem_t;*/
#pragma MAIN input_mem
void input_mem(comms_to_input_mem_t from_comms)
{
  static pixel_t pixels[MNIST_IMAGE_SIZE];
  //input_mem_t o;
  
  nn_to_input_mem_t from_nn;
  input_mem_to_nn_t to_nn;
  
  WIRE_READ(nn_to_input_mem_t, from_nn, nn_to_input_mem)
  
  // Single cycle pass through read
  to_nn.ready = from_nn.ready;
  to_nn.pixel = pixels[from_nn.j];
  to_nn.valid = from_nn.valid;
  
  // And hack comms write too
  if(from_comms.wr_en)
  {
    pixels[from_comms.j] = from_comms.pixel;
  }

  WIRE_WRITE(input_mem_to_nn_t, input_mem_to_nn, to_nn)
}

// Scratch memory in this simple example need only a few registers (for accumulation,comparing)
// Is a register file /dual/many ported, minimal number of regs so OK for now
#define scratch_reg_t float
#define NUM_SCRATCH 2
// Input
typedef struct nn_to_scratch_mem_t
{
  uint1_t ready[NUM_SCRATCH];
  scratch_reg_t r[NUM_SCRATCH];
  uint1_t wr_en[NUM_SCRATCH];
  uint1_t valid[NUM_SCRATCH];
} nn_to_scratch_mem_t;
nn_to_scratch_mem_t NN_TO_SCRATCH_MEM_T_NULL()
{
  nn_to_scratch_mem_t rv;
  uint32_t i;
  for(i=0;i<NUM_SCRATCH;i+=1)
  {
    rv.ready[i] = 0;
    rv.r[i] = 0;
    rv.wr_en[i] = 0;
    rv.valid[i] = 0;
  }
  return rv;
}
#include "nn_to_scratch_mem_t_array_N_t.h"
// Output
typedef struct scratch_mem_to_nn_t
{
  uint1_t ready[NUM_SCRATCH];
  scratch_reg_t r[NUM_SCRATCH];
  uint1_t valid[NUM_SCRATCH];
}scratch_mem_to_nn_t;
#include "scratch_mem_to_nn_t_array_N_t.h"
// Input
/*typedef struct comms_to_scratch_mem_t
{
  uint1_t wr_en;
  pixel_iter_t j;
  pixel_t pixel;
}comms_to_scratch_mem_t;*/
// Output
typedef struct scratch_mem_to_comms_t
{
  scratch_reg_t r[NUM_SCRATCH];
}scratch_mem_to_comms_t;
// Global ports/wires
scratch_mem_to_nn_t scratch_mem_to_nn;
#include "scratch_mem_to_nn_clock_crossing.h"
nn_to_scratch_mem_t nn_to_scratch_mem;
#include "nn_to_scratch_mem_clock_crossing.h"
typedef struct scratch_mem_t{
  scratch_mem_to_comms_t to_comms;
}scratch_mem_t;
#pragma MAIN scratch_mem
scratch_mem_t scratch_mem()
{
  static scratch_reg_t r[NUM_SCRATCH];
  scratch_mem_t o;
  
  // Hacky comms read
  o.to_comms.r = r;
  
  nn_to_scratch_mem_t from_nn;
  scratch_mem_to_nn_t to_nn;
  
  WIRE_READ(nn_to_scratch_mem_t, from_nn, nn_to_scratch_mem)

  // Single cycle pass through read
  uint32_t i;
  for(i=0;i<NUM_SCRATCH;i+=1)
  {
    to_nn.ready[i] = from_nn.ready[i];
    to_nn.r[i] = r[i];
    if(from_nn.wr_en[i] & from_nn.valid[i] & to_nn.ready[i])
    {
      r[i] = from_nn.r[i];
    }
    to_nn.valid[i] = from_nn.valid[i];
  }

  WIRE_WRITE(scratch_mem_to_nn_t, scratch_mem_to_nn, to_nn)
  
  return o;
}


// Bias and weight memories are read only, compile time constants
//(fake write port for now until syntax parsing done)

// Bias memory
// Input
typedef struct nn_to_bias_mem_t
{
  uint1_t ready;
  label_iter_t i;
  uint1_t valid;
}nn_to_bias_mem_t;
nn_to_bias_mem_t NN_TO_BIAS_MEM_T_NULL()
{
  nn_to_bias_mem_t rv;
  rv.ready = 0;
  rv.i = 0;
  rv.valid = 0;
  return rv;
}
#include "nn_to_bias_mem_t_array_N_t.h"
// Output
typedef struct bias_mem_to_nn_t
{
  uint1_t ready;
  float bias;
  uint1_t valid;
}bias_mem_to_nn_t;
#include "bias_mem_to_nn_t_array_N_t.h"
// Input
typedef struct comms_to_bias_mem_t
{
  uint1_t wr_en;
  label_iter_t i;
  float bias;
}comms_to_bias_mem_t;
/*
// Output
typedef struct bias_mem_to_comms_t
{
}bias_mem_to_comms_t;
*/
// Global ports/wires
bias_mem_to_nn_t bias_mem_to_nn;
#include "bias_mem_to_nn_clock_crossing.h"
nn_to_bias_mem_t nn_to_bias_mem;
#include "nn_to_bias_mem_clock_crossing.h"
/*typedef struct bias_mem_t{
  bias_mem_to_comms_t to_comms;
}bias_mem_t;*/
#pragma MAIN bias_mem
void bias_mem(comms_to_bias_mem_t from_comms)
{
  static float biases[MNIST_LABELS];
  //bias_mem_t o;
  
  nn_to_bias_mem_t from_nn;
  bias_mem_to_nn_t to_nn;
  
  WIRE_READ(nn_to_bias_mem_t, from_nn, nn_to_bias_mem)
  
  // Single cycle pass through read
  to_nn.ready = from_nn.ready;
  to_nn.bias = biases[from_nn.i];
  to_nn.valid = from_nn.valid;
  
  // And hack comms write too
  if(from_comms.wr_en)
  {
    biases[from_comms.i] = from_comms.bias;
  }

  WIRE_WRITE(bias_mem_to_nn_t, bias_mem_to_nn, to_nn)
}


// Weights memory
// Input
typedef struct nn_to_weights_mem_t
{
  uint1_t ready;
  label_iter_t i;
  pixel_iter_t j;
  uint1_t valid;
}nn_to_weights_mem_t;
nn_to_weights_mem_t NN_TO_WEIGHTS_MEM_T_NULL()
{
  nn_to_weights_mem_t rv;
  rv.ready = 0;
  rv.i = 0;
  rv.j = 0;
  rv.valid = 0;
  return rv;
}
#include "nn_to_weights_mem_t_array_N_t.h"
// Output
typedef struct weights_mem_to_nn_t
{
  uint1_t ready;
  float weight;
  uint1_t valid;
}weights_mem_to_nn_t;
#include "weights_mem_to_nn_t_array_N_t.h"
// Input
typedef struct comms_to_weights_mem_t
{
  uint1_t wr_en;
  label_iter_t i;
  pixel_iter_t j;
  float weight;
}comms_to_weights_mem_t;
/*
// Output
typedef struct weights_mem_to_comms_t
{
}weights_mem_to_comms_t;
*/
// Global ports/wires
weights_mem_to_nn_t weights_mem_to_nn;
#include "weights_mem_to_nn_clock_crossing.h"
nn_to_weights_mem_t nn_to_weights_mem;
#include "nn_to_weights_mem_clock_crossing.h"
/*typedef struct weights_mem_t{
  weights_mem_to_comms_t to_comms;
}weights_mem_t;*/
#pragma MAIN weights_mem
void weights_mem(comms_to_weights_mem_t from_comms)
{
  static float weights[MNIST_LABELS][MNIST_IMAGE_SIZE];
  //weights_mem_t o;
  
  nn_to_weights_mem_t from_nn;
  weights_mem_to_nn_t to_nn;
  
  WIRE_READ(nn_to_weights_mem_t, from_nn, nn_to_weights_mem)
  
  // Single cycle pass through read
  to_nn.ready = from_nn.ready;
  to_nn.weight = weights[from_nn.i][from_nn.j];
  to_nn.valid = from_nn.valid;
  
  // And hack comms write too
  if(from_comms.wr_en)
  {
    weights[from_comms.i][from_comms.j] = from_comms.weight;
  }

  WIRE_WRITE(weights_mem_to_nn_t, weights_mem_to_nn, to_nn)
}

// Output activations mem is only used by computaiton
// (actual NN output is the index of the maximally activated neuron, not its value)
// Input
typedef struct nn_to_output_mem_t
{
  uint1_t ready;
  label_iter_t i;
  float value;
  uint1_t wr_en;
  uint1_t valid;
}nn_to_output_mem_t;
nn_to_output_mem_t NN_TO_OUTPUT_MEM_T_NULL()
{
  nn_to_output_mem_t rv;
  rv.ready = 0;
  rv.i = 0;
  rv.value = 0.0;
  rv.wr_en = 0;
  rv.valid = 0;
  return rv;
}
#include "nn_to_output_mem_t_array_N_t.h"
// Output
typedef struct output_mem_to_nn_t
{
  uint1_t ready;
  float value;
  uint1_t valid;
}output_mem_to_nn_t;
#include "output_mem_to_nn_t_array_N_t.h"
// Global ports/wires
output_mem_to_nn_t output_mem_to_nn;
#include "output_mem_to_nn_clock_crossing.h"
nn_to_output_mem_t nn_to_output_mem;
#include "nn_to_output_mem_clock_crossing.h"
#pragma MAIN output_mem
void output_mem()
{
  static float activations[MNIST_LABELS];
  
  nn_to_output_mem_t from_nn;
  output_mem_to_nn_t to_nn;
  
  WIRE_READ(nn_to_output_mem_t, from_nn, nn_to_output_mem)
  
  // Single cycle pass through read
  to_nn.ready = from_nn.ready;
  to_nn.value = activations[from_nn.i];
  if(from_nn.wr_en & from_nn.valid & to_nn.ready)
  {
    activations[from_nn.i] = from_nn.value;
  }
  to_nn.valid = from_nn.valid;

  WIRE_WRITE(output_mem_to_nn_t, output_mem_to_nn, to_nn)
}

// Only computation talks to processing element
typedef enum pe_op_t
{
  DIV,
  MULT,
  ADD,
  GT
}pe_op_t;
// Input
typedef struct nn_to_pe_t
{
  uint1_t ready;
  float arg0;
  float arg1;
  pe_op_t op;
  uint1_t valid;
}nn_to_pe_t;
nn_to_pe_t NN_TO_PE_T_NULL()
{
  nn_to_pe_t rv;
  rv.ready = 0;
  rv.arg0 = 0.0;
  rv.arg1 = 0.0;
  rv.op = DIV;
  rv.valid = 0;
  return rv;
}
#include "nn_to_pe_t_array_N_t.h"
// Output
typedef struct pe_to_nn_t
{
  uint1_t ready;
  float value;
  uint1_t value_bool;
  uint1_t valid;
}pe_to_nn_t;
#include "pe_to_nn_t_array_N_t.h"
// Global ports/wires
pe_to_nn_t pe_to_nn;
#include "pe_to_nn_clock_crossing.h"
nn_to_pe_t nn_to_pe;
#include "nn_to_pe_clock_crossing.h"
#pragma MAIN processing_element
void processing_element()
{  
  nn_to_pe_t from_nn;
  pe_to_nn_t to_nn;
  
  // No state, so this function can be pipelined
  to_nn.ready = 1; // Always ready for input, TODO overflow on output
  
  WIRE_READ(nn_to_pe_t, from_nn, nn_to_pe)
  
  to_nn.value_bool = 0;
  if(from_nn.op == DIV)
  {
    to_nn.value = from_nn.arg0 / from_nn.arg1;
  }
  else if(from_nn.op == MULT)
  {
    to_nn.value = from_nn.arg0 * from_nn.arg1;
  }
  else if(from_nn.op == ADD)
  {
    to_nn.value = from_nn.arg0 + from_nn.arg1;
  }
  else // GT
  {
    to_nn.value_bool = from_nn.arg0 > from_nn.arg1;
    to_nn.value = 0.0;
  }
  
  to_nn.valid = from_nn.valid;

  WIRE_WRITE(pe_to_nn_t, pe_to_nn, to_nn)
}

// Sub state machines

typedef enum pixel_scaler_state_t
{
  IDLE,
  READ_INPUT_PIXEL,
  DO_PE_OP, // DIVIDE by 255.0
  WRITE_SCALED_VALUE_TO_SCRATCH
}pixel_scaler_state_t;
typedef struct pixel_scaler_t
{
  nn_to_input_mem_t to_input_mem;
  nn_to_pe_t to_pe;
  nn_to_scratch_mem_t to_scratch_mem;
  uint1_t done;
}pixel_scaler_t;
// R[0] = pixel[j] / 255.0
pixel_scaler_t pixel_scaler(uint1_t start, pixel_iter_t j, input_mem_to_nn_t from_input_mem, pe_to_nn_t from_pe, scratch_mem_to_nn_t from_scratch_mem, uint1_t ready)
{
  static pixel_scaler_state_t state;
  static uint1_t req_in_fight;
  pixel_scaler_t o;
  o.to_input_mem = NN_TO_INPUT_MEM_T_NULL();
  o.to_pe = NN_TO_PE_T_NULL();
  o.to_scratch_mem = NN_TO_SCRATCH_MEM_T_NULL();
  o.done = 0;
  
  if(state==IDLE)
  {
    if(start)
    {
      state = READ_INPUT_PIXEL;
    }
  }
  // Pass through 'if' single cycle start
  if(state==READ_INPUT_PIXEL)
  {
    // Make request
    if(!req_in_fight)
    {
      o.to_input_mem.j = j; // address
      o.to_input_mem.valid = 1;
      if(from_input_mem.ready) // & to_input_mem.valid==1 known
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready for pixel from mem if PE is ready to receive it
      // Go to next state if have valid pixel from input mem
      // next state is where ready is signaled (or not)
      if(from_input_mem.valid)
      {
        req_in_fight = 0; // Response now available
        state = DO_PE_OP; // Next state
      }
    }
  }
  // Pass through 'if' to PE_OP since could get pixel in same cycle
  if(state==DO_PE_OP)
  {
    // Make request
    if(!req_in_fight)
    {
      // From input mem into PE
      o.to_pe.arg0 = from_input_mem.pixel;
      o.to_pe.arg1 = 255.0;
      o.to_pe.op = DIV;
      o.to_pe.valid = from_input_mem.valid;
      o.to_input_mem.ready = from_pe.ready;
      if(o.to_pe.valid & from_pe.ready)
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready for PE result if scratch mem ready 
      // Go to next state if have valid PE ouput, where ready is signaled (or not)
      if(from_pe.valid)
      {
        req_in_fight = 0; // Got response
        state = WRITE_SCALED_VALUE_TO_SCRATCH; // Next state
      }
    }
  }
  // Pass through 'if' to since could get result in same cycle
  if(state==WRITE_SCALED_VALUE_TO_SCRATCH)
  {
    // Make request
    if(!req_in_fight)
    {
      // From PE into scratch mem R[0]
      o.to_scratch_mem.r[0] = from_pe.value;
      o.to_scratch_mem.wr_en[0] = 1; // write
      o.to_scratch_mem.valid[0] = from_pe.valid;
      o.to_pe.ready = from_scratch_mem.ready[0];
      if(o.to_scratch_mem.valid[0] & from_scratch_mem.ready[0])
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Response from scratch mem completes this FSM
      o.to_scratch_mem.ready[0] = ready;
      o.done = from_scratch_mem.valid[0];
      if(o.done & ready)
      {
        state = IDLE;
      }
    }
  }
  
  return o;
}


typedef enum weight_multiplier_state_t
{
  IDLE,
  READ_SCRATCH_AND_WEIGHT,
  DO_PE_OP, // multiply
  WRITE_TO_SCRATCH
}weight_multiplier_state_t;
typedef struct weight_multiplier_t
{
  nn_to_weights_mem_t to_weights_mem;
  nn_to_pe_t to_pe;
  nn_to_scratch_mem_t to_scratch_mem;
  uint1_t done;
}weight_multiplier_t;
// R[1] = R[0] * weight[i][j]
weight_multiplier_t weight_multiplier(uint1_t start, label_iter_t i, pixel_iter_t j, weights_mem_to_nn_t from_weights_mem, pe_to_nn_t from_pe, scratch_mem_to_nn_t from_scratch_mem, uint1_t ready)
{
  static weight_multiplier_state_t state;
  static uint1_t req_in_fight;
  weight_multiplier_t o;
  o.to_weights_mem = NN_TO_WEIGHTS_MEM_T_NULL();
  o.to_pe = NN_TO_PE_T_NULL();
  o.to_scratch_mem = NN_TO_SCRATCH_MEM_T_NULL();
  o.done = 0;
  
  if(state==IDLE)
  {
    if(start)
    {
      state = READ_SCRATCH_AND_WEIGHT;
    }
  }
  // Pass through 'if' single cycle start
  if(state==READ_SCRATCH_AND_WEIGHT)
  {
    // Make request
    if(!req_in_fight)
    {
      // Make two requests to memory
      // Both must be ready to accept
      if(from_scratch_mem.ready[0] & from_weights_mem.ready)
      {
        // Scratch mem
        o.to_scratch_mem.wr_en[0] = 0; // read R[0]
        o.to_scratch_mem.valid[0] = 1;
        // Weights emm
        o.to_weights_mem.i = i;
        o.to_weights_mem.j = j;
        o.to_weights_mem.valid = 1;
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready memory values if PE is ready to receive it
      // Go to next state if have valid scratch reg and weight data
      // next state is where ready is signaled (or not)
      if(from_scratch_mem.valid[0] & from_weights_mem.valid)
      {
        req_in_fight = 0; // Response now available
        state = DO_PE_OP; // Next state
      }
    }
  }
  // Pass through 'if' to PE_OP since could get pixel in same cycle
  if(state==DO_PE_OP)
  {
    // Make request
    if(!req_in_fight)
    {
      // From memories into PE
      o.to_pe.arg0 = from_scratch_mem.r[0];
      o.to_pe.arg1 = from_weights_mem.weight;
      o.to_pe.op = MULT;
      o.to_pe.valid = from_scratch_mem.valid[0] & from_weights_mem.valid;
      if(o.to_pe.valid & from_pe.ready)
      {
        o.to_scratch_mem.ready[0] = from_pe.ready;
        o.to_weights_mem.ready = from_pe.ready;
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready for PE result if scratch mem ready 
      // Go to next state if have valid PE ouput, where ready is signaled (or not)
      if(from_pe.valid)
      {
        req_in_fight = 0; // Got response
        state = WRITE_TO_SCRATCH; // Next state
      }
    }
  }
  // Pass through 'if' to since could get result in same cycle
  if(state==WRITE_TO_SCRATCH)
  {
    // Make request
    if(!req_in_fight)
    {
      // From PE into scratch mem R[1]
      o.to_scratch_mem.r[1] = from_pe.value;
      o.to_scratch_mem.wr_en[1] = 1; // write
      o.to_scratch_mem.valid[1] = from_pe.valid;
      o.to_pe.ready = from_scratch_mem.ready[1];
      if(o.to_scratch_mem.valid[1] & from_scratch_mem.ready[1])
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Response from scratch mem completes this FSM
      o.to_scratch_mem.ready[1] = ready;
      o.done = from_scratch_mem.valid[1];
      if(o.done & ready)
      {
        state = IDLE;
      }
    }
  }
  
  return o;
}


// Two 'steps' (unlike other fsms which could be done in a single clock cycle)
// This is because this FSM reads and writes from/to the same single ported output activation memory 
// and thus must be done in two clocks - but other parts of the state machine can be comb. if possible
// 1) R[0] = reading from bias mem+existing activation outputs[i] + R[1]
// 2) Output mem[i] = R[0]
typedef enum activation_accumulator_state_t
{
  IDLE,
  STEP1,
  STEP2
}activation_accumulator_state_t;
typedef enum activation_accumulator_step1_state_t
{
  READ_BIAS_OR_ACTIVATION_AND_SCRATCH,
  DO_PE_OP, // ADD
  WRITE_TO_SCRATCH
}activation_accumulator_step1_state_t;
typedef enum activation_accumulator_step2_state_t
{
  READ_SCRATCH,
  WRITE_ACTIVATION_MEM
}activation_accumulator_step2_state_t;
typedef struct activation_accumulator_t
{
  nn_to_bias_mem_t to_bias_mem;
  nn_to_output_mem_t to_output_mem;
  nn_to_pe_t to_pe;
  nn_to_scratch_mem_t to_scratch_mem;
  uint1_t done;
}activation_accumulator_t;
// Read from bias mem on first iteration of i loop, i.e. when j==0, otherwise from existing activation[i]
activation_accumulator_t activation_accumulator(uint1_t start, label_iter_t i, pixel_iter_t j, bias_mem_to_nn_t from_bias_mem, output_mem_to_nn_t from_output_mem, pe_to_nn_t from_pe, scratch_mem_to_nn_t from_scratch_mem, uint1_t ready)
{
  static activation_accumulator_state_t state;
  static activation_accumulator_step1_state_t step1_state;
  static activation_accumulator_step2_state_t step2_state;
  static uint1_t req_in_fight;
  // Bias or act mem?
  uint1_t use_bias_mem = j==0;
  uint1_t bias_act_mem_valid = 0;
  activation_accumulator_t o;
  o.to_bias_mem = NN_TO_BIAS_MEM_T_NULL();
  o.to_output_mem = NN_TO_OUTPUT_MEM_T_NULL();
  o.to_pe = NN_TO_PE_T_NULL();
  o.to_scratch_mem = NN_TO_SCRATCH_MEM_T_NULL();
  o.done = 0;  
  
  if(state==IDLE)
  {
    if(start)
    {
      state = STEP1;
      step1_state = READ_BIAS_OR_ACTIVATION_AND_SCRATCH;
    }
  }
  // Pass through 'if' single cycle start
  if(state==STEP1)
  {
    if(step1_state==READ_BIAS_OR_ACTIVATION_AND_SCRATCH)
    {
      // Make request
      if(!req_in_fight)
      {
        // Make two requests to memory
        // Bias mem or activation mem read?
        uint1_t bias_act_mem_ready = 0;
        if(use_bias_mem)
        {
          bias_act_mem_ready = from_bias_mem.ready;
        }
        else
        {
          bias_act_mem_ready = from_output_mem.ready;
        }
        // Both bias/act + scratch must be ready to accept
        if(from_scratch_mem.ready[1] & bias_act_mem_ready)
        {
          // Scratch mem
          o.to_scratch_mem.wr_en[1] = 0; // read R[1]
          o.to_scratch_mem.valid[1] = 1;
          // Bias mem or activation mem 
          if(use_bias_mem)
          {
            // Bias mem
            o.to_bias_mem.i = i;
            o.to_bias_mem.valid = 1;
          }
          else
          {
            // Activations output mem
            o.to_output_mem.i = i;
            o.to_output_mem.wr_en = 0; // read
            o.to_output_mem.valid = 1;
          }
          req_in_fight = 1;
        }
      }
      // Pass through 'if' single cycle 
      // response could come immediately/combinatorially
      if(req_in_fight)
      {
        // Only ready memory values if PE is ready to receive it
        // Go to next step1_state if have valid value from mem
        // next step1_state is where ready is signaled (or not)
        if(use_bias_mem)
        {
          bias_act_mem_valid = from_bias_mem.valid;
        }
        else
        {
          bias_act_mem_valid = from_output_mem.valid;
        }
        if(from_scratch_mem.valid[1] & bias_act_mem_valid)
        {
          req_in_fight = 0; // Response now available
          step1_state = DO_PE_OP; // Next step1_state
        }
      }
    }
    // Pass through 'if' to PE_OP since could get memory values in same cycle
    if(step1_state==DO_PE_OP)
    {
      // Make request
      if(!req_in_fight)
      {
        // From memories into PE
        // Bias or act?
        float bias_act_value = 0.0;
        if(use_bias_mem)
        {
          bias_act_value = from_bias_mem.bias;
          bias_act_mem_valid = from_bias_mem.valid;
        }
        else
        {
          bias_act_value = from_output_mem.value;
          bias_act_mem_valid = from_output_mem.valid;
        }
        o.to_pe.arg0 = from_scratch_mem.r[1];
        o.to_pe.arg1 = bias_act_value;
        o.to_pe.op = ADD;
        o.to_pe.valid = from_scratch_mem.valid[1] & bias_act_mem_valid;
        if(o.to_pe.valid & from_pe.ready)
        {
          o.to_scratch_mem.ready[1] = from_pe.ready;
          if(use_bias_mem)
          {
            o.to_bias_mem.ready = from_pe.ready;
          }
          else
          {
            o.to_output_mem.ready = from_pe.ready;
          }
          req_in_fight = 1;
        }
      }
      // Pass through 'if' single cycle 
      // response could come immediately/combinatorially
      if(req_in_fight)
      {
        // Only ready for PE result if scratch mem ready 
        // Go to next step1_state if have valid PE ouput, where ready is signaled (or not)
        if(from_pe.valid)
        {
          req_in_fight = 0; // Got response
          step1_state = WRITE_TO_SCRATCH; // Next step1_state
        }
      }
    }
    // Pass through 'if' to since could get result in same cycle
    if(step1_state==WRITE_TO_SCRATCH)
    {
      // Make request
      if(!req_in_fight)
      {
        // From PE into scratch mem R[0]
        o.to_scratch_mem.r[0] = from_pe.value;
        o.to_scratch_mem.wr_en[0] = 1; // write
        o.to_scratch_mem.valid[0] = from_pe.valid;
        o.to_pe.ready = from_scratch_mem.ready[0];
        if(o.to_scratch_mem.valid[0] & from_scratch_mem.ready[0])
        {
          req_in_fight = 1;
        }
      }
      // Pass through 'if' single cycle 
      // response could come immediately/combinatorially
      if(req_in_fight)
      {
        // Wait for response from scratch mem 
        o.to_scratch_mem.ready[0] = 1;
        if(from_scratch_mem.valid[0])
        {
          // Starts next step
          state = STEP2;
          step2_state = READ_SCRATCH;
        }
      }
    }
  }
  else // STEP2
  {
    if(step2_state==READ_SCRATCH)
    {
      // Make request
      if(!req_in_fight)
      {
        o.to_scratch_mem.wr_en[0] = 0; // read R[0]
        o.to_scratch_mem.valid[0] = 1;
        if(from_scratch_mem.ready[0])
        {
          req_in_fight = 1;
        }
      }
      // Pass through 'if' single cycle 
      // response could come immediately/combinatorially
      if(req_in_fight)
      {
        // Only ready for scratch mem read value if output activation mem ready to write 
        // Go to next state if have valid incoming value
        // next state is where ready is signaled (or not)
        if(from_scratch_mem.valid[0])
        {
          req_in_fight = 0; // Response now available
          step2_state = WRITE_ACTIVATION_MEM; // Next state
        }
      }
    }
    // Pass through 'if' same cycle write to act mem since could get scratch mem value this cycle
    if(step2_state==WRITE_ACTIVATION_MEM)
    {
      // Make request
      if(!req_in_fight)
      {
        // From scratch mem into output activation mem
        o.to_output_mem.i = i;
        o.to_output_mem.value = from_scratch_mem.r[0];
        o.to_output_mem.wr_en = 1; // write
        o.to_output_mem.valid = from_scratch_mem.valid[0];
        o.to_scratch_mem.ready[0] = from_output_mem.ready;
        if(o.to_output_mem.valid & from_output_mem.ready)
        {
          req_in_fight = 1;
        }
      }
      // Pass through 'if' single cycle 
      // response could come immediately/combinatorially
      if(req_in_fight)
      {
        // Response from output mem completes this FSM
        o.to_output_mem.ready = ready;
        o.done = from_output_mem.valid;
        if(o.done & ready)
        {
          state = IDLE;
        }
      }
    }
  }
  
  return o;
}


typedef enum max_finder_state_t
{
  IDLE,
  READ_ACTIVATION_VALUE,
  DO_PE_OP, // COMPARE GT existing max
  UPDATE_NEW_MAX, // Based on result of compare
  WRITE_FINAL_MAX_TO_SCRATCH
}max_finder_state_t;
typedef struct max_finder_t
{
  nn_to_output_mem_t to_output_mem;
  nn_to_pe_t to_pe;
  nn_to_scratch_mem_t to_scratch_mem;
  uint1_t done;
}max_finder_t;
// R[0] = max(activations)
// Need to loop over activations memory, storing max as you find it
// Not only do we need the result of PE operation (compare GT),
// but also the values compared (to store one of them as max)
// For this reason we must store the values when sending them into PE
// Because needing those two extra regs for compared values
// dont need to use scratch memory (outside this func) as often, only written once at end
max_finder_t max_finder(uint1_t start, output_mem_to_nn_t from_output_mem, pe_to_nn_t from_pe, scratch_mem_to_nn_t from_scratch_mem, uint1_t ready)
{
  static max_finder_state_t state;
  static uint1_t req_in_fight;
  static uint32_t i;
  static float curr_act;
  static float max_act;
  static uint8_t max_act_i;
  max_finder_t o; 
  o.to_output_mem = NN_TO_OUTPUT_MEM_T_NULL();
  o.to_pe = NN_TO_PE_T_NULL();
  o.to_scratch_mem = NN_TO_SCRATCH_MEM_T_NULL();
  o.done = 0;
  
  if(state==IDLE)
  {
    // Reset values
    i = 0;
    max_act = -99999.0; // TODO real good min constant
    max_act_i = MNIST_LABELS; // invalid value
    if(start)
    {
      state = READ_ACTIVATION_VALUE;
    }
  }
  // Pass through 'if' single cycle start
  if(state==READ_ACTIVATION_VALUE)
  {
    // Make request
    if(!req_in_fight)
    {
      o.to_output_mem.i = i; // address
      o.to_output_mem.wr_en = 0; // read
      o.to_output_mem.valid = 1;
      if(from_output_mem.ready) // & to_input_mem.valid==1 known
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready for actuivation value form output mem if PE is ready to receive it
      // Go to next state if have valid incoming value
      // next state is where ready is signaled (or not)
      if(from_output_mem.valid)
      {
        req_in_fight = 0; // Response now available
        state = DO_PE_OP; // Next state
      }
    }
  }
  // Pass through 'if' to DO_PE_OP since could get value from above stage in same cycle
  if(state==DO_PE_OP)
  {
    // Make request
    if(!req_in_fight)
    {
      // From input mem into PE
      curr_act = from_output_mem.value;
      o.to_pe.arg0 = curr_act;
      o.to_pe.arg1 = max_act;
      o.to_pe.op = GT;
      o.to_pe.valid = from_output_mem.valid;
      o.to_output_mem.ready = from_pe.ready;
      if(o.to_pe.valid & from_pe.ready)
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Only ready for PE result if scratch mem ready 
      // Go to next state if have valid PE ouput, where ready is signaled (or not)
      if(from_pe.valid)
      {
        req_in_fight = 0; // Got response
        state = UPDATE_NEW_MAX; // Next state
      }
    }
  }
  // Pass through 'if' to since could get result from above in same cycle
  if(state==UPDATE_NEW_MAX)
  {
    // If new value was greater, then replaces current max
    o.to_pe.ready = 1;
    if(from_pe.valid)
    {
      // GT?
      if(from_pe.value_bool)
      {
        max_act = curr_act;
        max_act_i = i;
      }
      
      // Done comparing, or next compare?
      if(i==(MNIST_LABELS-1))
      {
        // Done comparing
        state = WRITE_FINAL_MAX_TO_SCRATCH;
      }
      else
      {
        // Next compare
        i+=1;
        state = READ_ACTIVATION_VALUE;
      }
    }
  }
  // Does need to be pass through but can be for now
  if(state==WRITE_FINAL_MAX_TO_SCRATCH)
  {
    // Make request
    if(!req_in_fight)
    {
      // Into scratch mem R[0]
      o.to_scratch_mem.r[0] = max_act_i;
      o.to_scratch_mem.wr_en[0] = 1; // write
      o.to_scratch_mem.valid[0] = 1;
      if(from_scratch_mem.ready[0])
      {
        req_in_fight = 1;
      }
    }
    // Pass through 'if' single cycle 
    // response could come immediately/combinatorially
    if(req_in_fight)
    {
      // Response from scratch mem completes this FSM
      o.to_scratch_mem.ready[0] = ready;
      o.done = from_scratch_mem.valid[0];
      if(o.done & ready)
      {
        state = IDLE;
      }
    }
  }
  
  return o;
}

// Main computation fsm
typedef enum nn_computation_state_t
{
  IDLE, // Waiting for start signal
  // Loop doing below states:
  SCALE_PIXEL, // Using the FPU/PE to divide pixel uint8_t/255-> 0.0 -> 1.0
  MULT, // Mult input pixel value by NN weight
  ACCUM, // Accumulate that value with whats in the output activation mem (or bias value to start)
  INC_COUNTERS, // Increment i,j counters like nested loop would
  // Finally
  MAX_ACT // Find the maximally activated neuron
}nn_computation_state_t;

typedef struct nn_computation_t
{
  uint1_t ready;
  uint1_t done;
}nn_computation_t;
#pragma MAIN_MHZ nn_computation 100.0
nn_computation_t nn_computation(uint1_t start, uint1_t ready)
{
  // Registers
  static nn_computation_state_t state;
  static uint32_t i;
  static uint32_t j;
  
  // Input global wires
  input_mem_to_nn_t from_input_mem;
  WIRE_READ(input_mem_to_nn_t, from_input_mem, input_mem_to_nn)
  bias_mem_to_nn_t from_bias_mem;
  WIRE_READ(bias_mem_to_nn_t, from_bias_mem, bias_mem_to_nn)
  weights_mem_to_nn_t from_weights_mem;
  WIRE_READ(weights_mem_to_nn_t, from_weights_mem, weights_mem_to_nn)
  output_mem_to_nn_t from_output_mem;
  WIRE_READ(output_mem_to_nn_t, from_output_mem, output_mem_to_nn)
  pe_to_nn_t from_pe;
  WIRE_READ(pe_to_nn_t, from_pe, pe_to_nn)
  scratch_mem_to_nn_t from_scratch_mem;
  WIRE_READ(scratch_mem_to_nn_t, from_scratch_mem, scratch_mem_to_nn)
  
  // Output global wires
  nn_to_input_mem_t to_input_mem = NN_TO_INPUT_MEM_T_NULL();
  nn_to_bias_mem_t to_bias_mem = NN_TO_BIAS_MEM_T_NULL();
  nn_to_weights_mem_t to_weights_mem = NN_TO_WEIGHTS_MEM_T_NULL();
  nn_to_output_mem_t to_output_mem = NN_TO_OUTPUT_MEM_T_NULL();
  nn_to_pe_t to_pe = NN_TO_PE_T_NULL();
  nn_to_scratch_mem_t to_scratch_mem = NN_TO_SCRATCH_MEM_T_NULL();
  
  // Output wire
  nn_computation_t o;
  o.ready = 0;
  o.done = 0;
  
  if(state==IDLE)
  {
    o.ready = 1;
    if(start)
    {
      state = SCALE_PIXEL;
    }
  }
  else if(state==SCALE_PIXEL)
  {
    // Scale pixel[j], putting the value in scratch reg R[0]
    pixel_scaler_t pixel_scaler_out = pixel_scaler(1, j, from_input_mem, from_pe, from_scratch_mem, 1);
    to_input_mem = pixel_scaler_out.to_input_mem;
    to_pe = pixel_scaler_out.to_pe;
    to_scratch_mem = pixel_scaler_out.to_scratch_mem;
    if(pixel_scaler_out.done)
    {
      state = MULT;
    }
  }
  else if(state==MULT)
  {
    // Do mult FSM, R[0]*weight[i][j] putting result in scratch R[1]
    weight_multiplier_t weight_multiplier_out = weight_multiplier(1, i, j, from_weights_mem, from_pe, from_scratch_mem, 1);
    to_weights_mem = weight_multiplier_out.to_weights_mem;
    to_pe = weight_multiplier_out.to_pe;
    to_scratch_mem = weight_multiplier_out.to_scratch_mem;
    if(weight_multiplier_out.done)
    {
      // Always doing accum after the mult
      state = ACCUM;
    }
  }
  else if(state==ACCUM)
  {
    // Do accumulating FSM reading from bias mem+existing activation outputs + R[1]
    activation_accumulator_t activation_accumulator_out = activation_accumulator(1, i, j, from_bias_mem, from_output_mem, from_pe, from_scratch_mem, 1);
    to_bias_mem = activation_accumulator_out.to_bias_mem;
    to_output_mem = activation_accumulator_out.to_output_mem;
    to_pe = activation_accumulator_out.to_pe;
    to_scratch_mem = activation_accumulator_out.to_scratch_mem;
    if(activation_accumulator_out.done)
    {
      // Then increment counters/conditionals
      state = INC_COUNTERS;
    }
  }
  else if(state==INC_COUNTERS)
  {
    // Conditionally do something, probabaly mult again
    // But maybe done
    // Unrolling the nested i,j loops
    // Next state, counter increment
    if(j==(MNIST_IMAGE_SIZE-1))
    {
      // End of J loop
      j = 0;
      // Next i iteration
      if(i==(MNIST_LABELS-1))
      {
        // End of i loop
        i = 0;
        // Done accumulating activations, find max
        state = MAX_ACT;
      }
      else
      {
        // Normal outer i loop
        i += 1;
        state = SCALE_PIXEL;
      }
    }
    else
    {
      // Normal inner j loop
      j+=1;
      state = SCALE_PIXEL;
    }
  }
  else if(state==MAX_ACT)
  {
    // Do the find max activation fsm, result in R[0]
    // This ends the NN computaiton fsm, back to idle when ready
    max_finder_t max_finder_out = max_finder(1, from_output_mem, from_pe, from_scratch_mem, ready);
    to_output_mem = max_finder_out.to_output_mem;
    to_pe = max_finder_out.to_pe;
    to_scratch_mem = max_finder_out.to_scratch_mem;
    o.done = max_finder_out.done;
    if(o.done & ready)
    {
      state = IDLE;
    }
  }
  
  // Output global wires
  WIRE_WRITE(nn_to_input_mem_t, nn_to_input_mem, to_input_mem)
  WIRE_WRITE(nn_to_bias_mem_t, nn_to_bias_mem, to_bias_mem)
  WIRE_WRITE(nn_to_weights_mem_t, nn_to_weights_mem, to_weights_mem)
  WIRE_WRITE(nn_to_output_mem_t, nn_to_output_mem, to_output_mem)
  WIRE_WRITE(nn_to_pe_t, nn_to_pe, to_pe)
  WIRE_WRITE(nn_to_scratch_mem_t, nn_to_scratch_mem, to_scratch_mem)
  
  // Output wire
  return o;
}
