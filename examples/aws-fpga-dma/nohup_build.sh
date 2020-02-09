#!/usr/bin/env bash

# Run PipelineC build
cd ~/src/project_data/PipelineC/;
rm -r /home/centos/pipelinec_syn_output; 
python -u ./src/main.py 2>&1

# Build dcp that will be turned into AFI
cd $CL_DIR/build/scripts
./aws_build_dcp_from_cl.sh
