#!/usr/bin/env bash

# Run PipelineC build
cd ~/src/project_data/PipelineC/;
python3 -u ./src/main.py 2>&1

# Build dcp that will be turned into AFI
echo "Beginning AWS build process..."
cd $CL_DIR/build/scripts
#./aws_build_dcp_from_cl.sh
# In order to use a 250 MHz main clock the developer can specify the A1 Clock Group A Recipe
./aws_build_dcp_from_cl.sh -clock_recipe_a A1
