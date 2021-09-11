import sys
import os

import SYN
import MODELSIM
import EDAPLAY

def DO_OPTIONAL_SIM(do_sim=False, is_edaplay=False, latency=0):
  if is_edaplay and do_sim:
    EDAPLAY.SETUP_EDAPLAY(latency)
  else:
    # Assume modelsim is default sim
    MODELSIM.DO_OPTIONAL_DEBUG(do_sim, latency)
  

def GET_SIM_FILES(latency=0):
  # Get all vhd files in syn output
  vhd_files = []
  for root, dirs, filenames in os.walk(SYN.SYN_OUTPUT_DIRECTORY):
    for f in filenames:
      if f.endswith(".vhd"):
        #print "f",f
        fullpath = os.path.join(root, f)
        abs_path = os.path.abspath(fullpath)
        #print "fullpath",fullpath
        #f
        if ( (root == SYN.SYN_OUTPUT_DIRECTORY + "/main") and
           f.startswith("main_") and f.endswith("CLK.vhd") ):
          clks = int(f.replace("main_","").replace("CLK.vhd",""))
          if clks==latency:
            print("Using top:",abs_path)
            vhd_files.append(abs_path)
        else:
          vhd_files.append(abs_path)
          
  return vhd_files
