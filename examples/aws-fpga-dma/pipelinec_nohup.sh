#!/usr/bin/env bash

# Run PipelineC build
mkdir ~/pipelinec_syn_output/
cd ~/src/project_data/PipelineC/src;
python3 -u ./pipelinec 2>&1 | tee ~/pipelinec_syn_output/out.log

