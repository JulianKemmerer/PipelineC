#!/usr/bin/env bash

# $1 is piplinec args
#   ex. PipelineC$ ./test_builds.sh "--comb --no_synth"
export PIPELINEC=../src/pipelinec
export EXAMPLES=../examples

set -e # Exit if anything fails

rm -rf TEST_OUTPUTS
mkdir TEST_OUTPUTS
cd TEST_OUTPUTS

"$PIPELINEC" "$EXAMPLES"/blink.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/open_tools.c $1
"$PIPELINEC" "$EXAMPLES"/pipeline_and_fsm.c $1
"$PIPELINEC" "$EXAMPLES"/global_fifo.c $1
"$PIPELINEC" "$EXAMPLES"/clock_crossing.c $1
"$PIPELINEC" "$EXAMPLES"/async_clock_crossing.c $1
"$PIPELINEC" "$EXAMPLES"/internal_clocks.c $1
"$PIPELINEC" "$EXAMPLES"/user_func_latency.c $1

"$PIPELINEC" "$EXAMPLES"/verilator/blink.c $1 --sim --verilator
"$PIPELINEC" "$EXAMPLES"/cocotb/blink.c $1 --sim --cocotb --ghdl

"$PIPELINEC" "$EXAMPLES"/tool_tests/vivado.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/quartus.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/diamond.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/gowin.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/efinity.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/cc_tools.c $1
"$PIPELINEC" "$EXAMPLES"/tool_tests/pyrtl.c $1

echo "TESTS DONE"

