#!/usr/bin/env python

import os
import sys

import C_TO_LOGIC
import SIM
import SYN
import VIVADO
from utilities import GET_TOOL_PATH, REPO_ABS_DIR

# Default to env if there
TOOL_EXE = "vsim"
ENV_TOOL_PATH = GET_TOOL_PATH(TOOL_EXE)
if ENV_TOOL_PATH:
    MODELSIM_PATH = ENV_TOOL_PATH
else:
    # MODELSIM_PATH="/media/1TB/Programs/Linux/Modelsim/modelsim_ase/bin/vsim"
    MODELSIM_PATH = "/media/1TB/Programs/Linux/Modelsim18.0.0.219/modelsim_ase/bin/vsim"

MODEL_SIM_INI_TEXT = ""
with open(REPO_ABS_DIR() + "/src/text/model_sim_ini.txt", "r") as ms_ini:
    MODEL_SIM_INI_TEXT = ms_ini.read()


def DO_OPTIONAL_DEBUG(do_debug=False, latency=0):
    # DO DEBUG PROJECT?
    if not do_debug:
        return

    print(
        "================== Doing Optional Modelsim Debug ================================",
        flush=True,
    )
    # #######################################################################################################

    # Get all vhd files in syn output
    vhd_files = SIM.GET_SIM_FILES(latency=0)

    # TODO write some kind of helpers from commmon SimGenInfo?

    # .do FILE to execute:
    proj_name = "pipelinc_proj"
    proj_dir = SYN.SYN_OUTPUT_DIRECTORY + "/"
    text = ""
    text += (
        """
  project new {"""
        + proj_dir
        + """} """
        + proj_name
        + """
  """
    )

    # Compile ieee_proposed in fixed/float support?
    if SYN.SYN_TOOL is VIVADO:
        text += (
            """vcom -work ieee_proposed -2002 -explicit -stats=none """
            + VIVADO.VIVADO_DIR
            + "/scripts/rt/data/fixed_pkg_c.vhd"
            + "\n"
        )
        text += (
            """vcom -work ieee_proposed -2002 -explicit -stats=none """
            + VIVADO.VIVADO_DIR
            + "/scripts/rt/data/float_pkg_c.vhd"
            + "\n"
        )

    # Add all files
    for vhd_file in vhd_files:
        text += (
            """
  project addfile {"""
            + vhd_file
            + """}
  """
        )

    # Compile to work library?
    text += """
  project calculateorder
  project compileall
  vlib work
  vmap work work
  """
    # Do vsim too?
    # vsim work.main_bin_op_sl_main_c_7_top

    # Identify tool versions
    if os.path.exists(MODELSIM_PATH):
        print(MODELSIM_PATH, flush=True)
    else:
        raise Exception("vsim executable not found!")

    ini_filepath = proj_dir + "pipelinec_modelsim.ini"
    f = open(ini_filepath, "w")
    f.write(MODEL_SIM_INI_TEXT)
    f.close()
    do_filename = proj_name + ".do"
    do_filepath = proj_dir + do_filename
    f = open(do_filepath, "w")
    f.write(text)
    f.close()

    # Run modelsim
    bash_cmd = (
        MODELSIM_PATH
        + " "
        + "-modelsimini "
        + ini_filepath
        + " "
        + "-do 'source {"
        + do_filepath
        + "}' "
    )
    print(bash_cmd, flush=True)

    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd)
    print(log_text, flush=True)
    sys.exit(-1)
