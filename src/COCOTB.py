import os
import sys

import C_TO_LOGIC
import SYN
from utilities import GET_TOOL_PATH

def DO_SIM(multimain_timing_params, parser_state, args):
    print(
        "================== Doing cocotb Simulation ================================",
        flush=True,
    )

    # Check for cocotb-config tool
    tool_path = GET_TOOL_PATH("cocotb-config") 
    if tool_path is None:
      raise Exception("cocotb does not appear installed. cocotb-config not in path!")
    print(tool_path)

    # Generate a template py script and make file
    # Or use user specified makefile(and .py)
    COCOTB_OUT_DIR = SYN.SYN_OUTPUT_DIRECTORY + "/cocotb"
    if not os.path.exists(COCOTB_OUT_DIR):
        os.makedirs(COCOTB_OUT_DIR)
    makefile_path = COCOTB_OUT_DIR + "/" + "Makefile"
    makefile_dir = COCOTB_OUT_DIR
    if args.makefile:
      # Existing makefile
      makefile_path = os.path.abspath(args.makefile)
      makefile_dir = os.path.dirname(makefile_path)
    else:
      # Generate makefile (and dummy tb)
      raise NotImplementedError("Implement makefile generation")

    # Run make in directory with makefile to do simulation
    print("Running make in:", makefile_dir, "...", flush=True)
    bash_cmd = f"make"
    log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=makefile_dir)
    print(log_text, flush=True)
    sys.exit(0)

