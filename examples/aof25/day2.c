//#pragma PART "xc7a100tcsg324-1" // FMAX ~280 MHz
#pragma PART "LFE5U-85F-6BG381C" // ~140 MHz
#define CLOCK_MHZ 140 // Limited by range_iterator_fsm stateful function
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"
#include "arrays.h"
// Override default pipeline flow control fifo in-flight counter size to help timing
#define global_func_inst_counter_t uint6_t 
#include "global_func_inst.h"

// https://adventofcode.com/2025/day/2

// Max size params
#define MAX_DIGITS_WIDTH 10
#define HALF_MAX_DIGITS (MAX_DIGITS_WIDTH/2)
#define len_t uint5_t // log2(MAX_DIGITS_WIDTH)+1
#define pos_t int6_t // signed version of len
#define uint_t uint34_t // log2("9" * MAX_DIGITS_WIDTH) repeating digits
#define half_uint_t uint17_t
#define MAX_RANGE_STR_SIZE ((MAX_DIGITS_WIDTH*2)+1) // 2 numbers and 1 separator
#define range_str_len_t uint5_t // log2(MAX_RANGE_STR_SIZE)
#define range_str_pos_t int6_t // signed version of len

// Comments use example:
//  998-1012 has one invalid ID, 1010

// Input string from file
typedef struct range_string_t{
  char str[MAX_RANGE_STR_SIZE]; // str[0 to ..] = "998-1012_... padded with null to max
}range_string_t;
DECL_STREAM_TYPE(range_string_t)

// BCD conversion func for single digit
uint4_t bcd_digit_to_value(char digit){
  return digit - '0';
}

// Use compile time constant math loop 
// to make lookup table for powers of 10
// 10,100,1000 etc to one digit past max
// so -1 for half width of all 9999s can be computed
uint_t pow10_minus1_lut(len_t index)
{
  half_uint_t lut[HALF_MAX_DIGITS];
  uint_t multiplier = 10;
  for(int32_t i=0; i<HALF_MAX_DIGITS; i+=1){
    lut[i] = multiplier - 1;
    multiplier *= 10;
  }
  return lut[index];
}

// Mult by 10 without multipliers
uint_t mul_by_10(uint_t x){
  //     10x = 8x + 2x
  return (x << 3) + (x << 1);
}

// Convert ascii to uint, sized for half max digits
// ex. input bcd string [3 downto 0] = "__98", output 98
half_uint_t half_size_bcd_to_uint(char bcd[HALF_MAX_DIGITS])
{
  half_uint_t rv;
  half_uint_t MULT = 1;
  for(uint32_t i=0; i<HALF_MAX_DIGITS; i+=1){
    uint4_t digit_value = bcd_digit_to_value(bcd[i]);
    if(bcd[i]==0) digit_value = 0; // Null is zero value
    //rv += (half_uint_t)(digit_value x MULT);
    // Avoid multiply?
    //  TODO rework this still seems suspect in how hard it is to pipeline?
    // Only 10 possible values for digit_value x MULT
    half_uint_t possible_increments[10];
    for(uint4_t digit_value_i=0; digit_value_i < 10; digit_value_i+=1){
      possible_increments[digit_value_i] = digit_value_i * MULT; // compile time const mult
    }
    // just select for one of them to avoid multiply hardware
    half_uint_t increment = possible_increments[digit_value];
    rv += increment;
    MULT *= 10; // compile time const mult
  }
  //printf("BCD(reversed) %s = uint %d\n", bcd, rv);
  return rv;
}

