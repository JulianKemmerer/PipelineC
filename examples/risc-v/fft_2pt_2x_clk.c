#include "stream/stream.h"
#include "global_fifo.h"
#include "ram.h"
#include "global_func_inst.h"
#include "examples/arty/src/i2s/i2s_samples.h"
#include "gcc_test/fft.h"

// Types for the FIFO elements to be transfered
typedef struct fft_ram_2x_write_req_t{
  // t addr and data
  uint16_t t_index;
  fft_out_t t;
  uint1_t t_write_en;
  // u addr and data
  uint16_t u_index;
  fft_out_t u;
  uint1_t u_write_en;
}fft_ram_2x_write_req_t;
typedef struct fft_ram_2x_read_req_t{
  // t addr
  uint16_t t_index;
  // u addr
  uint16_t u_index;
}fft_ram_2x_read_req_t;
typedef struct fft_ram_2x_read_resp_t{
  // t data
  fft_out_t t;
  // u data
  fft_out_t u;
}fft_ram_2x_read_resp_t;
DECL_STREAM_TYPE(fft_ram_2x_write_req_t)
DECL_STREAM_TYPE(fft_ram_2x_read_req_t)
DECL_STREAM_TYPE(fft_ram_2x_read_resp_t)
DECL_STREAM_TYPE(fft_2pt_w_omega_lut_in_t)
DECL_STREAM_TYPE(fft_2pt_out_t)
DECL_STREAM_TYPE(fft_out_t)

// Declare the fifos linking across clock domains
// (req/resp could also be done as a shared resource bus,
//  see https://github.com/JulianKemmerer/PipelineC/wiki/Shared-Resource-Bus)
GLOBAL_STREAM_FIFO(i2s_samples_t, samples_fifo, 16)
GLOBAL_STREAM_FIFO(fft_ram_2x_read_req_t, rd_req_fifo, 16)
GLOBAL_STREAM_FIFO(fft_ram_2x_read_resp_t, rd_resp_fifo, 16)
GLOBAL_STREAM_FIFO(fft_ram_2x_write_req_t, wr_req_fifo, 16)
GLOBAL_STREAM_FIFO(fft_out_t, output_fifo, 16)

// Type of RAM for storing FFT output
// Dual write,read ports 1 clock latency (block)RAM
DECL_STREAM_RAM_DP_W_R_1(
  fft_out_t, fft_ram, NFFT, "(others => (others => (others => '0')))"
)

