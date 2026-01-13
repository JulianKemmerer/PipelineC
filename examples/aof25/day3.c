//#pragma PART "xc7a100tcsg324-1" // FMAX ~180MHz
#pragma PART "LFE5U-85F-6BG381C" // FMAX ~100MHz
#define CLOCK_MHZ 100 // Limited by accum_max2digits stateful function
#include "uintN_t.h"
#include "arrays.h"
#include "global_func_inst.h"

// https://adventofcode.com/2025/day/3

#define DIGITS_PER_CYCLE 8 // Min 2
#define digit_pos_t uint3_t // log2(per cycle)
#define BANK_ROUNDED_SIZE 16 // Must be multiple of digits per cycle, rounded from 15 for example
#define BANK_SIZE 15
#define BANK_SIZE_ROUND_AMOUNT (BANK_ROUNDED_SIZE - BANK_SIZE) // size mod per cycle
// TODO param for how many batteries turned on, hard coded to 2...

// Pipeline consuming N digits from a bank per cycle and outputting pair of max digits
typedef struct max2digits_t{
  char msd;
  char lsd;
  uint1_t is_last_digits_of_bank;
}max2digits_t;
typedef struct cycle_digits_t{
  char digits[DIGITS_PER_CYCLE];
  uint1_t is_last_digits_of_bank;
}cycle_digits_t;
max2digits_t find_max_2_digits(cycle_digits_t input_cycle){
  max2digits_t max;
  // Pass through last flag
  max.is_last_digits_of_bank = input_cycle.is_last_digits_of_bank;
  // Do easy loops to find largest 2 digits left to right ordering
  // Find max first
  digit_pos_t msd_pos;
  for(uint32_t i = 0; i < DIGITS_PER_CYCLE; i+=1)
  {
    // Max digit can't be last digits (including rounding to array size multiple with null chars ignored)
    if(~(input_cycle.is_last_digits_of_bank & (i>=(DIGITS_PER_CYCLE-1-BANK_SIZE_ROUND_AMOUNT)))){
      if(input_cycle.digits[i] > max.msd){
        max.msd = input_cycle.digits[i];
        msd_pos = i;
      }
    }
  }
  // Second highest digit can only be found to right after max
  for(uint32_t i = 1; i < DIGITS_PER_CYCLE; i+=1)
  {
    if(i>msd_pos){
      if(input_cycle.digits[i] > max.lsd){
        max.lsd = input_cycle.digits[i];
      }
    }
  }
  printf("Max two digit value from %s(last=%d,msd_pos=%d): %c%c\n", input_cycle.digits, input_cycle.is_last_digits_of_bank, msd_pos, max.msd, max.lsd);
  return max;
}
// find_max_2_digits_pipeline : max2digits_t find_max_2_digits(cycle_digits_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like find_max_2_digits_pipeline _in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(find_max_2_digits_pipeline, max2digits_t, find_max_2_digits, cycle_digits_t)


// Inputs to dataflow
MAIN_MHZ(inputs_process, CLOCK_MHZ) // Other MAIN funcs absorb this clock domain
void inputs_process()
{
  // Hard code inputs for sim for now...
  #define TEST_SIZE 4
  static char input_strings[TEST_SIZE][BANK_ROUNDED_SIZE] = {
    "987654321111111",
    "811111111111119",
    "234234234234278",
    "818181911112111"
  };
  static uint32_t bank_counter;
  static uint32_t digit_counter;
  static uint1_t test_running = 1;
  uint1_t is_last_digits = digit_counter >= (BANK_ROUNDED_SIZE-DIGITS_PER_CYCLE);
  uint1_t is_last_bank_last_digits = (bank_counter==(TEST_SIZE-1)) & is_last_digits;
  ARRAY_COPY(find_max_2_digits_pipeline_in.digits, input_strings[0], DIGITS_PER_CYCLE)
  find_max_2_digits_pipeline_in.is_last_digits_of_bank = is_last_digits;
  find_max_2_digits_pipeline_in_valid = test_running;
  if(find_max_2_digits_pipeline_in_valid /*& find_max_2_digits_pipeline_in_ready*/){
    printf("Input bank %d digits[%d+:%d] next string: %s\n", bank_counter, digit_counter, DIGITS_PER_CYCLE, find_max_2_digits_pipeline_in.digits);
    ARRAY_SHIFT_DOWN(input_strings[0], BANK_ROUNDED_SIZE, DIGITS_PER_CYCLE)
    if(is_last_digits){
      // next bank
      digit_counter = 0;
      bank_counter += 1;
      ARRAY_SHIFT_DOWN(input_strings, TEST_SIZE, 1)
    }else{
      // next digits in bank
      digit_counter += DIGITS_PER_CYCLE;
    } 
    test_running = ~is_last_bank_last_digits;
  }
}