// Preprocess range single string into separate fields
typedef struct decoded_range_strings_t{
  uint1_t both_lens_odd; // = 0 odd length ranges cant have two repeating halfs
  len_t half_len; // = 2 length of half unit, size of repeating seq
  // High and low bound most and least signficant digits
  half_uint_t high_msds_value; // = 10
  half_uint_t high_lsds_value; // = 12
  half_uint_t low_msds_value; // = 09 
  half_uint_t low_lsds_value; // = 98
  // MSDs used to specify range of repeat values to iterate over
  half_uint_t max_repeat_value; // 99 reduced down to high_msds_value 10
  half_uint_t min_repeat_value; // 10 low_msds_value=09 adjusted for no leading zeros
}decoded_range_strings_t;
DECL_STREAM_TYPE(decoded_range_strings_t)
decoded_range_strings_t decode_range(range_string_t range_str)
{
  decoded_range_strings_t decoded_range;

  // str[0 to ..] = "998-1012_...
  // Find pos of first '-' char
  // Will be in first MAX_DIGITS_WIDTH+1 chars
  range_str_pos_t dash_pos;
  for(int32_t i=0; i<(MAX_DIGITS_WIDTH+1); i+=1){
    if(range_str.str[i]=='-') dash_pos = i; // dash_pos = 3
  }
  // Find pos of first null char, searching from top/right
  // Smallest range to check is x-yy, so exclude those 4 chars at bottom/left
  range_str_pos_t null_pos = MAX_RANGE_STR_SIZE; // Implied after max size
  for(int32_t i=MAX_RANGE_STR_SIZE-1; i>=4; i-=1){
    if(range_str.str[i]==0) null_pos = i; // null_pos = 8
  }

  // Can compute lens based on pos
  len_t low_len = dash_pos; // = 3
  len_t high_len = null_pos - dash_pos - 1; // = 4
  // Shortcut odd length ranges?
  uint1_t low_len_is_odd = low_len(0);
  uint1_t high_len_is_odd = high_len(0);
  decoded_range.both_lens_odd = low_len_is_odd & high_len_is_odd;
  // Repeating size is half of lens (w odd size round up)
  len_t low_len_rounded = low_len;
  if(low_len_is_odd){
    low_len_rounded = low_len + 1; // 4
  }
  decoded_range.half_len = low_len_rounded >> 1; // 2

  // BCD arrays are downto
  // Use positions to copy into BCD buffers
  char low_bcd[MAX_DIGITS_WIDTH];  // [7 downto 0] = "_____998"
  char high_bcd[MAX_DIGITS_WIDTH]; // [7 downto 0] = "____1012"
  for(uint32_t bcd_pos=0; bcd_pos<MAX_DIGITS_WIDTH;bcd_pos+=1){
    range_str_pos_t low_pos = dash_pos-1-bcd_pos;
    if(low_pos >= 0){
      low_bcd[bcd_pos] = range_str.str[low_pos];
    }
    range_str_pos_t high_pos = null_pos-1-bcd_pos;
    if(high_pos > dash_pos)
    {
      high_bcd[bcd_pos] = range_str.str[high_pos];
    }
  }

  // Copy into least and most significant digit buffers half sized repeating unit [3:0]
  char low_msds[HALF_MAX_DIGITS];  // "___9"
  char low_lsds[HALF_MAX_DIGITS];  // "__98"
  char high_msds[HALF_MAX_DIGITS]; // "__10"
  char high_lsds[HALF_MAX_DIGITS]; // "__12"
  for(uint32_t half_i=0; half_i<HALF_MAX_DIGITS; half_i+=1){
    pos_t msds_bcd_pos = decoded_range.half_len + half_i;
    if(msds_bcd_pos < MAX_DIGITS_WIDTH){
      low_msds[half_i] = low_bcd[msds_bcd_pos];
      high_msds[half_i] = high_bcd[msds_bcd_pos];
    }
    pos_t lsds_bcd_pos = half_i;
    if(lsds_bcd_pos < decoded_range.half_len){
      low_lsds[half_i] = low_bcd[lsds_bcd_pos];
      high_lsds[half_i] = high_bcd[lsds_bcd_pos];
    }
  }

  // Convert half size units from ascii to numeric for later comparing/incrementing
  decoded_range.low_msds_value = half_size_bcd_to_uint(low_msds);
  decoded_range.low_lsds_value = half_size_bcd_to_uint(low_lsds);
  decoded_range.high_msds_value = half_size_bcd_to_uint(high_msds);
  decoded_range.high_lsds_value = half_size_bcd_to_uint(high_lsds);

  // Minumum value of repeating unit is based on low bound MSDs
  // cannot include leading zeros
  // replace leading 0 with round up to leading 1
  // "___9" -> "__10"
  char min_repeat_value_bcd[HALF_MAX_DIGITS] = low_msds;
  if(low_msds[decoded_range.half_len-1]==0){
    for(int32_t i=0; i<HALF_MAX_DIGITS; i+=1){
      if(i==(decoded_range.half_len-1)){
        min_repeat_value_bcd[i] = '1';
      }else{
        min_repeat_value_bcd[i] = '0';
      }
    }
  }
  decoded_range.min_repeat_value = half_size_bcd_to_uint(min_repeat_value_bcd);
  
  // Maximum value of repeating unit is based on half size
  decoded_range.max_repeat_value = pow10_minus1_lut(decoded_range.half_len-1);
  // Max repeat further reduced by high msds
  if(decoded_range.high_msds_value < decoded_range.max_repeat_value){
    decoded_range.max_repeat_value = decoded_range.high_msds_value;
  }

  return decoded_range;
}