// Instance of RAM for FFT
// Connected to global variable fifo streams 
// with little bit of 2:1 un/packing in between
// (this could also be done as de/serializers
//  see https://github.com/JulianKemmerer/PipelineC/tree/master/stream)
MAIN_MHZ(fft_ram_main, FFT_CLK_2X_MHZ)
void fft_ram_main(){
  // Declare instance of fft_ram called 'ram'
  // declares local variables 'ram_...' w/ valid+ready stream interface
  RAM_DP_W_R_1_STREAM(fft_out_t, fft_ram, ram)
  #warning "Feedback wire need defaults? See github issue..."

  // FSM logic doing 2:1 un/packing de/serializing
  // to-from RAM writes/reads reqs/resps

  // Write Port (addr+data requests)
  // toggle between t and u
  static uint1_t wr_is_t = 1;
  // Always ready sink, write responses out of ram unused/dropped
  ram_wr_out_ready = 1; 
  // Default not pulling requests from fifo
  wr_req_fifo_out_ready = 0;
  // What is port doing this cycle?
  if(wr_is_t){
    // Data
    ram_wr_data_in = wr_req_fifo_out.data.t;
    ram_wr_addr_in = wr_req_fifo_out.data.t_index;
    // Valid
    ram_wr_in_valid = wr_req_fifo_out.valid & wr_req_fifo_out.data.t_write_en;
    // Ready (xfer happening?valid&ready?)
    if(wr_req_fifo_out.valid & ram_wr_in_ready){
      // Next state
      wr_is_t = 0;
      // not asserting ready for request yet
      // since not done with req yet, u next
    }
  }else{ // wr is u
    // Data
    ram_wr_data_in = wr_req_fifo_out.data.u;
    ram_wr_addr_in = wr_req_fifo_out.data.u_index;
    // Valid
    ram_wr_in_valid = wr_req_fifo_out.valid & wr_req_fifo_out.data.u_write_en;
    // Ready (xfer happening?valid&ready?)
    if(wr_req_fifo_out.valid & ram_wr_in_ready){
      // Next state (next req)
      wr_is_t = 1;
      // Assert ready for request
      // since now done with both t and u
      wr_req_fifo_out_ready = 1;
    }
  }

  // Read Port Requests (addr)
  // toggle between t and u
  static uint1_t rd_req_is_t = 1;
  // Default not pulling requests from fifo
  rd_req_fifo_out_ready = 0;
  if(rd_req_is_t){
    // Data
    ram_rd_addr_in = rd_req_fifo_out.data.t_index;
    // Valid
    ram_rd_in_valid = rd_req_fifo_out.valid;
    // Ready (xfer happening?valid&ready?)
    if(ram_rd_in_valid & ram_rd_in_ready){
      // Next state
      rd_req_is_t = 0;
      // not asserting ready for request yet
      // since not done with req yet, u next
    }
  }else{ // rd req is u
    // Data
    ram_rd_addr_in = rd_req_fifo_out.data.u_index;
    // Valid
    ram_rd_in_valid = rd_req_fifo_out.valid;
    // Ready (xfer happening?valid&ready?)
    if(ram_rd_in_valid & ram_rd_in_ready){
      // Next state (next req)
      rd_req_is_t = 1;
      // Assert ready for request
      // since now done with both t and u
      rd_req_fifo_out_ready = 1;
    }
  }

  // Read Port Responses (data)
  static uint1_t rd_resp_is_t = 1;
  // Default not putting responses into resp fifo
  rd_resp_fifo_in.valid = 0;
  if(rd_resp_is_t){
    // Data 
    // (fifo input is global variable
    //  that can store partial 't' data as register)
    rd_resp_fifo_in.data.t = ram_rd_data_out;
    // Valid
    // not asserting valid response into fifo yet
    // since not done forming resp yet, u next
    rd_resp_fifo_in.valid = 0;
    // Ready 
    ram_rd_out_ready = 1; // Always ready for t data
    // Transfering data this cycle (valid&ready)?
    if(ram_rd_out_valid & ram_rd_out_ready){
      // Next state
      rd_resp_is_t = 0;
    }
  }else{ // rd resp is u
    // Data
    // (t from fifo input reg last state still set
    // u straight from ram into resp fifo this cycle)
    rd_resp_fifo_in.data.u = ram_rd_data_out;
    // Valid
    rd_resp_fifo_in.valid = ram_rd_out_valid;
    // Ready 
    ram_rd_out_ready = rd_resp_fifo_in_ready;
    // Transfering data this cycle (valid&ready)?
    if(ram_rd_out_valid & ram_rd_out_ready){
      // Next state (next resp)
      rd_resp_is_t = 1;
    }
  }
}

// Global instance of butterfly pipeline with valid ready handshake
GLOBAL_VALID_READY_PIPELINE_INST(fft_2pt_pipeline, fft_2pt_out_t, fft_2pt_w_omega_lut, fft_2pt_w_omega_lut_in_t, 16)

