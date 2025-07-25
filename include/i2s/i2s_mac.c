#pragma once
#include "wire.h"
#include "intN_t.h"
#include "uintN_t.h"
#include "arrays.h"
#include "stream/stream.h"
#include "fixed/q0_23.h"

// Logic to send and receive I2S samples via a streaming interface

// Include I2S signals to/from PMOD
typedef struct i2s_to_app_t
{
  uint1_t rx_data;
}i2s_to_app_t;
typedef struct app_to_i2s_t
{
  uint1_t tx_lrck;
  uint1_t tx_sclk;
  uint1_t tx_data;
  uint1_t rx_lrck;
  uint1_t rx_sclk;
}app_to_i2s_t;

/*
https://reference.digilentinc.com/pmod/pmodi2s2/reference-manual
  Quick Start
  To set up a simple 44.1 kHz audio passthrough, three control signals need to be generated by the host system board.
  1. A master clock (MCLK) at a frequency of approximately 22.579 MHz.
  2. A serial clock (SCLK), which fully toggles once per 8 MCLK periods.
  3. A Left/Right Word Select signal, which fully toggles once per 64 SCLK periods.
  The Pmod I2S2's Master/Slave select jumper (JP1) should be placed into the Slave (SLV) position.
  Each of these control signals should be provided to the appropriate pin on both the top and bottom rows of the Pmod I2S2.
  The ADOUT_SDIN pin should be driven by the ADIN_SDOUT signal.
*/
// This configuration does not exactly match I2S spec, which allows for back to back sample data
// However, in this case, as seen in Digilent docs, sample data is 
// padded with trailing zeros for several cycles before the next channel sample begins
#define I2S_MCLK_MHZ 22.579
#define SCLK_PERIOD_MCLKS 8
#define LR_PERIOD_SCLKS 64
#define LEFT 0
#define RIGHT 1

#include "i2s_samples.h"

// Both RX and TX are dealing with the I2S protocol
typedef enum i2s_state_t
{
  RL_WAIT, // Sync up to the R->L I2S start of frame, left sample data
  LR_WAIT, // Sync up to the L->R start of right sample data
  SAMPLE, // Bits for a sample
}i2s_state_t;

// Logic to receive I2S stereo samples
typedef struct i2s_rx_t
{
  stream(i2s_samples_t) samples;
  uint1_t overflow;
}i2s_rx_t;
i2s_rx_t i2s_rx(uint1_t data, uint1_t lr, uint1_t sclk_rising_edge, uint1_t samples_ready, uint1_t reset_n)
{
  // Registers
  static i2s_state_t state;
  static uint1_t last_lr;
  static uint1_t curr_sample_bits[SAMPLE_BITWIDTH];
  static uint5_t curr_sample_bit_count;
  static stream(i2s_samples_t) output_reg;
  static uint1_t l_sample_valid;
  static uint1_t r_sample_valid;
  
  // Output signal
  i2s_rx_t rv;
  // Defaults
  rv.samples = output_reg; // Output reg directly drives return value
  rv.overflow = 0; // Not overflowing
  // Output reg cleared if was ready for samples
  if(samples_ready)
  {
    output_reg.valid = 0;
  }
   
  // FSM Logic:
  
  // Everything occuring relative to sclk rising edges
  if(sclk_rising_edge)
  {
    // Waiting for R->L transition start of I2S frame, left sample data
    if(state==RL_WAIT)
    {
      if((last_lr==RIGHT) & (lr==LEFT))
      {
        // Next SCLK rising edge starts sample bits
        state = SAMPLE;
      }
    }
    // Waiting for L->R transition start of right sample data
    else if(state==LR_WAIT)
    {
      if((last_lr==LEFT) & (lr==RIGHT))
      {
        // Next SCLK rising edge starts sample bits
        state = SAMPLE;
      }
    }
    // Sampling data bit
    else // if(state==SAMPLE)
    {
      // Data is MSB first, put data into bottom/lsb such that
      // after N bits the first bit is in correct positon at MSB
      ARRAY_1SHIFT_INTO_BOTTOM(curr_sample_bits, SAMPLE_BITWIDTH, data)
      
      // Was this the last bit?
      if(curr_sample_bit_count==(SAMPLE_BITWIDTH-1))
      {
        // Form the current full sample
        i2s_data_t curr_sample;
        curr_sample.qmn = bits_to_i2s_data(curr_sample_bits);
        curr_sample_bit_count = 0; // Reset count
        // Overflow if there is sample still in the output buffer 
        rv.overflow = output_reg.valid;        
        
        // Were these bits L or R data?
        // Last LR since last bit LR switched at falling edge for next channel potentially
        if(last_lr==LEFT) 
        {
          output_reg.data.l_data = curr_sample;
          l_sample_valid = 1;
          // Right sample next
          state = LR_WAIT;
        }
        else
        {
          output_reg.data.r_data = curr_sample;
          r_sample_valid = 1;
          // Left sample next
          state = RL_WAIT;
        }
        
        // Enough to output stream data of both LR samples?
        if(l_sample_valid & r_sample_valid)
        {
          output_reg.valid = 1;
          // Clear individual LR valid for next time
          l_sample_valid = 0;
          r_sample_valid = 0;
        }
      }
      else
      {
        // More bits coming
        curr_sample_bit_count += 1;
      }
    }    
    
    // Remember lr value for next iter
    last_lr = lr;
  }
  
  // Resets
  if(!reset_n)
  {
    state = RL_WAIT;
    last_lr = lr;
    curr_sample_bit_count = 0;
    l_sample_valid = 0;
    r_sample_valid = 0;
  }
  
  return rv;
}

