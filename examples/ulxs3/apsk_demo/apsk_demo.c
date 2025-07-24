#include "modulator.h"
#include "stream/deserializer.h"
#include "dsp/dac.h"
#include "table.h"
//#include "global_fifo.h"

#pragma PART "LFE5U-85F-6BG381C"

// LED on off state
DECL_OUTPUT_REG(uint8_t, leds)
DECL_OUTPUT_REG(uint28_t, gp)

// CIC Interpolator
#define cic_name cic_interpolator       // Name
#define CIC_INTERP_FACTOR 512   // Interpolation factor
#define CIC_N_STAGES      1    // Number of stages
#define CIC_LOG2_N        9    // log2(CIC_INTERP_FACTOR)
#define cic_data_t  int16_t    // in_width
#define cic_accum_t int25_t    // data_width + CIC_N_STAGES * log2(CIC_INTERP_FACTOR)
#define cic_out_t   int16_t    // == cic_data_t
DECL_STREAM_TYPE(cic_data_t)
DECL_STREAM_TYPE(cic_accum_t)
#include "dsp/cic_interp.h"
#include "dsp/dac.h"

DECL_STREAM_TYPE(uint1_t)

// LFSR core
uint16_t lfsr_core(uint16_t lfsr, uint1_t enable){
    uint16_t rv;
    if(enable){
        uint16_t bit = ((lfsr >> 0) ^
            (lfsr >> 2) ^
            (lfsr >> 3) ^
            (lfsr >> 5)) & 1;
        rv =  (lfsr >> 1)  | (bit << 15);
    }
    else{
        rv = lfsr;
    }
    return rv;
}


// Outputs a 1bit stream of random values
stream(uint1_t) lfsr_update(uint1_t output_ready){
    static uint16_t lfsr;
    static uint1_t load_seed = 1;
    stream(uint1_t) o = {lfsr(0), output_ready}; // valid == ready

    if(load_seed){
      lfsr = 0xACE1;
      load_seed = 0;
    }
    
    lfsr = lfsr_core(lfsr, output_ready);

    return o;
}

deserializer(lfsr_deserializer, uint1_t, 8)

// Outputs a 8bit stream of random values
stream(uint8_t) lfsr_generator(uint1_t out_ready){
    static uint8_t o_data_reg;
    static uint1_t o_valid_reg;
    static uint8_t o_ready_reg;

    uint1_t lfsr_in_ready;
    #pragma FEEDBACK lfsr_in_ready

    stream(uint8_t) o = {.data = o_data_reg, .valid = o_valid_reg};

    // generate a new rnd bit
    stream(uint1_t) lfsr_bits = lfsr_update(lfsr_in_ready);

    // Deserialize 1b -> 8b
    lfsr_deserializer_o_t od = lfsr_deserializer(lfsr_bits.data, lfsr_bits.valid, out_ready);
    lfsr_in_ready = od.in_data_ready;
    
    uint8_t odata = uint1_array8_le(od.out_data);

    o_ready_reg = out_ready;

    if(od.out_data_valid & o_ready_reg){
        o_data_reg = odata;
        o_valid_reg = od.out_data_valid;
    }
    else{
        o_valid_reg = 0;
    }

    leds = o_data_reg;

    return o;
}

DECL_HANDSHAKE_TYPE(ci16_t)

hs_out(ci16_t) cic_interpolate(hs_in(ci16_t) input){
    // REAL
    stream(int16_t) lpf_in_i = {input.stream_in.data.real, input.stream_in.valid};
    hs_out(int25_t) lpf_out_i = cic_interpolator(lpf_in_i);
  
    // IMAG
    stream(int16_t) lpf_in_q = {input.stream_in.data.imag, input.stream_in.valid};
    hs_out(int25_t) lpf_out_q = cic_interpolator(lpf_in_q);
  
    // join back
    hs_out(ci16_t) output;
    output.stream_out.data.real = (int16_t)(lpf_out_i.stream_out.data >> 9);
    output.stream_out.data.imag = (int16_t)(lpf_out_q.stream_out.data >> 9);
    output.stream_out.valid = lpf_out_i.stream_out.valid & lpf_out_q.stream_out.valid;
    output.ready_for_stream_in = lpf_out_i.ready_for_stream_in || lpf_out_q.ready_for_stream_in;
    return output;
}

