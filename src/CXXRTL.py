import sys
import os
import shutil

import SIM
import SYN
import C_TO_LOGIC
import OPEN_TOOLS

def DO_SIM(latency, parser_state):
  print("================== Doing CXXRTL Simulation ================================", flush=True)
  # Generate helpful include of cxxrtl names
  names_text = ""
  for func in parser_state.main_mhz:
    if func.endswith("_DEBUG_INPUT_MAIN") or func.endswith("_DEBUG_OUTPUT_MAIN"):
      debug_name = func.split("_DEBUG")[0]
      names_text += f'#define {debug_name} p_{func.replace("_","__")}__return__output\n'
  names_h_path = SYN.SYN_OUTPUT_DIRECTORY + "/pipelinec_cxxrtl.h"
  f=open(names_h_path,"w")
  f.write(names_text)
  f.close() 
  
  
  # Generate main.cpp
  main_cpp_text = '''
#include <iostream>
#include "top/top.cpp"
#include "pipelinec_cxxrtl.h"
// ^ #define my_debug_output p_my__debug__output__DEBUG__OUTPUT__MAIN__return_output

#define p_clk 		p_clk__33p33
#define p_led		p_blink__return__output
//#define p_counter	p_my__debug__output__DEBUG__OUTPUT__MAIN__return__output
   
using namespace std;
   
int main()
{
    cxxrtl_design::p_top top;
    top.step();

    for(int cycle=0; cycle<10; ++cycle)
    {
       top.debug_eval(); //if not called, some values are optimized (thus not calculated)

       top.p_clk.set<bool>(false); top.step();
       top.p_clk.set<bool>(true); top.step();
  
       bool cur_led        = top.p_led.get<bool>();
       uint32_t counter    = top.my_debug_output.get<uint32_t>();
       cout << "cycle " << cycle << " - led: " << cur_led << ", counter: " << counter << endl;
    }
    return 0;
}
'''
  main_cpp_path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "main.cpp"
  f=open(main_cpp_path,"w")
  f.write(main_cpp_text)
  f.close()
  
  # Generate+compile sim .cpp from output VHDL
  # Get all vhd files in syn output
  vhd_files = SIM.GET_SIM_FILES(latency=0)
  # Write a shell script to execute
  sh_text = f'''
{OPEN_TOOLS.GHDL_BIN_PATH}/ghdl -i --std=08 `cat vhdl_files.txt` && \
{OPEN_TOOLS.GHDL_BIN_PATH}/ghdl -m --std=08 top && \
{OPEN_TOOLS.YOSYS_BIN_PATH}/yosys -m ghdl -p "ghdl --std=08 top; write_cxxrtl ./top/top.cpp" && \
clang++ -g -O3 -std=c++14 -I `yosys-config --datdir`/include main.cpp -o ./top/top
'''
  sh_path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "cxxrtl.sh"
  f=open(sh_path,"w")
  f.write(sh_text)
  f.close()
  
  # Run compile
  print("Compiling...", flush=True)
  bash_cmd = f"bash {sh_path}"
  #print(bash_cmd, flush=True)  
  log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=SYN.SYN_OUTPUT_DIRECTORY)
  #print(log_text, flush=True)

  # Run the simulation
  print("Starting simulation...", flush=True)
  bash_cmd = "./top/top"
  #print(bash_cmd, flush=True)
  log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=SYN.SYN_OUTPUT_DIRECTORY)
  print(log_text, flush=True)
  sys.exit(0)
