from os import makedirs
from os.path import basename, exists
from shutil import copy

from src.SIM import GET_SIM_FILES
from src.SYN import SYN_OUTPUT_DIRECTORY


def SETUP_EDAPLAY(latency: int = 0) -> None:
    # Copy each file into a single dir for each drag and drop
    out_dir = SYN_OUTPUT_DIRECTORY + "/all_vhdl_files"
    if not exists(out_dir):
        makedirs(out_dir)
    vhd_files = GET_SIM_FILES(latency)
    for vhd_file in vhd_files:
        dest_file_name = basename(vhd_file)
        out_file = out_dir + "/" + dest_file_name
        copy(vhd_file, out_file)

    print("Login to EDAPlayground:")
    print(" Then go to:", "https://www.edaplayground.com/x/vWLi")
    print(" Drag VHDL files from:", out_dir)
