#pragma once
// Module that allows internal VGA timing to be aligned with 
// externally supplied VGA signals
#define EXT_VGA_TIMING
#include "vga_signals.h"

// Wire from output of pixel render pipeline
// that needs to be aligned with corresponding external signal
vga_signals_t external_vga_timing_feedback;
#include "clock_crossing/external_vga_timing_feedback.h"

// Wire to internal vga timing module
// that signals to stall/stop incrementing counters, etc
#include "vga_stall_signal.c"

// Include regular VGA timing module now with external timing hooks enabled and visible
#include "vga_timing.h"

// This code uses start of frame for alignment, but any position could work

// 1. Wait for SOF valid data to come out of the pixel pipeline
// 2. Stall/pause vga timing / inputs to pipeline (at delayed x,y position)
// 3. Wait for SOF valid data to occur from external signal, release stall/pause
// 4. Wait for misaligned data to flush through pipeline
// 5. Monitor for misaligned SOF, if so, restart
typedef enum ext_vga_state_t
{
  STALL_AT_FEEDBACK_SOF,
  START_AT_EXTERNAL_SOF,
  WAIT_PIPELINE_FLUSH,
  MONITOR_ALIGNMENT
}ext_vga_state_t;

// Top level external vga connections
#pragma MAIN ext_vga
void ext_vga(uint16_t x, uint16_t y)
{
  // Stall the internal timing to become aligned with external timing based on output timing feedback
  vga_signals_t vga_timing_feedback;
  WIRE_READ(vga_signals_t, vga_timing_feedback, external_vga_timing_feedback)

  // SOF from feedback signal
  uint1_t feedback_sof = vga_timing_feedback.active & vga_timing_feedback.start_of_frame;
  // SOF from external signal naively from just x==0 and y==0
  uint1_t external_sof = (x == 0) & (y == 0);

  // Little state machine to manage stalling/pausing for vga timing alignment
  static ext_vga_state_t state;
  uint1_t stall_req = 0;
  if(state == STALL_AT_FEEDBACK_SOF)
  {
    // Wait for feedback signal to have start of frame
    if(feedback_sof)
    {
      // Then stall
      stall_req = 1;
      // And move to state waiting for external SOF
      state = START_AT_EXTERNAL_SOF;
    }
  }
  else if(state == START_AT_EXTERNAL_SOF)
  {
    // Stall until external timing indicates start of frame
    stall_req = 1;
    if(external_sof)
    {
      // Then release stall
      stall_req = 0;
      // And allow data to flush through pipeline
      state = WAIT_PIPELINE_FLUSH;
    }
  }
  else if(state == WAIT_PIPELINE_FLUSH)
  {
    // Waiting a whole frame is more than enough...
    if(external_sof)
    {
      state = MONITOR_ALIGNMENT;
    }
  }
  else if(state == MONITOR_ALIGNMENT)
  {
    // Expect that feedback and external signals are aligned
    if(external_sof != feedback_sof)
    {
      // If not, restart
      state = STALL_AT_FEEDBACK_SOF;
    }
  }

  // Signal stall to vga timing module
  vga_req_stall = stall_req;
}