stream(ci16_t) mixer(stream(ci16_t) lo, stream(ci16_t) iq){
    stream(ci16_t) o;
    o.data.real = (lo.data.real * iq.data.real - lo.data.imag * iq.data.imag) >> 15;
    o.data.imag = (lo.data.real * iq.data.imag - lo.data.imag * iq.data.real) >> 15;
    o.valid = lo.valid & iq.valid;
    return o;
}

uint8_t phase_gen(){
    static uint8_t phase;
    phase += 64;
    return phase;
}

int16_t nco_cos(uint8_t phase){
    static int16_t my_ram[NCO_TABLESIZE] = NCO_TABLE_COS;
    int16_t o = my_ram_RAM_SP_RF_0(phase, 0, 0);
    return o;
}

int16_t nco_sin(uint8_t phase){
    static int16_t my_ram[NCO_TABLESIZE] = NCO_TABLE_SIN;
    int16_t o = my_ram_RAM_SP_RF_0(phase, 0, 0);
    return o;
}

stream(ci16_t) nco_generator(uint8_t phase){
    stream(ci16_t) o;
    o.data.real = nco_cos(phase);
    o.data.imag = nco_sin(phase);
    o.valid = 1;
    return o;
}

typedef struct clkdiv_t
{
    uint1_t overflow;
    uint1_t clk;
}clkdiv_t;

clkdiv_t clkdiv(){
    static uint10_t ctr;
    static uint2_t clkreg;

    clkdiv_t o;
    o.clk = clkreg(0);

    if(ctr == 511){
        ctr = 0;
        clkreg += 1;
        o.overflow = 1;
    }
    else{
        o.overflow = 0;
        ctr += 1;
    }

    return o;
}

DECL_HANDSHAKE_INST_TYPE(ci16_t, uint8_t)
DECL_HANDSHAKE_INST_TYPE(ci16_t, ci16_t)

#pragma MAIN_MHZ main 30.72
void main(){
    clkdiv_t cd = clkdiv(); // sampling clock ref gen...
    //uint1_t mod_out_ready = cd.overflow; // "Hack" to limit the Baseband rate to 60KHz

    uint1_t lfsr_out_ready;
    #pragma FEEDBACK lfsr_out_ready

    //uint1_t mod_out_ready;
    //#pragma FEEDBACK mod_out_ready
    //uint1_t cic_out_ready = 1;
    
    stream(ci16_t) cic_stream;

    // -------------------- Baseband Generation Stage ------------------- //

    // LFSR Random Byte generation
    stream(uint8_t) u8_stream = lfsr_generator(lfsr_out_ready);

    // APSK Modulation
    DECL_HANDSHAKE_INST(lfsr_to_mod, ci16_t, apsk32_modulator, uint8_t)
    HANDSHAKE_FROM_STREAM(lfsr_to_mod, u8_stream, lfsr_out_ready)

    // Expansion of the macro above
    //hs_in(uint8_t) mod_inp = {.stream_in = u8_stream, .ready_for_stream_out = mod_out_ready};
    //hs_out(ci16_t) mod_outp = apsk32_modulator(mod_inp);
    //lfsr_out_ready = mod_outp.ready_for_stream_in;

    // 512x Interpolation (Baseband)
    DECL_HANDSHAKE_INST(mod_to_cic, ci16_t, cic_interpolate, ci16_t)
    HANDSHAKE_CONNECT(mod_to_cic, lfsr_to_mod)
    STREAM_FROM_HANDSHAKE(cic_stream, 1, mod_to_cic)

    // Expansion of the macro above
    //hs_in(ci16_t) cic_inp = {.stream_in = mod_outp.stream_out, .ready_for_stream_out = 1};
    //hs_out(ci16_t) cic_outp = cic_interpolate(cic_inp);
    //cic_stream = cic_outp.stream_out;
    //mod_out_ready = cic_outp.ready_for_stream_in;

    // -------------------- Digital UpConversion Stage ------------------- //

    // NCO Phase generation
    uint8_t phase = phase_gen();

    // Complex Local Oscillator at FCLK/4
    stream(ci16_t) lo_stream = nco_generator(phase);

    // Quadrature Mixer 
    stream(ci16_t) rf = mixer(lo_stream, cic_stream);

    // -------------------- Output Stage ------------------- //

    // Baseband Output Quadrature DAC's 
    uint1_t dac_i = sigma_delta_lowpass_2nd_ord_dac(cic_stream.data.real);
    uint1_t dac_q = sigma_delta_lowpass_2nd_ord_dac(cic_stream.data.imag);

    // RF Output DAC 
    uint1_t dac_rf = sigma_delta_bandpass_dac(rf.data.real + rf.data.imag);

    // PIN Mapping
    uint28_t gpios;
    gpios = uint28_uint1_0(gpios, dac_i);
    gpios = uint28_uint1_1(gpios, dac_q);
    gpios = uint28_uint1_2(gpios, cd.clk);
    gpios = uint28_uint1_3(gpios, dac_rf);
    gp = gpios;
}

