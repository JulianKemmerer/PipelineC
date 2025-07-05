#include "intN_t.h"
#include "uintN_t.h"
#include "stream/stream.h"
#include "stream/serializer.h"
#include "stream/deserializer.h"
#include "handshake/handshake.h"
#include "global_fifo.h"

// Complex Q1.15 Fixed Point
typedef struct ci16_t
{
  int16_t real, imag;
}ci16_t;

// 16-APSK LUT made with python (1/2 QPSK rotated pi/4 + 12-PSK)
ci16_t APSK16_LUT[16] = {{11584,11584},{-11584,11584},{-11584,-11584},{11584,-11584},{32767,0},{28377,16383},{16383,28377},{0,32767},{-16383,28377},{-28377,16383},{-32767,0},{-28377,-16383},{-16383,-28377},{0,-32767},{16383,-28377},{28377,-16383}};

// 32-APSK LUT made with python (1/3 * QPSK rotated pi/4 + 2/3 * 12-PSK rotated pi/12 + 16-PSK)
ci16_t APSK32_LUT[32] = {{7723,7723},{-7723,7723},{-7723,-7723},{7723,-7723},{21100,5653},{15446,15446},{5653,21100},{-5653,21100},{-15446,15446},{-21100,5653},{-21100,-5653},{-15446,-15446},{-5653,-21100},{5653,-21100},{15446,-15446},{21100,-5653},{32767,0},{30272,12539},{23169,23169},{12539,30272},{0,32767},{-12539,30272},{-23169,23169},{-30272,12539},{-32767,0},{-30272,-12539},{-23169,-23169},{-12539,-30272},{0,-32767},{12539,-30272},{23169,-23169},{30272,-12539}};

DECL_STREAM_TYPE(ci16_t)
DECL_STREAM_TYPE(uint8_t)
DECL_STREAM_TYPE(uint4_t)
DECL_STREAM_TYPE(uint5_t)
DECL_STREAM_TYPE(uint1_t)

DECL_HANDSHAKE_TYPE(ci16_t)
DECL_HANDSHAKE_TYPE(uint8_t)

// Serialize one 8b byte into two four bit half-octets
serializer_in_to_out(modulator_serializer_8_4, uint1_t, 8, 4)

ci16_t apsk16_map(uint4_t i){
  ci16_t o = APSK16_LUT[i];
  return o;
}

hs_out(ci16_t) apsk16_modulator(hs_in(uint8_t) i){
  hs_out(ci16_t) o;

  // Serializer input 8b
  uint1_t idata[8];
  UINT_TO_BIT_ARRAY(idata, 8, i.stream_in.data)

  modulator_serializer_8_4_t od = modulator_serializer_8_4(idata, i.stream_in.valid, i.ready_for_stream_out);
  o.ready_for_stream_in = od.in_data_ready;

  // Serializer output 4b
  uint4_t odata = uint1_array4_le(od.out_data);

  if(i.ready_for_stream_out & od.out_data_valid){
    o.stream_out.valid = 1;
    o.stream_out.data = apsk16_map(odata);
  }

  return o;
}

// FIFO To match rate 8/5
GLOBAL_STREAM_FIFO(uint1_t, apsk32_bit_fifo, 40)

// Serialize one 8b byte stream into 1 bit stream
serializer(mod_ser_8_1, uint1_t, 8)
// Deserialize one 1 bit stream into 5 bit stream
deserializer(mod_deser_1_5, uint1_t, 5)

ci16_t apsk32_map(uint5_t i){
  ci16_t o = APSK32_LUT[i];
  return o;
}

hs_out(ci16_t) apsk32_modulator(hs_in(uint8_t) i){
  hs_out(ci16_t) o;

  // Serializer input 8b
  uint1_t idata[8];
  UINT_TO_BIT_ARRAY(idata, 8, i.stream_in.data)

  // 8:1 Serializer -> FIFO
  mod_ser_8_1_o_t oser = mod_ser_8_1(idata, i.stream_in.valid, apsk32_bit_fifo_in_ready);
  apsk32_bit_fifo_in.data = oser.out_data;
  apsk32_bit_fifo_in.valid = oser.out_data_valid;
  
  // FIFO -> 1:5 Deserializer
  mod_deser_1_5_o_t odes = mod_deser_1_5(apsk32_bit_fifo_out.data, apsk32_bit_fifo_out.valid, i.ready_for_stream_out);
  apsk32_bit_fifo_out_ready = odes.in_data_ready;
  
  // Deserializer output 5b
  uint5_t odata = uint1_array5_le(odes.out_data);
  o.ready_for_stream_in = oser.in_data_ready;

  if(i.ready_for_stream_out & odes.out_data_valid){
    o.stream_out.valid = 1;
    o.stream_out.data = apsk32_map(odata);
  }

  return o;
}