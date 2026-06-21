#!/bin/bash
set -e
reset
cd /media/1TB/Dropbox/PipelineC/git/PipelineC

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/autopipeline_test.py --out_dir ~/pypeline_run_all

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./examples/pypeline/vga_donut.py --out_dir ~/pypeline_run_all --comb

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./examples/pypeline/vga_test_pattern.py --out_dir ~/pypeline_run_all --comb

python3 ./src/pypeline_sim.py ./src/tests/pypeline_tests/inst/global_wires_sim_test.py --run 10

python3 ./src/tests/pypeline_tests/inst/float32_add_test.py
rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/float32_add_test.py --out_dir ~/pypeline_run_all --comb

python3 ./src/tests/pypeline_tests/inst/pypeline_test.py
rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/pypeline_test.py --out_dir ~/pypeline_run_all --comb

python3 ./src/tests/pypeline_tests/inst/reg_init_test.py
rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/reg_init_test.py --out_dir ~/pypeline_run_all --comb

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/if_test.py --out_dir ~/pypeline_run_all --comb

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/var_ref_test.py --out_dir ~/pypeline_run_all --comb

python3 ./src/tests/pypeline_tests/inst/bit_math_test.py
rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/bit_math_test.py --out_dir ~/pypeline_run_all --comb

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/old_sw_lib_ops.py --out_dir ~/pypeline_run_all --comb

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/global_wires_test.py --out_dir ~/pypeline_run_all --comb --no_synth

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/compound_init_test.py --out_dir ~/pypeline_run_all --comb --no_synth

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/bit_manip_test.py --out_dir ~/pypeline_run_all --comb --no_synth

rm -rf ~/pypeline_run_all/*; ./src/pipelinec ./src/tests/pypeline_tests/inst/import_test.py --out_dir ~/pypeline_run_all --comb --no_synth