/*

#define UART_CLK_MHZ 122.88
#define UART_BAUD 9600
#include "uart/uart_mac.h"

// TX side
// Globally visible ports / wires
// Inputs
stream(uint8_t) uart_tx_mac_word_in;
// Outputs
uint1_t uart_tx_mac_in_ready;
uint1_t uart_tx;
#pragma MAIN uart_tx_mac
//MAIN_MHZ(uart_tx_mac, UART_CLK_MHZ)
void uart_tx_mac()
{
  // Input one 8b word into serializer buffer and get eight single bits
  uint1_t word_in[UART_WORD_BITS];
  UINT_TO_BIT_ARRAY(word_in, UART_WORD_BITS, uart_tx_mac_word_in.data)
  // Ready is FEEDBACK doesnt get a value until later
  uint1_t ready_for_bit_stream;
  #pragma FEEDBACK ready_for_bit_stream
  uart_serializer_o_t ser = uart_serializer(
    word_in, 
    uart_tx_mac_word_in.valid,
    ready_for_bit_stream
  );
  uart_tx_mac_in_ready = ser.in_data_ready;
  stream(uint1_t) bit_stream;
  bit_stream.data = ser.out_data;
  bit_stream.valid = ser.out_data_valid;

  // Transmit bit stream onto output wire
  uart_tx_1b_t uart_tx_1b_out = uart_tx_1b(
    bit_stream
  );
  uart_tx = uart_tx_1b_out.output_wire;
  // Finally have FEEDBACK ready for serializer
  ready_for_bit_stream = uart_tx_1b_out.ready_for_bit_stream; 
}


DECL_STREAM_TYPE(uint1_t)
DECL_STREAM_TYPE(uint8_t)
DECL_STREAM_TYPE(int16_t)

// CIC 512x 1 stage
DECL_STREAM_TYPE(int25_t)
#define cic_name lpf_iq        // Name
#define CIC_INTERP_FACTOR 512  // Interpolation factor
#define CIC_N_STAGES      1    // Number of stages
#define CIC_LOG2_N        9    // log2(CIC_INTERP_FACTOR)
#define cic_data_t  int16_t    // in_width
#define cic_accum_t int25_t    // data_width + CIC_N_STAGES * log2(CIC_INTERP_FACTOR)
#define cic_out_t   int16_t    // == cic_data_t
#include "dsp/cic_interp.h"

// CIC 25x 1 stage
DECL_STREAM_TYPE(int21_t)
#define cic_name lpf_iq_25x        // Name
#define CIC_INTERP_FACTOR 25    // Interpolation factor
#define CIC_N_STAGES      1    // Number of stages
#define CIC_LOG2_N        5    // log2(CIC_INTERP_FACTOR)
#define cic_data_t  int16_t    // in_width
#define cic_accum_t int21_t    // data_width + CIC_N_STAGES * log2(CIC_INTERP_FACTOR)
#define cic_out_t   int16_t    // == cic_data_t
#include "dsp/cic_interp.h"
*/