// Didnt need to write fft_2pt_fsm as standalone function
// could have put code directly in-line into MAIN func
// as opposed to making an instance of the fft_2pt_fsm module
// FSM States for main 1clk fsm
typedef enum fft_fsm_state_t{
  LOAD_INPUTS,
  BUTTERFLY_ITERS,
  UNLOAD_OUTPUTS
}fft_fsm_state_t;
// Outputs
typedef struct fft_2pt_fsm_out_t
{
  // Stream of writes to RAM
  stream(fft_ram_2x_write_req_t) wr_reqs_to_ram;
  // Stream of read request addresses to RAM
  stream(fft_ram_2x_read_req_t) rd_addrs_to_ram;
  // Stream of data to butterfly pipeline
  stream(fft_2pt_w_omega_lut_in_t) data_to_pipeline;
  // Stream of output FFT result to CPU
  stream(fft_out_t) result_out;
  // Ready for input samples stream
  uint1_t ready_for_samples_in;
  // Ready for read resp from RAM
  uint1_t ready_for_rd_datas_from_ram;
  // Ready for data out from pipeline
  uint1_t ready_for_data_from_pipeline;
}fft_2pt_fsm_out_t;
fft_2pt_fsm_out_t fft_2pt_fsm(
  // Inputs
  // Stream of input samples from I2S
  i2s_samples_t_stream_t samples_in,
  // Stream of read response data from RAM
  stream(fft_ram_2x_read_resp_t) rd_datas_from_ram,
  // Stream of data from butterfly pipeline
  stream(fft_2pt_out_t) data_from_pipeline,
  // Ready for write req to RAM
  uint1_t ready_for_wr_reqs_to_ram,
  // Ready for read addr to RAM
  uint1_t ready_for_rd_addrs_to_ram,
  // Ready for data into pipeline
  uint1_t ready_for_data_to_pipeline,
  // Ready for result out to CPU
  uint1_t ready_for_result_out
){
  // State registers
  static fft_fsm_state_t state;
  //  FFT s,j,k iterators for various streams
  static fft_iters_t rd_req_iters;
  static fft_iters_t pipeline_req_iters;
  static fft_iters_t wr_req_iters; 
  //  Some helper flags to do 's' loops sequentially
  static uint1_t waiting_on_s_iter_to_finish;
  static uint1_t rd_reqs_done;
  // Outputs (default all zeros)
  fft_2pt_fsm_out_t o; 
  // FSM logic
  if(state==LOAD_INPUTS)
  {
    // Load input samples from I2S
    // data needs fixed point massaging
    // and only using the left channel as real inputs to FFT
    #ifdef FFT_TYPE_IS_FIXED
    fft_data_t data_in = samples_in.data.l_data.qmn >> (24-16);
    #endif
    // Array index is bit reversed, using 'j' as sample counter here
    uint32_t j = wr_req_iters.j;
    uint32_t array_index = j(0, 31); // reverse of [31:0]
    // Connect input samples stream
    // to the stream of writes going to RAM
    // only using one 't' part of two possible write addrs+datas
    // Data (connect input to output)
    o.wr_reqs_to_ram.data.t.real = data_in;
    o.wr_reqs_to_ram.data.t_index = array_index;
    o.wr_reqs_to_ram.data.t_write_en = 1;
    // Valid (connect input to output)
    o.wr_reqs_to_ram.valid = samples_in.valid;
    // Ready (connect input to output)
    o.ready_for_samples_in = ready_for_wr_reqs_to_ram;
    // Transfering data this cycle (valid&ready)?
    if(samples_in.valid & o.ready_for_samples_in){
      // Last sample into ram?
      if(wr_req_iters.j==(NFFT-1)){
        // Done loading samples, next state
        state = BUTTERFLY_ITERS;
        wr_req_iters = FFT_ITERS_INIT;
      }else{
        // More input samples coming
        wr_req_iters.j += 1;
      }
    }
  }
  else if(state==BUTTERFLY_ITERS)
  {
    // FSM version of s,k,j loops from fft.c
    // that stream data through fft_2pt_w_omega_lut pipeline
    // Note: 's' loops must be done sequentially:
    // meaning need to confirm all iters from one 's' iter
    // are done before starting another
    /*
    fft_2pt_w_omega_lut_in_t fft_in;
    fft_in.t = output[t_index];
    fft_in.u = output[u_index];
    fft_in.s = s;
    fft_in.j = j;
    fft_2pt_out_t fft_out = fft_2pt_w_omega_lut(fft_in);
    */
    // 1)
    // Begins by making valid requests to read data from RAM
    // i.e. lookup output[t_index], output[u_index]
    uint32_t m = 1 << rd_req_iters.s;
    uint32_t m_1_2 = m >> 1;
    uint32_t t_index = rd_req_iters.k + rd_req_iters.j + m_1_2;
    uint32_t u_index = rd_req_iters.k + rd_req_iters.j;
    // until done making requests 
    // or unless waiting for s iter to finish 
    if(~rd_reqs_done & ~waiting_on_s_iter_to_finish){
      // Data
      o.rd_addrs_to_ram.data.t_index = t_index;
      o.rd_addrs_to_ram.data.u_index = u_index;
      // Valid
      o.rd_addrs_to_ram.valid = 1;
      // Ready, transfering data this cycle (valid&ready)?
      if(ready_for_rd_addrs_to_ram){
        // Transfer going through, next
        // Ending an s iteraiton?
        uint1_t s_incrementing = k_last(rd_req_iters) & j_last(rd_req_iters);
        if(s_incrementing){
          // Pause, wait for current s iter to finish
          waiting_on_s_iter_to_finish = 1;
        }
        // Last req to ram?
        if(last_iter(rd_req_iters)){
          // Done requests
          rd_reqs_done = 1;
          rd_req_iters = FFT_ITERS_INIT;
        }else{
          // More reqs to make
          rd_req_iters = next_iters(rd_req_iters);
        }
      }
    }
    // 2)
    // Read response data from RAM connected to butterfly pipeline
    // Data (connect input to output)
    o.data_to_pipeline.data.t = rd_datas_from_ram.data.t;
    o.data_to_pipeline.data.u = rd_datas_from_ram.data.u;
    //  along with some iterators counting along
    o.data_to_pipeline.data.j = pipeline_req_iters.j;
    o.data_to_pipeline.data.s = pipeline_req_iters.s;
    // Valid (connect input to output)
    o.data_to_pipeline.valid = rd_datas_from_ram.valid;
    // Ready (connect input to output)
    o.ready_for_rd_datas_from_ram = ready_for_data_to_pipeline;
    // Transfering data this cycle (valid&ready)?
    if(o.data_to_pipeline.valid & ready_for_data_to_pipeline){
      // Transfer going through, count next
      pipeline_req_iters = next_iters(pipeline_req_iters);
      // Last req to pipeline?
      if(last_iter(pipeline_req_iters)){
        // resets counters
        pipeline_req_iters = FFT_ITERS_INIT;
      }
    }
    // 3) 
    // Pipeline outputs are connected to RAM writes
    // i.e. write back output[t_index], output[u_index] to RAM
    uint32_t m = 1 << wr_req_iters.s;
    uint32_t m_1_2 = m >> 1;
    uint32_t t_index = wr_req_iters.k + wr_req_iters.j + m_1_2;
    uint32_t u_index = wr_req_iters.k + wr_req_iters.j;
    // Data (connect input to output)
    o.wr_reqs_to_ram.data.t = data_from_pipeline.data.t;
    o.wr_reqs_to_ram.data.t_write_en = 1;
    o.wr_reqs_to_ram.data.u = data_from_pipeline.data.u;
    o.wr_reqs_to_ram.data.u_write_en = 1;
    //  along with some iterators counting along
    o.wr_reqs_to_ram.data.t_index = t_index;
    o.wr_reqs_to_ram.data.u_index = u_index;
    // Valid (connect input to output)
    o.wr_reqs_to_ram.valid = data_from_pipeline.valid;
    // Ready (connect input to output)
    o.ready_for_data_from_pipeline = ready_for_wr_reqs_to_ram;
    // Transfering data this cycle (valid&ready)?
    if(o.wr_reqs_to_ram.valid & ready_for_wr_reqs_to_ram){
      // Transfer going through, next
      // Ending an s iteraiton?
      uint1_t s_incrementing = k_last(wr_req_iters) & j_last(wr_req_iters);
      if(s_incrementing){
        // Finished s iteration write back now
        waiting_on_s_iter_to_finish = 0;
      }
      // Last req to ram?
      if(last_iter(wr_req_iters)){
        // Done write back, finishes FFT, unload result
        wr_req_iters = FFT_ITERS_INIT;
        state = UNLOAD_OUTPUTS;
      }else{
        // More write reqs to make
        wr_req_iters = next_iters(wr_req_iters);
      }
    }
  }
  else // UNLOAD_OUTPUTS
  {
    // Start/request reads of data from RAM to output to CPU
    // (using 'j' counter for this)
    if(rd_req_iters.j < NFFT){
      // Try to start next read by making valid request
      // Data (only using one 't' part of two possible read addrs)
      o.rd_addrs_to_ram.data.t_index = rd_req_iters.j;
      // Valid
      o.rd_addrs_to_ram.valid = 1;
      // Ready
      if(ready_for_rd_addrs_to_ram){
        // Transfer going through, next
        rd_req_iters.j += 1;
        // move to next state handled below with read responses        
      }
    }
    // Responses from RAM connected to CPU
    // (using 'k' for this)
    if(rd_req_iters.k < NFFT){
      // Connect responses from RAM to CPU output
      // Data (only using one 't' part of two possible read datas)
      o.result_out.data = rd_datas_from_ram.data.t;
      // Valid (connect input to output) 
      o.result_out.valid = rd_datas_from_ram.valid;
      // Ready (connect input to output) 
      o.ready_for_rd_datas_from_ram = ready_for_result_out;
      // Transfering data this cycle (valid&ready)?
      if(o.result_out.valid & ready_for_result_out){
        // Last data to CPU?
        if(rd_req_iters.k==(NFFT-1)){
          // Done offloading output, restart FFT
          state = LOAD_INPUTS;
          rd_req_iters = FFT_ITERS_INIT;
          rd_reqs_done = 0;
        }else{
          // Still waiting for more outputs
          rd_req_iters.k += 1;
        }
      }
    }
  }
  return o;
}

