import sys
import os
import shutil

import SIM
import SYN
import C_TO_LOGIC

def DO_SIM(latency):
  print("================== Doing CXXRTL Simulation ================================", flush=True)
  print("Compiling...")
  # Generate main.cpp
  main_cpp_text = '''
#include <iostream>
#include "top/top.cpp"

#define p_clk 		p_clk__33p33
#define p_led		p_blink__return__output
// TODO generated names / code structure
//#define p_counter	p_blink__0clk__a5a1_2e_counter__mux__blink__c__l17__c3__5f70_2e_return__output //name was guessed
   
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
       //uint32_t counter    = top.p_counter.get<uint32_t>();
       //cout << "cycle " << cycle << " - led: " << cur_led << ", counter: " << counter << endl;
       cout << "cycle " << cycle << " - led: " << cur_led << endl;
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
  sh_text = '''
ghdl -i --std=08 `cat vhdl_files.txt`
ghdl -m --std=08 top
yosys -m ghdl -p "ghdl --std=08 top; write_cxxrtl ./top/top.cpp"
clang++ -g -O3 -std=c++14 -I `yosys-config --datdir`/include main.cpp -o ./top/top
'''
  sh_path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "cxxrtl.sh"
  f=open(sh_path,"w")
  f.write(sh_text)
  f.close()
  
  # Run compile
  bash_cmd = f"bash {sh_path}"
  #print(bash_cmd, flush=True)  
  log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=SYN.SYN_OUTPUT_DIRECTORY)
  #print(log_text, flush=True)

  # Run the simulation
  print("Starting simulation...")
  bash_cmd = "./top/top"
  #print(bash_cmd, flush=True)
  log_text = C_TO_LOGIC.GET_SHELL_CMD_OUTPUT(bash_cmd, cwd=SYN.SYN_OUTPUT_DIRECTORY)
  print(log_text, flush=True)
  sys.exit(0)