/*
// FIR 25x 1 stage
#define fir_interp_name interp_25x
#define FIR_INTERP_N_TAPS 128
#define FIR_INTERP_LOG2_N_TAPS 7
#define FIR_INTERP_FACTOR 25 
#define fir_interp_data_t int16_t
#define fir_interp_data_stream_t stream(int16_t)
#define fir_interp_coeff_t int16_t
#define fir_interp_accum_t int39_t // data_width + coeff_width + log2(taps#)
#define fir_interp_out_t int16_t
#define fir_interp_out_stream_t stream(int16_t)
#define FIR_INTERP_OUT_SCALE 3 // normalize, // 3x then 8x(<<3) w pow2 scale = 24
#define FIR_INTERP_POW2_DN_SCALE (15-3) // data_width + coeff_width - out_width - 1 // fixed point adjust
#define FIR_INTERP_COEFFS {0,2,10,23,40,60,82,104,122,134,137,127,101,57,-8,-98,-213,-355,-524,-718,-936,-1175,-1430,-1695,-1963,-2228,-2479,-2707,-2902,-3052,-3145,-3171,-3117,-2973,-2729,-2375,-1903,-1307,-581,275,1264,2385,3632,5001,6481,8061,9730,11470,13264,15094,16940,18779,20589,22349,24035,25627,27102,28441,29625,30638,31467,32099,32525,32740,32740,32525,32099,31467,30638,29625,28441,27102,25627,24035,22349,20589,18779,16940,15094,13264,11470,9730,8061,6481,5001,3632,2385,1264,275,-581,-1307,-1903,-2375,-2729,-2973,-3117,-3171,-3145,-3052,-2902,-2707,-2479,-2228,-1963,-1695,-1430,-1175,-936,-718,-524,-355,-213,-98,-8,57,101,127,137,134,122,104,82,60,40,23,10,2,0}
#include "dsp/fir_interp.h"
*/

/*

// Outputs a 1bit stream of random values
stream(uint1_t) lfsr_update(uint1_t output_ready){
    static uint16_t lfsr;
    static uint1_t load_seed = 1;
    stream(uint1_t) o = {lfsr(0), output_ready}; // valid == ready

    if(load_seed){
      lfsr = 0xACE1;
      load_seed = 0;
    }
    
    lfsr = lfsr_core(lfsr, output_ready);

    return o;
}

deserializer(lfsr_deserializer, uint1_t, 8)

// Outputs a 8bit stream of random values
stream(uint8_t) lfsr_generator(uint1_t out_ready){
    static uint8_t o_data_reg;
    static uint1_t o_valid_reg;
    static uint8_t o_ready_reg;

    uint1_t lfsr_in_ready;
    #pragma FEEDBACK lfsr_in_ready

    stream(uint8_t) o = {.data = o_data_reg, .valid = o_valid_reg};

    // generate a new rnd bit
    stream(uint1_t) lfsr_bits = lfsr_update(lfsr_in_ready);

    // Deserialize 1b -> 8b
    lfsr_deserializer_o_t od = lfsr_deserializer(lfsr_bits.data, lfsr_bits.valid, out_ready);
    lfsr_in_ready = od.in_data_ready;
    
    uint8_t odata = uint1_array8_le(od.out_data);

    o_ready_reg = out_ready;

    if(od.out_data_valid & o_ready_reg){
        o_data_reg = odata;
        o_valid_reg = od.out_data_valid;
    }
    else{
        o_valid_reg = 0;
    }

    return o;
}

DECL_OUTPUT(uint8_t, lfsr_data)
DECL_OUTPUT(uint1_t, lfsr_valid)
DECL_OUTPUT(uint1_t, lfsr_ready)

DECL_OUTPUT(int16_t, mod_data_i)
DECL_OUTPUT(int16_t, mod_data_q)
DECL_OUTPUT(uint1_t, mod_valid)
DECL_OUTPUT(uint1_t, mod_oready)
DECL_OUTPUT(uint1_t, mod_iready)

GLOBAL_STREAM_FIFO(uint8_t, global_fifo, 8)

#pragma MAIN lfsr_main
void lfsr_main(){
    global_fifo_in = lfsr_generator(global_fifo_in_ready);

    lfsr_data = global_fifo_in.data;
    lfsr_valid = global_fifo_in.valid;
    lfsr_ready = global_fifo_in_ready;
}

stream(ci16_t) fir_interpolate(stream(ci16_t) input){
    // REAL
    stream(int16_t) interp_in_i = {input.data.real, input.valid};
    stream(int16_t) interp_out_i = interp_25x(interp_in_i);
  
    // IMAG
    stream(int16_t) interp_in_q = {input.data.imag, input.valid};
    stream(int16_t) interp_out_q = interp_25x(interp_in_q);
  
    // join back
    stream(ci16_t) output = {{interp_out_i.data, interp_out_q.data}, interp_out_i.valid & interp_out_q.valid};
    return output;
}

*/