// BCD conversion func for single digit
uint4_t bcd_digit_to_value(char digit){
  return digit - '0';
}
// Mult by 10 without multipliers
uint7_t mul_by_10(uint7_t x){
  //     10x = 8x + 2x
  return (x << 3) + (x << 1);
}
// 2 BCD digits to uint
uint7_t bcd_to_value(max2digits_t digits){
  uint7_t rv = mul_by_10(bcd_digit_to_value(digits.msd)) +  bcd_digit_to_value(digits.lsd);
  printf("%c%c as uint = %d\n", digits.msd, digits.lsd, rv);
  return rv;
}
// bcd_to_value_pipeline : uint7_t bcd_to_value(max2digits_t)
//  instance of pipeline without handshaking but does include stream valid bit
//  delcares global variable wires as ports to connect to, named like bcd_to_value_pipeline _in/_out...
GLOBAL_PIPELINE_INST_W_VALID_ID(bcd_to_value_pipeline, uint7_t, bcd_to_value, max2digits_t)
// TODO this probably doesnt need to be a pipeline since small logic?



// Given possible update of 2 max digits update the current set of max digits found so far
// TODO dont do compares with 8b chars do preconversion in find_max_2_digits pipeline to uint uint4_t values
max2digits_t update_max2digits(max2digits_t current, max2digits_t update){
  max2digits_t next = current;
  // Next MSD is might be update msb or lsb
  // and update lsd cant replace msd if last digits
  uint1_t msd_next_is_lsd = (update.lsd > update.msd) & ~update.is_last_digits_of_bank;
  char max_update_digit = msd_next_is_lsd ? update.lsd : update.msd;
  uint1_t update_msd_used;
  uint1_t update_lsd_used;
  if(max_update_digit > current.msd){
    next.msd = max_update_digit;
    if(msd_next_is_lsd){
      update_lsd_used = 1;
    }else{
      update_msd_used = 1;
      // replacing next msd with update msd
      // means using update lsd too
      update_lsd_used = 1;
      next.lsd = update.lsd;
    }
  }
  // Next LSD is either update msb or lsb
  // if not already used above
  if( (update.msd > current.lsd) & ~update_msd_used){
    next.lsd = update.msd;
  }else if( (update.lsd > current.lsd) & ~update_lsd_used){
    next.lsd = update.lsd;
  }
  printf("Current %c%c updated by %c%c(last=%d) yields next: %c%c\n",
    current.msd,current.lsd,
    update.msd,update.lsd,update.is_last_digits_of_bank,
    next.msd,next.lsd);
  return next;
}

// Keeping running updated max pairs of digits that come out of find_max_2_digits pipeline
#pragma MAIN accum_max2digits
void accum_max2digits(){
  // Running max 2 digits for this bank
  static max2digits_t max;
  static uint1_t max_out_valid;
  // Output into next pipeline from regs, single cycle pulse resets max accum
  bcd_to_value_pipeline_in = max;
  bcd_to_value_pipeline_in_valid = max_out_valid;
  if(max_out_valid){
    max.lsd = 0;
    max.msd = 0;
    max_out_valid = 0;
  }
  if(find_max_2_digits_pipeline_out_valid){
    max = update_max2digits(max, find_max_2_digits_pipeline_out);
    if(find_max_2_digits_pipeline_out.is_last_digits_of_bank){
      // End of bank completed finding max 2 digits for valid output
      max_out_valid = 1;
      printf("Final max 2 digits of bank: %c%c\n", max.msd, max.lsd);
    }
  }
}


// Accumulate uint values coming out of bcd_to_value pipeline for final result
#pragma MAIN accum_joltage
uint32_t accum_joltage(){
  static uint32_t joltage;
  if(bcd_to_value_pipeline_out_valid){
    joltage += bcd_to_value_pipeline_out;
    printf("Total output joltage: %d\n", joltage);
  }
  // Return so doesnt synthesize away
  return joltage;
}