// Logic to transmit I2S samples
typedef struct i2s_tx_t
{
  uint1_t samples_ready;
  uint1_t data;
}i2s_tx_t;
i2s_tx_t i2s_tx(stream(i2s_samples_t) samples, uint1_t lr, uint1_t sclk_falling_edge, uint1_t reset_n)
{
  // Registers
  static i2s_state_t state;
  static uint1_t last_lr;
  static uint1_t curr_sample_bits[SAMPLE_BITWIDTH];
  static uint5_t curr_sample_bit_count;
  static stream(i2s_samples_t) input_reg;
  static uint1_t l_sample_done;
  static uint1_t r_sample_done;
  static uint1_t output_data_reg;
  
  // Defaults
  i2s_tx_t rv;
  rv.data = output_data_reg;
  rv.samples_ready = !input_reg.valid; // Ready for new samples if have none
  
  // FSM Logic:
  
  // Everything occuring relative to sclk falling edges
  if(sclk_falling_edge)
  {
    // Waiting for R->L transition start of I2S frame, left sample data
    if(state==RL_WAIT)
    {
      output_data_reg = 0; // No out data until next sample
      if((last_lr==RIGHT) & (lr==LEFT))
      {
        // Must have valid sample to start I2S frame
        if(input_reg.valid)
        {
          // Next SCLK falling edge starts sample bits
          state = SAMPLE;
          // Make sure output reg has left data
          UINT_TO_BIT_ARRAY(curr_sample_bits, SAMPLE_BITWIDTH, input_reg.data.l_data.qmn)
          // Data is MSB first, output bit from top of array
          output_data_reg = curr_sample_bits[SAMPLE_BITWIDTH-1];
        }
      }
    }
    // Waiting for L->R transition start of right sample data
    else if(state==LR_WAIT)
    {
      output_data_reg = 0; // No out data until next sample
      if((last_lr==LEFT) & (lr==RIGHT))
      {
        // Input samples assumed valid at this point, now done with them, reset
        input_reg.valid = 0;
        // Next SCLK falling edge starts sample bits
        state = SAMPLE;
        // Make sure output reg has right data
        UINT_TO_BIT_ARRAY(curr_sample_bits, SAMPLE_BITWIDTH, input_reg.data.r_data.qmn)
        // Data is MSB first, output bit from top of array
        output_data_reg = curr_sample_bits[SAMPLE_BITWIDTH-1];
      }
    }
    // Transmitting sample data bits
    else // if(state==SAMPLE)
    {
      // Current bit is output is from reg above
      // Then shift bits up and out for next bit in MSB
      ARRAY_SHIFT_UP(curr_sample_bits, SAMPLE_BITWIDTH, 1)
      // Next data output bit from top of array
      output_data_reg = curr_sample_bits[SAMPLE_BITWIDTH-1];
      
      // Was this the last bit?
      if(curr_sample_bit_count==(SAMPLE_BITWIDTH-1))
      {
        curr_sample_bit_count = 0; // Reset count
        // Were these bits L or R data?
        // Last LR since last bit LR switched at falling edge for next channel potentially
        if(last_lr==LEFT)
        {
          l_sample_done = 1;
          // Right sample next
          state = LR_WAIT;
        }
        else
        {
          r_sample_done = 1;
          // Left sample next
          state = RL_WAIT;
        }
        
        // Done outputting both LR samples?
        if(l_sample_done & r_sample_done)
        {
          // Clear individual LR done for next time
          l_sample_done = 0;
          r_sample_done = 0;
        }
      }
      else
      {
        // More bits coming
        curr_sample_bit_count += 1;
      }
    }    
    
    // Remember lr value for next iter
    last_lr = lr;
  }
  
  // Data into input reg when ready
  if(rv.samples_ready)
  {
    input_reg = samples;
  }
  
  // Resets
  if(!reset_n)
  {
    state = RL_WAIT;
    last_lr = lr;
    curr_sample_bit_count = 0;
    input_reg.valid = 0;
    l_sample_done = 0;
    r_sample_done = 0;
    output_data_reg = 0;
  }
  
  return rv;
}