// GLOBAL_STREAM_FIFO(ci16_t, iq_fifo, 32)
// 
// GLOBAL_STREAM_FIFO(uint8_t, data_fifo, 32)
/*

stream(ci16_t) cic_interpolate(stream(ci16_t) input){
    // REAL
    stream(int16_t) lpf_in_i = {input.data.real, input.valid};
    stream(int25_t) lpf_out_i = lpf_iq(lpf_in_i);
  
    // IMAG
    stream(int16_t) lpf_in_q = {input.data.imag, input.valid};
    stream(int25_t) lpf_out_q = lpf_iq(lpf_in_q);
  
    // join back
    stream(ci16_t) output = {.data = {.real = lpf_out_i.data >> 9, .imag = lpf_out_q.data >> 9}, .valid = lpf_out_i.valid};
    return output;
}


stream(ci16_t) cic_interpolate_2(stream(ci16_t) input){
    // REAL
    stream(int16_t) lpf_in_i = {input.data.real, input.valid};
    stream(int21_t) lpf_out_i = lpf_iq_25x(lpf_in_i);
  
    // IMAG
    stream(int16_t) lpf_in_q = {input.data.imag, input.valid};
    stream(int21_t) lpf_out_q = lpf_iq_25x(lpf_in_q);
  
    // join back
    stream(ci16_t) output = {.data = {.real = lpf_out_i.data >> 5, .imag = lpf_out_q.data >> 5}, .valid = lpf_out_i.valid};
    return output;
}

typedef struct beacon_t
{
  uint1_t rf_a;
  uint1_t rf_b;
  uint1_t uart_txb;
}beacon_t;

// Main SDR Datapath
beacon_t sdr_tx_datapath()
{
  uint1_t sample_ready = ready_gen();

  // LFSR Gen
  stream(uint8_t) data_stream = lfsr_generator(data_fifo_in_ready);
  
  // APSK MOD
  //apsk16_mod_in_t mod_inp = {.i_stream = data_fifo_out, .o_ready = iq_fifo_in_ready};
  //apsk16_mod_out_t mod_output = apsk16_modulator(mod_inp);


  // CIC 25x interp
  stream(ci16_t) x25_stream = cic_interpolate_2(iq_fifo_out);

  // CIC 512x interp
  stream(ci16_t) iq_stream = cic_interpolate(x25_stream);

  // DAC Sigma Delta conversion 
  uint1_t rf_i = sigma_delta_lowpass_dac(iq_stream.data.real);
  uint1_t rf_q = sigma_delta_lowpass_dac(iq_stream.data.imag);
  
  // return data
  beacon_t rv = {.rf_a = rf_i, .rf_b = rf_q, .uart_txb = uart_tx};

  // D.FIFO DVR
  data_fifo_in = data_stream;
  data_fifo_out_ready = uart_tx_mac_in_ready; //mod_output.i_ready;

  // IQ.FIFO DVR
  iq_fifo_in = nco_gen(iq_fifo_in_ready); // mod_output.o_stream;
  iq_fifo_out_ready = sample_ready;

  // uart dvr
  uart_tx_mac_word_in = data_fifo_out;
  //uart_tx_mac_in_ready;

  uint8_t ledval = 0;
  uint8_t data = data_fifo_out.data;
  ledval = uint8_uint1_0(ledval, data_fifo_in_ready);
  ledval = uint8_uint1_1(ledval, data_fifo_out_ready);
  ledval = uint8_uint1_2(ledval, iq_fifo_in_ready);
  ledval = uint8_uint1_3(ledval, iq_fifo_out_ready);
  ledval = uint8_uint4_4(ledval, data(3,0));
  leds = ledval;

  return rv;
}


#pragma MAIN_MHZ mod_main 122.88
void mod_main(){
    // 9.6Kbps APSK Beacon
    beacon_t newval_rf = sdr_tx_datapath();

    // Write to pin
    uint28_t gpio_vals = 0;
    gpio_vals = uint28_uint1_0(gpio_vals, newval_rf.rf_a);
    //gpio_vals = uint28_uint1_1(gpio_vals, newval_rf.rf_b);
    //gpio_vals = uint28_uint1_2(gpio_vals, newval_rf.uart_txb);
    gp = gpio_vals;
}
*/