// Logic to check if an invalid repeating sequence value is inside the range
typedef struct query_t{
  half_uint_t repeat;
  decoded_range_strings_t decoded_range;
}query_t;
//DECL_STREAM_TYPE(query_t)
uint1_t repeated_value_in_range(query_t query){
  // Know MSDs are in range based on how iterating so
  // further bounds checking is needed for LSDs at the edges of MSD ranges
  uint1_t in_range = 1;
  if(query.repeat == query.decoded_range.high_msds_value){
    if(query.repeat > query.decoded_range.high_lsds_value){
      in_range = 0;
    }
  }
  if(query.repeat == query.decoded_range.low_msds_value){
    if(query.repeat < query.decoded_range.low_lsds_value){
      in_range = 0;
    }
  }
  return in_range;
}
// Build uint value from repeating some digits
uint_t value_from_repeat(half_uint_t repeat, len_t half_len){
  half_uint_t lower_digits = repeat; // 0010 
  // Loop to repeatedly multiply by 10 
  uint_t upper_digits = repeat; // just LSDs start
  // Depending on how big the half size repeating unit is
  for(uint32_t i = 0; i < HALF_MAX_DIGITS; i+=1)
  {
    if(i < half_len){
      // 0100 then 1000, ex. shifting left in base 10
      upper_digits = mul_by_10(upper_digits);
    }
  }
  return lower_digits + upper_digits;
}
// Given query of repeating invalid digits and range
// return the uint of value if is in range, otherwise 0
uint_t invalid_check(query_t query)
{
  uint_t rv = 0;
  if(repeated_value_in_range(query)){
    uint_t rv = value_from_repeat(query.repeat, query.decoded_range.half_len);
    printf("Invalid ID: %d\n", rv);
  }//else{
  //  printf("Not Invalid ID: %d repeated not in range/not an ID\n", query.repeat);
  //}
  return rv;
}

// Hardware instances making inputs -> pipeline -> fsm -> pipeline -> output dataflow
// The automatic pipelines from pure comb logic functions declared below
// have a minimum of 2 clocks latency from input and output register stages

// decode_range_pipeline : decoded_range_strings_t decode_range(range_string_t)
//  instance of pipeline with valid ready handshaking and allowing 16 in flight operations
//  delcares global variable wires as ports to connect to, named like decode_range_pipeline_in/_out...
GLOBAL_VALID_READY_PIPELINE_INST(decode_range_pipeline, decoded_range_strings_t, decode_range, range_string_t, 16)

// invalid_check_pipeline : uint_t invalid_check(query_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like invalid_check_pipeline_in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(invalid_check_pipeline, uint_t, invalid_check, query_t)