// Instannce of fft_2pt_fsm connected to FIFOs and butterfly pipeline
MAIN_MHZ(fft_fsm_main, FFT_CLK_MHZ)
void fft_fsm_main(){
  // The FSM instance
  fft_2pt_fsm_out_t fsm_out = fft_2pt_fsm(
    // Inputs
    // Stream of input samples from I2S out of FIFO
    samples_fifo_out,
    // Stream of read response data from RAM out of FIFO
    rd_resp_fifo_out,
    // Stream of data from butterfly pipeline
    fft_2pt_pipeline_out,
    // Ready for write req to RAM into FIFO
    wr_req_fifo_in_ready,
    // Ready for read addr to RAM into FIFO
    rd_req_fifo_in_ready,
    // Ready for data into pipeline
    fft_2pt_pipeline_in_ready,
    // Ready for result out to CPU into FIFO
    output_fifo_in_ready
  );
  // Outputs
  // Ready for input samples stream out of FIFO
  samples_fifo_out_ready = fsm_out.ready_for_samples_in;
  // Ready for read resp from RAM out of FIFO
  rd_resp_fifo_out_ready = fsm_out.ready_for_rd_datas_from_ram;
  // Ready for data out from pipeline
  fft_2pt_pipeline_out_ready = fsm_out.ready_for_data_from_pipeline;
  // Stream of writes to RAM into FIFO
  wr_req_fifo_in = fsm_out.wr_reqs_to_ram;
  // Stream of read request addresses to RAM into FIFO
  rd_req_fifo_in = fsm_out.rd_addrs_to_ram;
  // Stream of data to butterfly pipeline
  fft_2pt_pipeline_in = fsm_out.data_to_pipeline;
  // Stream of output FFT result to CPU into FIFO
  output_fifo_in = fsm_out.result_out;
}
