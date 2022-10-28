#include "uintN_t.h"
#include "axi/axis.h"
#include "fifo.h"
#include "compiler.h"

#pragma MAIN_MHZ the_pipeline 300.0
#pragma MAIN_MHZ io_and_ctrl 300.0
#pragma PART "xcu50-fsvh2104-2-e"

// Wires into and out of autopipelined region
uint32_t pipeline_in_data;
uint1_t pipeline_in_valid;
uint32_t pipeline_out_data;
uint1_t pipeline_out_valid;
// The autopipelined function (no state)
void the_pipeline()
{
    uint32_t temp = 0;
    uint32_t i = 0;
    for (i = 0; i < 32; i = i + 1) {
        if (temp == 1) {
          temp = temp - 1;
        } else if (temp == 0) {
          temp = temp + 1;
        }
    }
    if (temp == 0) {
        temp = temp + 1;
    }
    pipeline_out_data = pipeline_in_data + temp;
    pipeline_out_valid = pipeline_in_valid;
}

// FIFO for holding outputs from pipeline
// Pipeline shouldn't be more than 128 cycles latency/deep
#define FIFO_DEPTH 128
FIFO_FWFT(outfifo, uint32_t, FIFO_DEPTH) // 128 deep of u32s

// Stateful FIFO + counting + AXIS signaling
DECL_OUTPUT(uint32_t, out_data)
DECL_OUTPUT(uint1_t, out_valid)
DECL_OUTPUT(uint1_t, in_ready)
void io_and_ctrl(uint32_t in_data, uint1_t in_valid, uint1_t out_ready)
{
    // Keep count of how many words in FIFO
    static uint16_t fifo_count;

    // Default not ready for inputs
    in_ready = 0;

    // Signal ready for input if room in fifo
    if(fifo_count < FIFO_DEPTH){
        in_ready = 1;
    }

    // Logic for input side of pipeline
    // Gate valid with ready signal
    pipeline_in_valid = in_valid & in_ready;
    pipeline_in_data = in_data;

    // Free flow of data out of pipeline into fifo
    uint1_t fifo_wr_en = pipeline_out_valid;
    uint32_t fifo_wr_data = pipeline_out_data;
    // Dont need to check for not full/overflow since count used for ready

    // Read side of FIFO connected to top level outputs
    uint1_t fifo_rd_en = out_ready;

    // The FIFO instance connected to outputs
    outfifo_t fifo_o = outfifo(fifo_rd_en, fifo_wr_data, fifo_wr_en);
    out_valid = fifo_o.data_out_valid;
    out_data = fifo_o.data_out;
    
    // Count input writes and output reads from fifo
    if(in_valid & in_ready){
        fifo_count += 1;
    }
    if(out_valid & out_ready){
        fifo_count -= 1;
    }
}
