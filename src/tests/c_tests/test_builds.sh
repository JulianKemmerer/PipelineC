#!/usr/bin/env bash

# $1 is pipelinec args
#   ex. src/tests/c_tests$ ./test_builds.sh "--comb --no_synth"
#   (runnable from any cwd -- paths are resolved relative to this script)
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/../../.." && pwd)"
export PIPELINEC="$REPO_ROOT/src/pipelinec"
export EXAMPLES="$REPO_ROOT/examples"

set -e # Exit if anything fails

rm -rf "$THIS_DIR/TEST_OUTPUTS"
mkdir "$THIS_DIR/TEST_OUTPUTS"
cd "$THIS_DIR/TEST_OUTPUTS"

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