typedef struct i2s_mac_t
{
  i2s_rx_t rx;
  i2s_tx_t tx;
  app_to_i2s_t to_i2s;
}i2s_mac_t;
i2s_mac_t i2s_mac(
  uint1_t reset_n, 
  uint1_t rx_samples_ready, 
  stream(i2s_samples_t) tx_samples,
  i2s_to_app_t from_i2s
){
  // Registers to produce clocking common to RX and TX
  static uint3_t sclk_counter;
  static uint1_t sclk;
  static uint6_t lr_counter;
  static uint1_t lr;
  
  // Output signals
  i2s_mac_t rv;
  
  // Outputs clks from registers
  rv.to_i2s.tx_sclk = sclk;
  rv.to_i2s.rx_sclk = sclk;
  rv.to_i2s.tx_lrck = lr;
  rv.to_i2s.rx_lrck = lr;
  
  // SCLK toggling at half period count on MCLK rising edge
  uint1_t sclk_half_toggle = sclk_counter==((SCLK_PERIOD_MCLKS/2)-1);
  uint1_t sclk_rising_edge = sclk_half_toggle & (sclk==0);
  uint1_t sclk_falling_edge = sclk_half_toggle & (sclk==1);
  
  // Receive I2S samples
  i2s_rx_t rx = i2s_rx(from_i2s.rx_data, lr, sclk_rising_edge, rx_samples_ready, reset_n);
  rv.rx = rx;
  
  // Transmit I2S samples
  i2s_tx_t tx = i2s_tx(tx_samples, lr, sclk_falling_edge, reset_n);
  rv.to_i2s.tx_data = tx.data;
  rv.tx = tx;

  // Drive I2S clocking derived from current MCLK domain
  if(sclk_half_toggle)
  {
    // Do toggle and reset counter
    sclk = !sclk;
    sclk_counter = 0;
  }
  else
  {
    // No toggle yet, keep counting
    sclk_counter += 1;
  }
  
  // LR counting SCLK falling edges
  if(sclk_falling_edge)
  {
    // LR toggle at half period count 
    if(lr_counter==((LR_PERIOD_SCLKS/2)-1))
    {
      // Do toggle and reset counter
      lr = !lr;
      lr_counter = 0;
    }
    else
    {
      // No toggle yet, keep counting
      lr_counter += 1;
    }  
  }
  
  // Resets
  if(!reset_n)
  {
    sclk_counter = 0;
    sclk = 0;
    lr_counter = 0;
    lr = 0;
  }
  
  return rv;
}

//#define I2S_MAC_PORTS
#ifdef I2S_MAC_PORTS
// Instantiate the I2S MAC with globally visible + separate RX and TX wires

// RX
typedef struct i2s_mac_rx_to_app_t
{
  stream(i2s_samples_t) samples;
  uint1_t overflow; 
}i2s_mac_rx_to_app_t;
typedef struct app_to_i2s_mac_rx_t
{
  uint1_t samples_ready;
  uint1_t reset_n;
}app_to_i2s_mac_rx_t;
i2s_mac_rx_to_app_t i2s_mac_rx_to_app;
app_to_i2s_mac_rx_t app_to_i2s_mac_rx;
// TX
typedef struct i2s_mac_tx_to_app_t
{
  uint1_t samples_ready;
}i2s_mac_tx_to_app_t;
typedef struct app_to_i2s_mac_tx_t
{
  stream(i2s_samples_t) samples;
  uint1_t reset_n;
}app_to_i2s_mac_tx_t;
// Globally visible ports/wires
i2s_mac_tx_to_app_t i2s_mac_tx_to_app;
app_to_i2s_mac_tx_t app_to_i2s_mac_tx;

// Main func to instantiate i2s_mac connected to global wire ports 
MAIN_MHZ(i2s_mac_ports, I2S_MCLK_MHZ)
void i2s_mac_ports()
{
  // Signals
  i2s_mac_rx_to_app_t rx_to_app;
  i2s_mac_tx_to_app_t tx_to_app;
  
  // Read global signals from app
  app_to_i2s_mac_rx_t app_to_rx = app_to_i2s_mac_rx;
  app_to_i2s_mac_tx_t app_to_tx = app_to_i2s_mac_tx;
  
  // Send and receive sample streams using I2S MAC
  uint1_t reset_n = app_to_tx.reset_n & app_to_rx.reset_n; // Can split reset later
  i2s_mac_t mac = i2s_mac(reset_n, app_to_rx.samples_ready, app_to_tx.samples);  
    
  // Write global signals to app
  rx_to_app.samples = mac.rx.samples;
  rx_to_app.overflow = mac.rx.overflow;
  tx_to_app.samples_ready = mac.tx.samples_ready;
  i2s_mac_rx_to_app = rx_to_app;
  i2s_mac_tx_to_app = tx_to_app;
}
#endif