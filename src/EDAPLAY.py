
import os
import shutil
import sys

import EDAPLAY
import MODELSIM
import SIM
import SYN


def SETUP_EDAPLAY(latency=0):
  # Copy each file into a single dir for each drag and drop
  out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/all_vhdl_files"
  if not os.path.exists(out_dir):
    os.makedirs(out_dir)
  vhd_files = SIM.GET_SIM_FILES(latency)
  for vhd_file in vhd_files:
    dest_file_name = os.path.basename(vhd_file)
    out_file = out_dir + "/" + dest_file_name
    shutil.copy(vhd_file, out_file)

  print("Login to EDAPlayground:")
  print(" Then go to:","https://www.edaplayground.com/x/vWLi")
  print(" Drag VHDL files from:", out_dir)
  
  sys.exit(0)
