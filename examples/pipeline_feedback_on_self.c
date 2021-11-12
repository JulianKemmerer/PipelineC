// A single pipeline that loops its output back on itself
// It has two inputs and two outputs, the first output loops back
// to become the second input after some N cycles of pipeline delay

#include "wire.h"
#include "intN_t.h"

typedef struct in1_t
{
  int32_t a;
  int32_t b;
}in1_t;

// Also out1 type
typedef struct in2_t
{
  int32_t c;
  int32_t d;
}in2_t;

typedef struct out2_t
{
  int32_t e;
}out2_t;

typedef struct pipeline_output_t
{
  in2_t out1;
  out2_t out2;
}pipeline_output_t;

pipeline_output_t the_pipeline(in1_t in1, in2_t in2)
{
  // Dummy math
  pipeline_output_t o;
  o.out1.c = in1.a + in2.c;
  o.out1.d = in1.b - in2.d;
  o.out2.e = o.out1.d * o.out1.c;
  return o;
}

#pragma MAIN_MHZ main 170.0

/*
in2_t out1_feedback;
#include "clock_crossing/out1_feedback.h"
out2_t main(in1_t in1)
{
  // No globals or static locals are used in this func directly
  // Only through WIRE macros which prevent like-a-register use of out1_feedback
  in2_t in2;
  WIRE_READ(in2_t, in2, out1_feedback) // in2 = out1_feedback
  
  pipeline_output_t both_outputs = the_pipeline(in1, in2);
  
  WIRE_WRITE(in2_t, out1_feedback, both_outputs.out1) // out1_feedback = both_outputs.out1

  return both_outputs.out2;
}*/

out2_t main(in1_t in1)
{
  // Non-volatile static would force this func to be comb. logic.
  volatile static in2_t out1_vol_feedback_reg;
  
  in2_t in2 = out1_vol_feedback_reg;

  pipeline_output_t both_outputs = the_pipeline(in1, in2);
  
  out1_vol_feedback_reg = both_outputs.out1;

  return both_outputs.out2;
}