// Inputs to dataflow
MAIN_MHZ(inputs_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void inputs_process()
{
  // Hard code inputs for sim for now...
  #define TEST_SIZE 11
  static char input_strings[TEST_SIZE][MAX_RANGE_STR_SIZE] = {
    "11-22",
    "95-115",
    "998-1012",
    "1188511880-1188511890",
    "222220-222224",
    "1698522-1698528",
    "446443-446449",
    "38593856-38593862",
    "565653-565659",
    "824824821-824824827",
    "2121212118-2121212124"
    // TODO add more from full input list, ex. 4-19
  };
  static uint32_t test_counter;
  static uint1_t test_running = 1;
  decode_range_pipeline_in.data.str = input_strings[0];
  decode_range_pipeline_in.valid = test_running;
  if(decode_range_pipeline_in.valid & decode_range_pipeline_in_ready){
    printf("Input #%d next range string %s\n", test_counter, input_strings[0]);
    ARRAY_SHIFT_DOWN(input_strings, TEST_SIZE, 1)
    test_running = test_counter < (TEST_SIZE-1);
    test_counter += 1;
  }
}

// decode_range_pipeline would be here in top to bottom dataflow...

// FSM for iterating over a range pulled from decode pipeline
// individual iterations are evaluated by sending data into the invalid checking pipeline
typedef enum state_t{
  GET_NEXT_RANGE,
  ITERATE_RANGE
}state_t;
#pragma MAIN range_iterator_fsm
void range_iterator_fsm()
{
  static state_t state;
  // Iterate over a range
  static decoded_range_strings_t decoded_range;
  // Checking if a repeated seq invalid value is in range
  static half_uint_t curr_repeat_value;
  // Default not ready for incoming ranges from decode pipeline
  decode_range_pipeline_out_ready = 0;
  // Default not inputting valid data into invalid check pipeline
  invalid_check_pipeline_in_valid = 0;
  if(state==GET_NEXT_RANGE)
  {
    // Ready for next range from decode pipeline
    decode_range_pipeline_out_ready = 1;
    // Repeat value starts from lower bound MSDs
    decoded_range = decode_range_pipeline_out.data;
    curr_repeat_value = decoded_range.min_repeat_value;
    // Upon receiving next range begin iterating
    if(decode_range_pipeline_out.valid & decode_range_pipeline_out_ready){
      state = ITERATE_RANGE;
      printf("Next decoded range: %d:%d - %d:%d (repeat unit size=%d, start=%d,end=%d)\n",
        decoded_range.low_msds_value, decoded_range.low_lsds_value,
        decoded_range.high_msds_value, decoded_range.high_lsds_value,
        decoded_range.half_len, decoded_range.min_repeat_value, decoded_range.max_repeat_value
      );
      // Unless is case for odd length ID values
      if(decoded_range.both_lens_odd){
        printf("Range cant have repeating half sequences since odd number of digits. Skipped.\n");
        state = GET_NEXT_RANGE; // Skip odd range, get next again
      }
    }
  }
  else // state==ITERATE_RANGE
  {
    // Iteration ends at upper bound MSDs
    if(curr_repeat_value <= decoded_range.max_repeat_value){
      // Put current query into checking pipeline
      query_t q;
      q.repeat = curr_repeat_value;
      q.decoded_range = decoded_range;
      invalid_check_pipeline_in = q;
      invalid_check_pipeline_in_valid = 1;
      printf("Checking repeat of value=%d (len=%d)...\n", curr_repeat_value, decoded_range.half_len);
      if(curr_repeat_value==decoded_range.max_repeat_value){
        state = GET_NEXT_RANGE;
      }
    }//else{
      //state = GET_NEXT_RANGE;
    //}
    // And increment for next
    curr_repeat_value += 1;
  }
}

// invalid_check_pipeline would be here in top to bottom dataflow...

// FSM for accumulating invalid values at output
#pragma MAIN accum_invalids
uint_t accum_invalids()
{
  // Accumulate invalid ids at output of invalid check pipeline
  static uint_t invalids_sum;
  if(invalid_check_pipeline_out_valid){
    invalids_sum += invalid_check_pipeline_out;
    if(invalid_check_pipeline_out > 0){
      printf("Output updated invalids sum + %d = %d\n",
        invalid_check_pipeline_out, invalids_sum);
    }
  }
  return invalids_sum; // for synth so doesnt optimize away
}

