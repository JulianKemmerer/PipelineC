#!/usr/bin/env python
import sys
import os
import copy
import math
import math
import hashlib
from pycparser import c_ast

import C_TO_LOGIC
import SW_LIB
import RAW_VHDL
import SYN
import VIVADO


VHDL_FILE_EXT=".vhd"
VHDL_PKG_EXT=".pkg"+VHDL_FILE_EXT


def WIRE_TO_VHDL_TYPE_STR(wire_name, logic, parser_state=None):
  #print "logic.wire_to_c_type",logic.wire_to_c_type
  c_type_str = logic.wire_to_c_type[wire_name]
  return C_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str, parser_state)
  
def WIRE_TO_VHDL_NULL_STR(global_wire, logic, parser_state):
  c_type_str = logic.wire_to_c_type[global_wire]
  return C_TYPE_STR_TO_VHDL_NULL_STR(c_type_str, parser_state)

# Could be volatile global too
def STATE_REG_TO_VHDL_INIT_STR(wire, logic, parser_state):
  # Does this wire have an init?
  leaf = C_TO_LOGIC.LEAF_NAME(wire, True)
  c_type = logic.wire_to_c_type[wire]
  init = None
  if leaf in logic.state_regs:
    init = logic.state_regs[leaf].init
    
  if type(init) == c_ast.Constant:
    val = int(init.value)
    width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
    if WIRES_ARE_UINT_N([wire], logic) :
      return "to_unsigned(" + str(val) + "," + str(width) + ")"
    elif WIRES_ARE_INT_N([wire], logic):
      return "to_signed(" + str(val) + "," + str(width) + ")"
    else:
      print("What type of int blah?")
      sys.exit(-1)
      
  # If not use null
  elif init is None:
    return WIRE_TO_VHDL_NULL_STR(wire, logic, parser_state)
  else:
    print("Invalid initializer for state variable:", wire, "in func",logic.func_name)
    print(init)
    print("Only simple integers for now...")
    sys.exit(-1)
    
def CLK_EXT_STR(main_func, parser_state):
  text = ""
  mhz = parser_state.main_mhz[main_func]
  # Start with mhz
  text += str(mhz).replace(".","p")
  
  # Maybe add clock group
  group = parser_state.main_clk_group[main_func]
  if group:
    text += "_" + group
    
  return text
  
def WRITE_MULTIMAIN_TOP(parser_state, multimain_timing_params, is_final_top=False):
  text = ""
  text += "library ieee;" + "\n"
  text += "use ieee.std_logic_1164.all;" + "\n"
  text += "use ieee.numeric_std.all;" + "\n"
  # Include C defined structs
  text += "use work.c_structs_pkg.all;\n"
  # Include clock cross types
  text += "use work.clk_cross_t_pkg.all;\n"
  
  # Hash for multi main is just hash of main pipes
  hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    
  # Entity and file name
  entity_name = ""
  if not is_final_top:
    entity_name = "top" + hash_ext
  else:
    entity_name = "top" 
  filename = entity_name + VHDL_FILE_EXT
  
  text += '''
  entity ''' + entity_name + ''' is
port(
'''

  # All the clocks
  all_clks = set()
  for main_func in parser_state.main_mhz:
    clk_ext_str = CLK_EXT_STR(main_func, parser_state)
    clk_name = "clk_" + clk_ext_str
    all_clks.add(clk_name)
  for clk_name in sorted(list(all_clks)):
    text += clk_name + " : in std_logic;\n"

  text += '''
  -- IO for each main func
'''
  # IO
  for main_func in parser_state.main_mhz:
    main_func_logic = parser_state.FuncLogicLookupTable[main_func]
    # Inputs
    for input_port in main_func_logic.inputs:
      c_type = main_func_logic.wire_to_c_type[input_port]
      vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state)
      text += main_func + "_" + input_port + " : in " + vhdl_type + ";\n"
    # Outputs
    for output_port in main_func_logic.outputs:
      c_type = main_func_logic.wire_to_c_type[output_port]
      vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state)
      text += main_func + "_" + output_port + " : out " + vhdl_type + ";\n"
  
  # Remove last two chars
  text = text[0:len(text)-2]
    
  text += '''
  );
end ''' + entity_name + ''';
architecture arch of ''' + entity_name + ''' is
'''

  # Clock cross wires
  has_clk_cross = False
  for main_func in parser_state.main_mhz:
    main_func_logic = parser_state.FuncLogicLookupTable[main_func]
    if LOGIC_NEEDS_CLK_CROSS_TO_MODULE(main_func_logic,parser_state) or LOGIC_NEEDS_MODULE_TO_CLK_CROSS(main_func_logic,parser_state):
      has_clk_cross = True
      break
  if has_clk_cross:
    text += '''
-- Clock cross wires
signal clk_cross_to_module : clk_cross_to_module_t;
signal module_to_clk_cross : module_to_clk_cross_t;
'''
 
  # Dont touch IO
  if not is_final_top:
    text += "attribute syn_keep : boolean;\n"
    text += "attribute keep : string;\n"
    text += "attribute dont_touch : string;\n"    
    # IO
    for main_func in parser_state.main_mhz:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      # The inputs regs of the logic
      for input_name in main_func_logic.inputs:
        # Get type for input
        vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,main_func_logic,parser_state)
        text += "signal " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + "_input_reg : " + vhdl_type_str + " := " + WIRE_TO_VHDL_NULL_STR(input_name, main_func_logic, parser_state) + ";" + "\n"
        if not is_final_top:
          # Dont touch
          text += "attribute syn_keep of " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + '''_input_reg : signal is true;\n'''
          text += "attribute keep of " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + '''_input_reg : signal is "true";\n'''
          text += "attribute dont_touch of " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + '''_input_reg : signal is "true";\n'''
        
      text += "\n"
      
      # Output regs and signals
      for output_port in main_func_logic.outputs:
        output_vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(output_port,main_func_logic,parser_state)
        text += "signal " + main_func + "_" + WIRE_TO_VHDL_NAME(output_port, main_func_logic) + "_output : " + output_vhdl_type_str + ";" + "\n"
        text += "signal " + main_func + "_" + WIRE_TO_VHDL_NAME(output_port, main_func_logic) + "_output_reg : " + output_vhdl_type_str + ";" + "\n"
        if not is_final_top:
          # Dont touch
          text += "attribute syn_keep of " + main_func + "_" + WIRE_TO_VHDL_NAME(output_port, main_func_logic) + '''_output_reg : signal is true;\n'''
          text += "attribute keep of " + main_func + "_" + WIRE_TO_VHDL_NAME(output_port, main_func_logic) + '''_output_reg : signal is "true";\n'''
          text += "attribute dont_touch of " + main_func + "_" + WIRE_TO_VHDL_NAME(output_port, main_func_logic) + '''_output_reg : signal is "true";\n'''
          
    text += "\n"
  
  
  text += '''
begin
'''

  # IO regs
  if not is_final_top:
    text += "\n"  
    text += " " + "-- IO regs\n"
    
    for main_func in parser_state.main_mhz:
      clk_ext_str = CLK_EXT_STR(main_func, parser_state)
      text += " " + "process(clk_" + clk_ext_str + ") is" + "\n"
      text += " " + "begin" + "\n"
      text += " " + " " + "if rising_edge(clk_" + clk_ext_str + ") then" + "\n"
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      # Register inputs
      for input_name in main_func_logic.inputs:
        # Get type for input
        vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,main_func_logic,parser_state)
        text += " " + " " + " " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + "_input_reg <= " + main_func + "_" + WIRE_TO_VHDL_NAME(input_name, main_func_logic) + ";" + "\n"
        
      # Output regs 
      for out_wire in main_func_logic.outputs:
        text += " " + " " + " " + main_func + "_" + WIRE_TO_VHDL_NAME(out_wire, main_func_logic) + "_output_reg <= " + main_func + "_" + WIRE_TO_VHDL_NAME(out_wire, main_func_logic) + "_output;" + "\n"
      
      text += " " + " " + "end if;" + "\n"    
      text += " " + "end process;" + "\n"
    
  # Output wire connection
  if not is_final_top:
    for main_func in parser_state.main_mhz:
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      # Connect to top output port
      for out_wire in main_func_logic.outputs:
        text += " " + main_func + "_" + WIRE_TO_VHDL_NAME(out_wire, main_func_logic) + " <= " + main_func + "_" + WIRE_TO_VHDL_NAME(out_wire, main_func_logic) + "_output_reg;" + "\n"

  text += '''
-- Instantiate each main
'''
  # Main instances
  for main_func in parser_state.main_mhz:
    main_func_logic = parser_state.FuncLogicLookupTable[main_func]
    main_entity_name = GET_ENTITY_NAME(main_func, main_func_logic,multimain_timing_params.TimingParamsLookupTable, parser_state)
    clk_ext_str = CLK_EXT_STR(main_func, parser_state)
     
    # ENTITY
    main_timing_params = multimain_timing_params.TimingParamsLookupTable[main_func];
    main_needs_clk = LOGIC_NEEDS_CLOCK(main_func, main_func_logic, parser_state, multimain_timing_params.TimingParamsLookupTable)
    main_needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(main_func_logic, parser_state)
    main_needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(main_func_logic, parser_state)#, multimain_timing_params.TimingParamsLookupTable)
    main_needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(main_func_logic, parser_state)#, multimain_timing_params.TimingParamsLookupTable)
    
    new_inst_name = WIRE_TO_VHDL_NAME(main_func, main_func_logic)
    text += new_inst_name + " : entity work." + main_entity_name +" port map (\n"
    # Clock
    if main_needs_clk:
      text += "clk_" + clk_ext_str + ",\n"
    # Clock enable
    if main_needs_clk_en:
      text += "to_unsigned(1,1), -- main function always clock enabled\n"
    # Clock cross in
    if main_needs_clk_cross_to_module:
      text += "clk_cross_to_module." + main_func + ",\n"
    # Clock cross out 
    if main_needs_module_to_clk_cross:
      text += "module_to_clk_cross." + main_func + ",\n"
    # Inputs
    for in_port in main_func_logic.inputs:
      in_wire = main_func + "_" + in_port
      text += WIRE_TO_VHDL_NAME(in_wire, main_func_logic) 
      if not is_final_top: 
        text += "_input_reg"
      text += ",\n"
    # Outputs
    for out_port in main_func_logic.outputs:
      out_wire = main_func + "_" + out_port
      text += WIRE_TO_VHDL_NAME(out_wire, main_func_logic)
      if not is_final_top: 
        text += "_output"
      text += ",\n"
       
    # Remove last two chars
    text = text[0:len(text)-2]
    text += ");\n\n"


  # Clock crossings
  text += '''
  -- Instantiate each clock crossing
'''
  for var_name in parser_state.clk_cross_var_info:
    flow_control = parser_state.clk_cross_var_info[var_name].flow_control
    write_func, read_func = parser_state.clk_cross_var_info[var_name].write_read_funcs
    write_main, read_main = parser_state.clk_cross_var_info[var_name].write_read_main_funcs
    write_clk_ext_str = CLK_EXT_STR(write_main, parser_state)
    # Defaults for disconnected read side
    read_clk_ext_str = write_clk_ext_str
    if read_main is not None:
      read_clk_ext_str = CLK_EXT_STR(read_main, parser_state)
    
    # Find the full inst name for write and read func instances
    # (should only be one instance), and break into toks
    
    # Main func inst name is special case, 
    #and clock cross wire replace clock cross func inst name last tok
    # Write
    write_func_inst = None
    write_func_insts = parser_state.FuncToInstances[write_func]
    if len(write_func_insts) > 1:
      print("More than one use of", write_func)
      sys.exit(-1)
    write_func_inst = list(write_func_insts)[0]
    write_func_logic = parser_state.LogicInstLookupTable[write_func_inst]
    write_func_inst_toks = write_func_inst.split(C_TO_LOGIC.SUBMODULE_MARKER)
    # Start with main func then apply hier instances
    write_text = write_main
    for write_func_inst_tok in write_func_inst_toks[1:len(write_func_inst_toks)-1]:
      write_func_inst_str = WIRE_TO_VHDL_NAME(write_func_inst_tok)
      write_text += "." + write_func_inst_str
    write_text += "." + write_func
    
    # Read
    # Do not even write instance if done have read side func
    if read_func in parser_state.FuncToInstances:
      read_func_insts = parser_state.FuncToInstances[read_func]
      if len(read_func_insts) > 1:
        print("More than one use of", read_func)
        sys.exit(-1)
      read_func_inst = list(read_func_insts)[0]
      read_func_logic = parser_state.FuncLogicLookupTable[read_func]
      read_func_inst_toks = read_func_inst.split(C_TO_LOGIC.SUBMODULE_MARKER)
      # Start with main func then apply hier instances
      read_text = read_main
      for read_func_inst_tok in read_func_inst_toks[1:len(read_func_inst_toks)-1]:
        read_func_inst_str = WIRE_TO_VHDL_NAME(read_func_inst_tok)
        read_text += "." + read_func_inst_str
      read_text += "." + read_func
    
      text += var_name + ''' : entity work.clk_cross_''' + var_name + ''' port map
      (
  '''
      # Clk in input
      text += "clk_" + write_clk_ext_str + ",\n"
      # Clk in enable
      text += "module_to_clk_cross." + write_text + "_" + C_TO_LOGIC.CLOCK_ENABLE_NAME + ",\n"
      # Clk cross in data from pipeline output
      for input_port in write_func_logic.inputs:
        text += "module_to_clk_cross." + write_text + "_" + input_port + ",\n"
      for output_port in write_func_logic.outputs:
        text += "clk_cross_to_module." + write_text + "_" + output_port + ",\n"
      # Clk out input
      text += "clk_" + read_clk_ext_str + ",\n"
      # Clk out enable
      text += "module_to_clk_cross." + read_text + "_" + C_TO_LOGIC.CLOCK_ENABLE_NAME + ",\n"
      # Clk cross out data to pipeline input
      for input_port in read_func_logic.inputs:
        text += "module_to_clk_cross." + read_text + "_" + input_port + ",\n"
      for output_port in read_func_logic.outputs:
        text += "clk_cross_to_module." + read_text + "_" + output_port + ",\n"
        
      text = text.strip("\n").strip(",")
        
      text += '''
      );
  '''
  
  text += '''
end arch;
'''
  output_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + "top"
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)
  f = open(output_dir + "/" + filename,"w")
  f.write(text)
  f.close()
  

    
def GET_BLACKBOX_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  # Just like top with KEEP's and IO regs only though
  timing_params = TimingParamsLookupTable[inst_name]
  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  needs_clk = LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
  needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
  needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state)#, TimingParamsLookupTable)
  needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state)#, TimingParamsLookupTable)
  entity_name = GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state)
    
  rv = "-- BLACKBOX\n"
  
  # Dont touch IO
  rv += "attribute syn_keep : boolean;\n"
  rv += "attribute keep : string;\n"
  rv += "attribute dont_touch : string;\n"
  
  
  # The inputs regs of the logic
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    rv += "signal " + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg : " + vhdl_type_str + " := " + WIRE_TO_VHDL_NULL_STR(input_name, Logic, parser_state) + ";" + "\n"
    # Dont touch
    rv += "attribute syn_keep of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is true;\n'''
    rv += "attribute keep of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is "true";\n'''
    rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is "true";\n'''
    
    
  rv += "\n"
  
  # Output regs and signals
  for output_port in Logic.outputs:
    output_vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(output_port,Logic,parser_state)
    rv += "signal " + WIRE_TO_VHDL_NAME(output_port, Logic) + "_output_reg : " + output_vhdl_type_str + ";" + "\n"
    # Dont touch
    rv += "attribute syn_keep of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is true;\n'''
    rv += "attribute keep of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is "true";\n'''
    rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is "true";\n'''
    

  rv += "\n"
  
  rv += "begin" + "\n"
  
  # No instance 
  # IO regs only
  rv += " " + "-- IO regs\n"
  rv += " " + "process(clk) is" + "\n"
  rv += " " + "begin" + "\n"
  rv += " " + " " + "if rising_edge(clk) then" + "\n"
  
  # Register inputs
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    rv += " " + " " + " " + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg <= " + WIRE_TO_VHDL_NAME(input_name, Logic) + ";" + "\n"
    
  rv += " " + " " + "end if;" + "\n"    
  rv += " " + "end process;" + "\n"
  
  # Connect to top output port
  for out_wire in Logic.outputs:
    rv += " " + WIRE_TO_VHDL_NAME(out_wire, Logic) +" <= " + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output_reg;" + "\n"
  
  return rv


def WRITE_LOGIC_TOP(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable, is_final_top=False): 
  timing_params = TimingParamsLookupTable[inst_name]
  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  needs_clk = LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
  needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
  needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state)#, TimingParamsLookupTable)
  needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state)#, TimingParamsLookupTable)
  entity_name = GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state)
  
  if not is_final_top:
    filename = entity_name + "_top.vhd"
  else:
    filename = Logic.func_name + ".vhd"
    
    
  rv = ""
  rv += "library ieee;" + "\n"
  rv += "use ieee.std_logic_1164.all;" + "\n"
  rv += "use ieee.numeric_std.all;" + "\n"
  # Include C defined structs
  rv += "use work.c_structs_pkg.all;\n"
  if needs_clk_cross_to_module or needs_module_to_clk_cross:
    # Include clock cross types
    rv += "use work.clk_cross_t_pkg.all;\n"
  
  
  
  if not is_final_top:
    rv += "entity " + entity_name + "_top is" + "\n"
  else:
    rv += "entity " + Logic.func_name + " is" + "\n"
  
  rv += "port(" + "\n"
  rv += " clk : in std_logic;" + "\n"
  
  # Clock cross as needed
  if needs_clk_cross_to_module:
    rv += " clk_cross_to_module : in " + Logic.func_name + "_clk_cross_to_module_t;\n"
  if needs_module_to_clk_cross:
    rv += " module_to_clk_cross : out " + Logic.func_name + "_module_to_clk_cross_t;\n"
    
  # The inputs of the logic
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    rv += " " + WIRE_TO_VHDL_NAME(input_name, Logic) + " : in " + vhdl_type_str + ";" + "\n"
  
  # Output is type of return wire
  for output_port in Logic.outputs:
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(output_port,Logic,parser_state)
    rv += " " + WIRE_TO_VHDL_NAME(output_port, Logic) + " : out " + vhdl_type_str + ";" + "\n"

  rv = rv.strip("\n").strip(";")
  rv += ");" + "\n"
  
  if not is_final_top:
    rv += "end " + entity_name + "_top;" + "\n"
  else:
    rv += "end " + Logic.func_name + ";" + "\n"

  if not is_final_top:
    rv += "architecture arch of " + entity_name + "_top is" + "\n"
  else:
    rv += "architecture arch of " + Logic.func_name + " is" + "\n"
  
  # Dont touch IO
  if not is_final_top:
    rv += "attribute syn_keep : boolean;\n"
    rv += "attribute keep : string;\n"
    rv += "attribute dont_touch : string;\n"
    
    
  # Keep clock?
  #rv += '''
  #attribute dont_touch of clk : signal is "true";
  #attribute keep of clk : signal is "true";
  #attribute syn_keep of clk : signal is true;
  #'''
  
  # The inputs regs of the logic
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    rv += "signal " + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg : " + vhdl_type_str + " := " + WIRE_TO_VHDL_NULL_STR(input_name, Logic, parser_state) + ";" + "\n"
    if not is_final_top:
      # Dont touch
      rv += "attribute syn_keep of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is true;\n'''
      rv += "attribute keep of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is "true";\n'''
      rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(input_name, Logic) + '''_input_reg : signal is "true";\n'''
      
    
  rv += "\n"
  
  # Output regs and signals
  for output_port in Logic.outputs:
    output_vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(output_port,Logic,parser_state)
    rv += "signal " + WIRE_TO_VHDL_NAME(output_port, Logic) + "_output : " + output_vhdl_type_str + ";" + "\n"
    rv += "signal " + WIRE_TO_VHDL_NAME(output_port, Logic) + "_output_reg : " + output_vhdl_type_str + ";" + "\n"
    if not is_final_top:
      # Dont touch
      rv += "attribute syn_keep of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is true;\n'''
      rv += "attribute keep of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is "true";\n'''
      rv += "attribute dont_touch of " + WIRE_TO_VHDL_NAME(output_port, Logic) + '''_output_reg : signal is "true";\n'''
      

  rv += "\n"
  
  # Clock cross regs and signals
  if needs_clk_cross_to_module:
    rv += "signal clk_cross_to_module_input_reg : " + Logic.func_name + "_clk_cross_to_module_t;" + "\n"
  if needs_module_to_clk_cross:
    rv += "signal module_to_clk_cross_output : " + Logic.func_name + "_module_to_clk_cross_t;" + "\n"
    rv += "signal module_to_clk_cross_output_reg : " + Logic.func_name + "_module_to_clk_cross_t;" + "\n"
  
  # Write vhdl func if needed
  if Logic.is_vhdl_func:
    rv += GET_VHDL_FUNC_DECL(inst_name, Logic, parser_state, timing_params)
  
  rv += "begin" + "\n"
  
  # Instantiate main
  # As entity or as function?
  if Logic.is_vhdl_func:
    # FUNCTION INSTANCE
    for output_port in Logic.outputs:
      rv += WIRE_TO_VHDL_NAME(output_port, Logic) + "_output <= " + Logic.func_name + "(\n"
    # Inputs from regs
    for in_port in Logic.inputs:
      rv += WIRE_TO_VHDL_NAME(in_port, Logic) + "_input_reg"  + ",\n"
    # Remove last two chars
    rv = rv[0:len(rv)-len(",\n")]
    rv += ");\n"
  else:
    # ENTITY
    rv += "-- Instantiate entity\n"
    rv += entity_name +" : entity work." + entity_name + " port map (\n"
    if needs_clk:
      rv += "clk,\n"
    if needs_clk_en:
      rv += "to_unsigned(1,1),-- Top level funcs always synthesized as clock enabled\n"
    # Clock cross as needed
    if needs_clk_cross_to_module:
      rv += " clk_cross_to_module_input_reg,\n"
    if needs_module_to_clk_cross:
      rv += " module_to_clk_cross_output,\n"
    # Inputs from regs
    for in_port in Logic.inputs:
      rv += WIRE_TO_VHDL_NAME(in_port, Logic) + "_input_reg"  + ",\n"
    # Outputs to signal
    for out_port in Logic.outputs:
      rv += WIRE_TO_VHDL_NAME(out_port, Logic) + "_output" + ",\n"
    # Remove last two chars
    rv = rv[0:len(rv)-len(",\n")]
    rv += ");\n"
  
  rv += "\n"  
  rv += " " + "-- IO regs\n"
  rv += " " + "process(clk) is" + "\n"
  rv += " " + "begin" + "\n"
  rv += " " + " " + "if rising_edge(clk) then" + "\n"
  
  # Register inputs
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    rv += " " + " " + " " + WIRE_TO_VHDL_NAME(input_name, Logic) + "_input_reg <= " + WIRE_TO_VHDL_NAME(input_name, Logic) + ";" + "\n"
    
  # Output regs 
  for out_wire in Logic.outputs:
    rv += " " + " " + " " + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output_reg <= " + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output;" + "\n"
  
  # Clock cross registers
  if needs_clk_cross_to_module:
    rv += " " + " " + " " + "clk_cross_to_module_input_reg <= clk_cross_to_module;" + "\n"
  if needs_module_to_clk_cross:
    rv += " " + " " + " " + "module_to_clk_cross_output_reg <= module_to_clk_cross_output;" + "\n"
  
  rv += " " + " " + "end if;" + "\n"    
  rv += " " + "end process;" + "\n"
  
  # Connect to top output port
  for out_wire in Logic.outputs:
    rv += " " + WIRE_TO_VHDL_NAME(out_wire, Logic) +" <= " + WIRE_TO_VHDL_NAME(out_wire, Logic) + "_output_reg;" + "\n"
    
  # Connect to top clk cross outputs
  if needs_module_to_clk_cross:
    rv += " " + "module_to_clk_cross <= module_to_clk_cross_output_reg;" + "\n" 
    
  rv += "end arch;" + "\n"
  
  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
  
  #print "NOT WRIT TOP"
  f = open(output_directory+ "/" + filename,"w")
  f.write(rv)
  f.close()
  
def GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str):
  if not (C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str)):
    print("Cant GET_WIDTH_FROM_C_TYPE_STR since isnt int/uint N", c_type_str)
    print(0/0)
    sys.exit(-1) 
    
  # Chars?
  if c_type_str == 'char':
    return 8
    
  return int(c_type_str.replace("uint","").replace("int","").replace("_t",""))
  
def GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str, allow_fail=False):
  if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str):
    return GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type_str)
  elif c_type_str == "float":
    return 32
  elif c_type_str in parser_state.enum_to_ids_dict:
    # Enum type, width is log2(elements)
    num_ids = len(parser_state.enum_to_ids_dict[c_type_str])
    bits = int(math.ceil(math.log(num_ids,2)))
    return bits 
  else:
    if not allow_fail:
      print("Cant GET_WIDTH_FROM_C_TYPE_STR for ", c_type_str)
      print(0/0)
      sys.exit(-1)
    return None
  
  
def C_TYPE_IS_UINT_N(type_str):
  try:
    width = int(type_str.replace("uint","").replace("_t",""))
    return True
  except:
    
    # Chars?
    if type_str == 'char':
      return True
    
    return False
  
def C_TYPE_IS_INT_N(type_str):
  try:
    width = int(type_str.replace("int","").replace("_t",""))
    return True
  except:
    return False
    
# Includes intN and uintN
def C_TYPES_ARE_INTEGERS(c_types):
  for c_type in c_types:
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
      elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      c_type = elem_type
      #print "c_type",c_type
    
    if not( C_TYPE_IS_INT_N(c_type) or C_TYPE_IS_UINT_N(c_type) ):
      return False
  return True

# Includes intN and uintN
def C_TYPES_ARE_TYPE(c_types, the_type):
  for c_type in c_types:
    if c_type != the_type:
      return False
  return True
    
def C_BUILT_IN_FUNC_IS_RAW_HDL(logic_func_name, input_c_types):
  # IS RAW VHDL
  if  (
      logic_func_name == C_TO_LOGIC.VHDL_FUNC_NAME or
      logic_func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX + "_") or
      logic_func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SL_NAME + "_") or
      logic_func_name.startswith(C_TO_LOGIC.CONST_PREFIX+C_TO_LOGIC.BIN_OP_SR_NAME + "_") or
    ( logic_func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.UNARY_OP_NOT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
      ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_EQ_NAME)  ) or #and C_TYPES_ARE_INTEGERS(input_c_types)
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_NEQ_NAME)  ) or #and C_TYPES_ARE_INTEGERS(input_c_types)
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_AND_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_OR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_XOR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LT_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or
    ( logic_func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME) )
    ):# or    
    return True
  
  # IS NOT RAW VHDL
  elif (  logic_func_name.startswith(C_TO_LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX + "_")                                                                    or  
      logic_func_name.startswith(C_TO_LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_")                                                                or
      logic_func_name.startswith(C_TO_LOGIC.CAST_FUNC_NAME_PREFIX + "_")                                                                          or
      logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_DIV_NAME)                                          or
      logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MULT_NAME)                                         or
      logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MOD_NAME)                                          or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SL_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_SR_NAME) and C_TYPES_ARE_INTEGERS(input_c_types) ) or # ASSUME FOR NOW
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GT_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_GTE_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LT_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_LTE_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_PLUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float")) or
    ( logic_func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX + "_" + C_TO_LOGIC.BIN_OP_MINUS_NAME) and C_TYPES_ARE_TYPE(input_c_types,"float"))
    ):
    return False
  else:
    print("Is logic_func_name",logic_func_name,"with input types",input_c_types,"raw VHDL or not?")
    sys.exit(-1)
  
  
def GET_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
  LogicInstLookupTable = parser_state.LogicInstLookupTable
  
  timing_params = TimingParamsLookupTable[inst_name]
  package_file_text = ""
  # Raw hdl logic is static in the stages code here but coded as generic
  if len(logic.submodule_instances) <= 0 and logic.func_name not in parser_state.main_mhz:
    package_file_text = RAW_VHDL.GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, timing_params)
  else:
    package_file_text = GET_C_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable)
  
  return package_file_text
  
  
def WRITE_CLK_CROSS_ENTITIES(parser_state, multimain_timing_params):
  text = ""
  

  for var_name in parser_state.clk_cross_var_info:
    flow_control = parser_state.clk_cross_var_info[var_name].flow_control
    write_size,read_size = parser_state.clk_cross_var_info[var_name].write_read_sizes
 
    # TODO OTHER SIZES
    if flow_control:
      if SYN.SYN_TOOL is not VIVADO:
        print("Async fifos are only implemented for Xilinx parts, TODO!", var_name)
        sys.exit(-1)
      if write_size != read_size:
        print("Only equal read and write sizes for async fifos for now, TODO!", var_name)
        sys.exit(-1) 
 
    if not flow_control:
      if write_size >= read_size:
        clk_ratio = write_size / read_size
      else:
        clk_ratio = read_size / write_size
      if int(clk_ratio) != clk_ratio:
        print("TODO: non int ratio clks")
        sys.exit(-1)
      clk_ratio = int(clk_ratio)
      CLK_RATIO = str(clk_ratio)
      CLK_RATIO_MINUS1 = str(clk_ratio - 1)
      
      if var_name in parser_state.global_state_regs:
        c_type = parser_state.global_state_regs[var_name].type_name    
      data_vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state) 
      
      in_t = c_type + "_array_" + str(write_size) + "_t"
      in_vhdl_t = C_TYPE_STR_TO_VHDL_TYPE_STR(in_t, parser_state)
      out_t = c_type + "_array_" + str(read_size) + "_t"
      out_vhdl_t = C_TYPE_STR_TO_VHDL_TYPE_STR(out_t, parser_state)
    else:
      # With flow control
      array_type = parser_state.global_state_regs[var_name].type_name
      c_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(array_type)
      if len(dims) > 1:
        print("More than 1 dim for async flow control!?",var_name)
        sys.exit(-1)
      depth = dims[0]
      if depth < 16:
        depth = 16
        print("WARNING:",var_name,"async fifo depth increased to minimum allowed =", depth)
      in_t = c_type + "[" + str(write_size) + "]"
      in_vhdl_t = C_TYPE_STR_TO_VHDL_TYPE_STR(in_t, parser_state)
      out_t = c_type + "[" + str(read_size) + "]"
      out_vhdl_t = C_TYPE_STR_TO_VHDL_TYPE_STR(out_t, parser_state)
    
    text += '''
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
use work.c_structs_pkg.all; -- User types
'''
    
    if flow_control:
      text += '''
library xpm;
use xpm.vcomponents.all;
'''
    
    text += '''
    entity clk_cross_''' + var_name + ''' is
    port(
      in_clk : in std_logic;
      in_clk_en : in unsigned(0 downto 0);
'''
    if flow_control:
      text += '''
      wr_data : in ''' + in_vhdl_t + ''';
      wr_en : in unsigned(0 downto 0);
      wr_out: out ''' + var_name + '''_write_t;
'''
    else:
      text += '''
      i : in ''' + in_vhdl_t + ''';
'''
    text += '''
      out_clk : in std_logic;
      out_clk_en : in unsigned(0 downto 0);
'''
    if flow_control:
      text += '''
      rd_enable: in unsigned(0 downto 0);
      rd_out : out ''' + var_name + '''_read_t
'''
    else:
      text += '''
      o : out ''' + out_vhdl_t + '''
'''
    text += '''
    );
    end clk_cross_''' + var_name + ''';
    architecture arch of clk_cross_''' + var_name + ''' is
    '''
    
    if not flow_control:
      text += '''
      constant CLK_RATIO : integer := ''' + CLK_RATIO + ''';
      constant CLK_RATIO_MINUS1 : integer := ''' + CLK_RATIO_MINUS1 + ''';
      '''
      
    if flow_control:
      text += '''
      signal full : std_logic;
      signal wr_rst_busy : std_logic;
      signal rd_rst_busy : std_logic;
      signal ready : std_logic;
      signal valid : std_logic;
      signal fifo_rd_enable : std_logic;
      signal fifo_wr_en : std_logic;
      signal din_slv : std_logic_vector((''' + C_TYPE_STR_TO_VHDL_SLV_LEN_STR(in_t,parser_state) + ''')-1 downto 0);
      signal dout_slv : std_logic_vector((''' + C_TYPE_STR_TO_VHDL_SLV_LEN_STR(out_t,parser_state) + ''')-1 downto 0);
      '''      
    # Need some regs
    elif write_size != read_size:
      # A counter
      text += '''
      signal fast_clk_counter_r : integer range 0 to CLK_RATIO_MINUS1 := CLK_RATIO_MINUS1;'''
      # Output register in fast domain
      text += '''
      signal o_fast_r : ''' + out_vhdl_t + ''';'''
      # A slow toggling N regs
      # Write > read means slow->fast
      if write_size > read_size: 
        text += '''
        signal slow_array_r : ''' + in_vhdl_t + ''';'''
        # Input register in slow domain
        text += '''
        signal i_slow_r : ''' + in_vhdl_t + ''';
        signal i_slow_valid_r : std_logic := '0';
        '''
      elif write_size < read_size:
        # Write < read means fast->slow 
        text += '''
        signal slow_array_r : ''' + out_vhdl_t + ''';'''
        # Output register in slow domain
        text += '''
        signal o_slow_r : ''' + out_vhdl_t + ''';
        '''
        
      # N valid bits
      text += '''
      signal slow_array_valids_r : std_logic_vector(0 to CLK_RATIO_MINUS1) := (others => '0');
      '''
    else:
      # Same clock domain only need reg for clock enable
      text += '''
      signal clock_disabled_value_r : ''' + in_vhdl_t + ''' := ''' + C_TYPE_STR_TO_VHDL_NULL_STR(in_t, parser_state) + ''';'''
    
    text+='''
    begin
    '''
    
    to_slv_toks = VHDL_TYPE_TO_SLV_TOKS(in_vhdl_t, parser_state)
    from_slv_toks = VHDL_TYPE_FROM_SLV_TOKS(out_vhdl_t, parser_state)

    # Flow control is async fifo
    if flow_control:
      text += '''
      
fifo_wr_en <= wr_en(0) and in_clk_en(0) and not wr_rst_busy;
wr_out.ready(0) <= not full and not wr_rst_busy;
din_slv <= ''' + to_slv_toks[0] + '''wr_data''' + to_slv_toks[1] + ''';

fifo_rd_enable <= rd_enable(0) and out_clk_en(0) and not rd_rst_busy;
rd_out.valid(0) <= valid and not rd_rst_busy;
rd_out.data <= ''' + from_slv_toks[0] + '''dout_slv''' + from_slv_toks[1] + ''';
      
-- xpm_fifo_async: Asynchronous FIFO
-- Xilinx Parameterized Macro, version 2019.1
xpm_fifo_async_inst : xpm_fifo_async
generic map (
  CDC_SYNC_STAGES => 2, -- DECIMAL
  DOUT_RESET_VALUE => "0", -- String
  ECC_MODE => "no_ecc", -- String
  FIFO_MEMORY_TYPE => "auto", -- String
  FIFO_READ_LATENCY => 0, -- DECIMAL
  FIFO_WRITE_DEPTH => ''' + str(depth) + ''', -- DECIMAL
  FULL_RESET_VALUE => 0, -- DECIMAL
  PROG_EMPTY_THRESH => 10, -- DECIMAL
  PROG_FULL_THRESH => 10, -- DECIMAL
  RD_DATA_COUNT_WIDTH => 1, -- DECIMAL
  READ_DATA_WIDTH => ''' + C_TYPE_STR_TO_VHDL_SLV_LEN_STR(out_t, parser_state) + ''', -- DECIMAL , READ_DATA_WIDTH should be equal to
                   -- WRITE_DATA_WIDTH if FIFO_MEMORY_TYPE is set to "auto"
  READ_MODE => "fwft", -- String
  RELATED_CLOCKS => 0, -- DECIMAL
  SIM_ASSERT_CHK => 0, -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
  USE_ADV_FEATURES => "1000", -- String
                      -- Setting USE_ADV_FEATURES[12] to 1 enables data_valid flag;
                      -- 1<<12 = 4096 = 0x1000
  WAKEUP_TIME => 0, -- DECIMAL
  WRITE_DATA_WIDTH => ''' + C_TYPE_STR_TO_VHDL_SLV_LEN_STR(in_t,parser_state) + ''', -- DECIMAL
  WR_DATA_COUNT_WIDTH => 1 -- DECIMAL
)
port map (
  --almost_empty => almost_empty, -- 1-bit output: Almost Empty : When asserted, this signal indicates that
  -- only one more read can be performed before the FIFO goes to empty.
  --almost_full => almost_full, -- 1-bit output: Almost Full: When asserted, this signal indicates that
  -- only one more write can be performed before the FIFO is full.
  
  data_valid => valid, -- 1-bit output: Read Data Valid: When asserted, this signal indicates
  -- that valid data is available on the output bus (dout).
  
  --dbiterr => dbiterr, -- 1-bit output: Double Bit Error: Indicates that the ECC decoder
  -- detected a double-bit error and data in the FIFO core is corrupted.
  
  dout => dout_slv, -- READ_DATA_WIDTH-bit output: Read Data: The output data bus is driven
  -- when reading the FIFO
  
  --empty => empty, -- 1-bit output: Empty Flag: When asserted, this signal indicates that
  -- the FIFO is empty. Read requests are ignored when the FIFO is empty,
  -- initiating a read while empty is not destructive to the FIFO.
  full => full, -- 1-bit output: Full Flag: When asserted, this signal indicates that the
  -- FIFO is full. Write requests are ignored when the FIFO is full,
  -- initiating a write when the FIFO is full is not destructive to the
  -- contents of the FIFO.
  --overflow => overflow, -- 1-bit output: Overflow: This signal indicates that a write request
  -- (wren) during the prior clock cycle was rejected, because the FIFO is
  -- full. Overflowing the FIFO is not destructive to the contents of the
  -- FIFO.
  --prog_empty => prog_empty, -- 1-bit output: Programmable Empty: This signal is asserted when the
  -- number of words in the FIFO is less than or equal to the programmable
  -- empty threshold value. It is de-asserted when the number of words in
  -- the FIFO exceeds the programmable empty threshold value.
  --prog_full => prog_full, -- 1-bit output: Programmable Full: This signal is asserted when the
  -- number of words in the FIFO is greater than or equal to the
  -- programmable full threshold value. It is de-asserted when the number
  -- of words in the FIFO is less than the programmable full threshold
  -- value.
  --rd_data_count => rd_data_count, -- RD_DATA_COUNT_WIDTH-bit output: Read Data Count: This bus indicates
  -- the number of words read from the FIFO.
  
  rd_rst_busy => rd_rst_busy, -- 1-bit output: Read Reset Busy: Active-High indicator that the FIFO
  -- read domain is currently in a reset state.
  
  --sbiterr => sbiterr, -- 1-bit output: Single Bit Error: Indicates that the ECC decoder
  -- detected and fixed a single-bit error.
  --underflow => underflow, -- 1-bit output: Underflow: Indicates that the read request (rd_en)
  -- during the previous clock cycle was rejected because the FIFO is
  -- empty. Under flowing the FIFO is not destructive to the FIFO.
  --wr_ack => wr_ack, -- 1-bit output: Write Acknowledge: This signal indicates that a write
  -- request (wr_en) during the prior clock cycle is succeeded.
  --wr_data_count => wr_data_count, -- WR_DATA_COUNT_WIDTH-bit output: Write Data Count: This bus indicates
  -- the number of words written into the FIFO.
  
  wr_rst_busy => wr_rst_busy, -- 1-bit output: Write Reset Busy: Active-High indicator that the FIFO
  -- write domain is currently in a reset state.
  
  din => din_slv, -- WRITE_DATA_WIDTH-bit input: Write Data: The input data bus used when
  -- writing the FIFO.
  
  injectdbiterr => '0', -- 1-bit input: Double Bit Error Injection: Injects a double bit error if
  -- the ECC feature is used on block RAMs or UltraRAM macros.
  injectsbiterr => '0', -- 1-bit input: Single Bit Error Injection: Injects a single bit error if
  -- the ECC feature is used on block RAMs or UltraRAM macros.
  
  rd_clk => out_clk, -- 1-bit input: Read clock: Used for read operation. rd_clk must be a
  -- free running clock.
  
  rd_en => fifo_rd_enable, -- 1-bit input: Read Enable: If the FIFO is not empty, asserting this
  -- signal causes data (on dout) to be read from the FIFO. Must be held
  -- active-low when rd_rst_busy is active high.
  
  rst => '0', -- 1-bit input: Reset: Must be synchronous to wr_clk. The clock(s) can be
  -- unstable at the time of applying reset, but reset must be released
  -- only after the clock(s) is/are stable.
  
  sleep => '0', -- 1-bit input: Dynamic power saving: If sleep is High, the memory/fifo
  -- block is in power saving mode.
  
  wr_clk => in_clk, -- 1-bit input: Write clock: Used for write operation. wr_clk must be a
  -- free running clock.
  
  wr_en => fifo_wr_en -- 1-bit input: Write Enable: If the FIFO is not full, asserting this
  -- signal causes data (on din) to be written to the FIFO. Must be held     
  -- active-low when rst or wr_rst_busy is active high.
  
);
-- End of xpm_fifo_async_inst instantiation     
'''


    # BELOW CROSSINGS CANNOT USE OUTPUT CLOCK ENABLES
    # - DO NOT HAVE FIFO BUFFERS
    #  - ARE NOT FLOW CONTROLABLE 
    # (input clock enables are just extra enable inputs + fine)

    # Write > read means slow->fast
    elif write_size > read_size:
      text +='''
      
      -- input reg in slow domain
      process(in_clk) is
      begin
      if rising_edge(in_clk) then
        i_slow_r <= i;
        i_slow_valid_r <= in_clk_en(0);
      end if;
      end process;
      
      -- slow->fast, need fast domain logic
      process(out_clk) is
      begin
      if rising_edge(out_clk) then
  
        -- Always shifting out serial fast data
        for i in 0 to ''' + str(clk_ratio-2) + ''' loop 
          slow_array_r.data(i) <= slow_array_r.data(i+1);
          slow_array_valids_r(i) <= slow_array_valids_r(i+1);
        end loop;
        -- Output data null by default
        o_fast_r.data(0) <= ''' + C_TYPE_STR_TO_VHDL_NULL_STR(c_type, parser_state) + ''';
        -- If valid data then output from front of array
        if slow_array_valids_r(0) = '1' then
          o_fast_r.data(0) <= slow_array_r.data(0);
        end if;        
        
        -- Counter roll over is slow clk enable logic in fast domain
        -- Incoming slow data registered 
        if fast_clk_counter_r = CLK_RATIO_MINUS1 then
          fast_clk_counter_r <= 0;
          slow_array_valids_r <= (others => i_slow_valid_r);
          slow_array_r <= i_slow_r;
        else
          -- Counter
          fast_clk_counter_r <= fast_clk_counter_r + 1;
        end if;
      
      end if;
      end process;
      o <= o_fast_r;
      '''
    elif write_size < read_size:
      # Write < read means fast->slow
      text +='''
      
      -- fast->slow ,need fast domain logic
      process(in_clk) is
      begin
      if rising_edge(in_clk) then
      
        -- Always shifting in serial fast data
        for i in 0 to ''' + str(clk_ratio-2) + ''' loop 
          slow_array_r.data(i) <= slow_array_r.data(i+1);
          slow_array_valids_r(i) <= slow_array_valids_r(i+1);
        end loop;
        slow_array_r.data(CLK_RATIO_MINUS1) <= i.data(0);
        slow_array_valids_r(CLK_RATIO_MINUS1) <= in_clk_en(0);        
        
        -- Counter roll over is slow clk enable logic in fast domain
        if fast_clk_counter_r = CLK_RATIO_MINUS1 then
          fast_clk_counter_r <= 0;
        
          -- Output datas null by default
          for i in 0 to CLK_RATIO_MINUS1 loop
            o_fast_r.data(i) <= ''' + C_TYPE_STR_TO_VHDL_NULL_STR(c_type, parser_state) + ''';
            -- If valid data then output data
            if slow_array_valids_r(i) = '1' then
              o_fast_r.data(i) <= slow_array_r.data(i);
            end if;
          end loop;
        else
          -- Counter
          fast_clk_counter_r <= fast_clk_counter_r + 1;
        end if;
            
      end if;
      end process;
      
      -- output reg on slow output clock
      process(out_clk) is
      begin
      if rising_edge(out_clk) then
        o_slow_r <= o_fast_r;
      end if;
      end process;
      o <= o_slow_r;
      '''    
      
    elif write_size == read_size:
      text += '''   
      -- Same clock with clock disabled past value holding reg
      process(in_clk, in_clk_en) is
      begin
        if rising_edge(in_clk) and in_clk_en(0) = '1' then
          clock_disabled_value_r <= i;
        end if;
      end process;
      
      -- Mux current in value or past value
      process(i,in_clk_en,clock_disabled_value_r) is
      begin
        if in_clk_en(0) = '1' then
          o <= i;
        else
          o <= clock_disabled_value_r;
        end if;
      end process;
      '''
    
    text += '''    
    end arch;
    '''
    
  if not os.path.exists(SYN.SYN_OUTPUT_DIRECTORY):
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY) 
  path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "clk_cross_entities" + VHDL_FILE_EXT
  
  f=open(path,"w")
  f.write(text)
  f.close()    
    


def WRITE_CLK_CROSS_VHDL_PACKAGE(parser_state):
  text = ""
  text += '''
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
use work.c_structs_pkg.all; -- User types
-- Clock crossings
package clk_cross_t_pkg is
'''
  
  # Type for each func, with hierarchy
  # could do recursive but ...dumb
  read_funcs_written = set()
  write_funcs_written = set()
  # Collect funcs that dont need clk cross first
  # And funcs that are themselves the clock crossing (dont need port)
  for func_name in parser_state.FuncLogicLookupTable:
    func_logic = parser_state.FuncLogicLookupTable[func_name]   
    if not LOGIC_NEEDS_CLK_CROSS_TO_MODULE(func_logic, parser_state):
      read_funcs_written.add(func_name)
    if not LOGIC_NEEDS_MODULE_TO_CLK_CROSS(func_logic, parser_state):
      write_funcs_written.add(func_name)
    if SW_LIB.IS_CLOCK_CROSSING(func_logic):
      if "_READ" in func_name: 
        read_funcs_written.add(func_name)
      if "_WRITE" in func_name:
        write_funcs_written.add(func_name) 
  
  # Dumb loop
  still_writing = True
  while still_writing:
    still_writing = False
    
    # READ
    for func_name in parser_state.FuncLogicLookupTable:
      func_logic = parser_state.FuncLogicLookupTable[func_name] 
      # Read?
      if not LOGIC_NEEDS_CLK_CROSS_TO_MODULE(func_logic, parser_state):
        continue 
      # Done already?
      if func_name in read_funcs_written:
        continue
      # All submodule funcs written?
      all_subs_written = True
      for sub_inst in func_logic.submodule_instances:
        sub_func_name = func_logic.submodule_instances[sub_inst]
        if sub_func_name not in read_funcs_written:
          all_subs_written = False
          break
      if not all_subs_written:
        continue
      #
      # clk_cross _t for this func 
      text += '''
  type ''' + func_name + '''_clk_cross_to_module_t is record
    '''   
      # READ+WRITE OUTPUTS
      # Which submodules are clock crossings, get var name from sub
      for sub_inst in func_logic.submodule_instances:
        sub_func = func_logic.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func]
        if SW_LIB.IS_CLOCK_CROSSING(sub_logic):
          for output_port in sub_logic.outputs:
            # submodule instance name == Func name for clk cross since single instance?
            #output_port_wire = sub_func + C_TO_LOGIC.SUBMODULE_MARKER + output_port
            c_type = sub_logic.wire_to_c_type[output_port]
            text += "     " + sub_func + "_" + output_port + " : " + C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state) + ";\n"
            
      # Then include types for submodules (not clock crossing submodules)
      for sub_inst in func_logic.submodule_instances:
        sub_func = func_logic.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func]
        if SW_LIB.IS_CLOCK_CROSSING(sub_logic):
          continue        
        if LOGIC_NEEDS_CLK_CROSS_TO_MODULE(sub_logic, parser_state):
          text += '''
    ''' + WIRE_TO_VHDL_NAME(sub_inst) + " : " + sub_func + "_clk_cross_to_module_t;"
  
      text += '''
  end record;
'''
      still_writing = True
      read_funcs_written.add(func_name)
  
  
    # WRITE
    for func_name in parser_state.FuncLogicLookupTable:
      func_logic = parser_state.FuncLogicLookupTable[func_name] 
      # Write?
      if not LOGIC_NEEDS_MODULE_TO_CLK_CROSS(func_logic, parser_state):
        continue 
      # Done already?
      if func_name in write_funcs_written:
        continue
      # All submodule funcs written?
      all_subs_written = True
      for sub_inst in func_logic.submodule_instances:
        sub_func_name = func_logic.submodule_instances[sub_inst]
        if sub_func_name not in write_funcs_written:
          all_subs_written = False
          break
      if not all_subs_written:
        continue
      #
      # clk_cross _t for this func 
      text += '''
  type ''' + func_name + '''_module_to_clk_cross_t is record
    '''  
      # READ+WRITE CLOCK EN + INPUTS
      # Which submodules are clock crossings, get var name from sub
      for sub_inst in func_logic.submodule_instances:
        sub_func = func_logic.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func]
        if SW_LIB.IS_CLOCK_CROSSING(sub_logic):
          var_name = C_TO_LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(sub_logic.func_name) 
          clk_cross_info = parser_state.clk_cross_var_info[var_name]
          c_type = sub_logic.wire_to_c_type[C_TO_LOGIC.CLOCK_ENABLE_NAME]
          text += "     " + sub_func + "_" + C_TO_LOGIC.CLOCK_ENABLE_NAME + " : " + C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state) + ";\n"   
          for input_port in sub_logic.inputs:
            # submodule instance name == Func name for clk cross since single instance?
            #input_port_wire = sub_func + C_TO_LOGIC.SUBMODULE_MARKER + input_port
            c_type = sub_logic.wire_to_c_type[input_port]
            text += "     " + sub_func + "_" + input_port + " : " + C_TYPE_STR_TO_VHDL_TYPE_STR(c_type, parser_state) + ";\n"   
      # Then include types for submodules (not clock crossing submodules)
      for sub_inst in func_logic.submodule_instances:
        sub_func = func_logic.submodule_instances[sub_inst]
        sub_logic = parser_state.FuncLogicLookupTable[sub_func]
        if SW_LIB.IS_CLOCK_CROSSING(sub_logic):
          continue  
        if LOGIC_NEEDS_MODULE_TO_CLK_CROSS(sub_logic, parser_state):
          text += '''
    ''' + WIRE_TO_VHDL_NAME(sub_inst) + " : " + sub_func + "_module_to_clk_cross_t;"
  
      text += '''
  end record;
  
'''
      still_writing = True
      write_funcs_written.add(func_name)
  
  
  
  # Done writing hierarchy, write multimain top types
  read_text = ""
  for main_func in parser_state.main_mhz:
    main_logic = parser_state.FuncLogicLookupTable[main_func]
    if LOGIC_NEEDS_CLK_CROSS_TO_MODULE(main_logic, parser_state):
      read_text += '''
    ''' + WIRE_TO_VHDL_NAME(main_func) + " : " + main_func + "_clk_cross_to_module_t;"
  if read_text != "":
    text += '''type clk_cross_to_module_t is record'''
    text += read_text
    text += '''
  end record;
  
  '''
  
  write_text = ""
  for main_func in parser_state.main_mhz:
    main_logic = parser_state.FuncLogicLookupTable[main_func]
    if LOGIC_NEEDS_MODULE_TO_CLK_CROSS(main_logic, parser_state):
      write_text += '''
    ''' + WIRE_TO_VHDL_NAME(main_func) + " : " + main_func + "_module_to_clk_cross_t;"
  if write_text != "":
    text += '''type module_to_clk_cross_t is record'''
    text += write_text
    text += '''
  end record;
  
  '''
  
  text += '''
end clk_cross_t_pkg;
'''
  
  if not os.path.exists(SYN.SYN_OUTPUT_DIRECTORY):
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY) 

  path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "clk_cross_t_pkg" + VHDL_PKG_EXT
  
  f=open(path,"w")
  f.write(text)
  f.close()
  

def WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state):
  
  text = ""
  pkg_body_text = ""
  
  text += '''
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
-- All structs defined in C code

package c_structs_pkg is
'''
  
  
  # Do this stupid dumb loop to resolve dependencies
  # Hacky resolve dependencies
  types_written = []
  # Uhh sooopppaa hacky
  for i in range(1, 257):
    types_written.append("uint" + str(i) + "_t")
    types_written.append("int" + str(i) + "_t")
  # Oh dont forget to be extra dumb
  types_written.append("float")
  # Oh hey adding to the dumb
  types_written.append("char")
  
  
  # Write structs
  done = False
  while not done:
    done = True
  
  
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~   ENUMS  ~~~~~~~~~~~~~~~~~~~~~~~~~~#
    # Enum types
    for enum_name in list(parser_state.enum_to_ids_dict.keys()):    
      if enum_name not in types_written:
        done = False
        types_written.append(enum_name)
        # Type
        text += '''
  type ''' + enum_name + ''' is (
    ''' 
        ids_list = parser_state.enum_to_ids_dict[enum_name]
        for field in ids_list:
          text += '''
      ''' + field + ''','''
        
        text = text.strip(",")
        text += '''
  );
  '''

  
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~   ARRAYS  ~~~~~~~~~~~~~~~~~~~~~~~~~~#
    # C arrays are multidimensional and single element type
    # Find all array types - need to do this since array types are not (right now) 
    # declared/typedef individually like structs
    array_types = []
    for func_name in parser_state.FuncLogicLookupTable:
      logic = parser_state.FuncLogicLookupTable[func_name]
      for wire in logic.wire_to_c_type:
        c_type = logic.wire_to_c_type[wire]
        if (c_type not in types_written) and C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type) and (c_type not in array_types):
          elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
          if elem_type in types_written:
            array_types.append(c_type)
    # Get array types declared in structs
    for struct_name in parser_state.struct_to_field_type_dict:
      field_type_dict = parser_state.struct_to_field_type_dict[struct_name]
      for field_name in field_type_dict:
        field_type = field_type_dict[field_name]
        if  (field_type not in types_written) and C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type) and not(field_type in array_types):
          elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          if elem_type in types_written:
            array_types.append(field_type)  
                  
    # Write VHDL type for each
    for array_type in array_types:
      vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(array_type,parser_state)
      elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(array_type)
      # type uint64_t_3_4 is array(0 to 2) of uint64_t_4;
      for i in range(len(dims)-1, -1, -1):
        # Build type
        new_dims = dims[i:]
        new_type = elem_type
        for new_dim in new_dims:
          new_type += "[" + str(new_dim) + "]"
        
        # Write the type if nto already written
        if new_type not in types_written:
          types_written.append(new_type)
          done = False
          new_vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(new_type,parser_state)
          inner_type_dims = new_dims[1:]
          inner_type = elem_type
          for inner_type_dim in inner_type_dims:
            inner_type += "[" + str(inner_type_dim) + "]"
          inner_vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(inner_type,parser_state)
          # Type def
          line = "type " + new_vhdl_type + " is array(0 to " + str(new_dims[0]-1) + ") of " + inner_vhdl_type + ";\n"
          text += line
          # SLV LEN
          inner_size_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(inner_type,parser_state)
          text += '''constant ''' + new_vhdl_type + '''_SLV_LEN : integer := ''' + inner_size_str + ''' * ''' + str(new_dims[0]) + ''';\n'''
          # type_to_slv
          func_decl_text = ""
          func_decl_text += '''
      function ''' + new_vhdl_type + '''_to_slv(data : ''' + new_vhdl_type + ''') return std_logic_vector'''
          func_body_text = ""
          func_body_text += ''' is
        variable rv : std_logic_vector('''+new_vhdl_type+'''_SLV_LEN-1 downto 0);
        variable pos : integer := 0;
      begin
    '''
          vhdl_slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(inner_type,parser_state)
          to_slv_toks = VHDL_TYPE_TO_SLV_TOKS(inner_vhdl_type, parser_state)
          for i in range(0, new_dims[0]):
            func_body_text += '''
            rv((pos+'''+vhdl_slv_len_str+''')-1 downto pos) := ''' + to_slv_toks[0] + "data(" + str(i) + ")" + to_slv_toks[1] + ''';
            pos := pos + '''+vhdl_slv_len_str+''';
    '''          
          func_body_text += '''
          return rv;
      end function;
    '''
          text += func_decl_text + ";\n"
          pkg_body_text += func_decl_text + func_body_text
          
          
          # slv to type
          func_decl_text = ""
          func_decl_text += '''
      function slv_to_''' + new_vhdl_type + '''(data : std_logic_vector) return ''' + new_vhdl_type
          func_body_text = ""
          # Need intermediate 'downto 0' elem_slv for passing into from_slv func
          func_body_text += ''' is
        variable rv : ''' + new_vhdl_type + ''';
        variable elem_slv : std_logic_vector(''' + inner_size_str + '''-1 downto 0);
        variable pos : integer := 0;
      begin
    '''
          vhdl_slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(inner_type,parser_state)
          from_slv_toks = VHDL_TYPE_FROM_SLV_TOKS(inner_vhdl_type, parser_state)
          for i in range(0, new_dims[0]):
            func_body_text += '''
            elem_slv := data((pos+'''+vhdl_slv_len_str+''')-1 downto pos);
            rv(''' + str(i) + ''') := ''' + from_slv_toks[0] + '''elem_slv''' + from_slv_toks[1] + ''';
            pos := pos + '''+vhdl_slv_len_str+''';
    '''
          func_body_text += '''
          return rv;
      end function;
    '''
          text += func_decl_text + ";\n"
          pkg_body_text += func_decl_text + func_body_text
          
          
          

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~   STRUCTS  ~~~~~~~~~~~~~~~~~~~~~~~~~~#
    for struct_name in parser_state.struct_to_field_type_dict:
      #print "STRUCT",struct_name, struct_name in types_written
      # When to stop?
      if struct_name in types_written:
        continue  
              
      # Resolve dependencies:
      # Check if all the types for this struct are written or not structs
      field_type_dict = parser_state.struct_to_field_type_dict[struct_name]
      field_types_written = True
      for field in field_type_dict:
        c_type = field_type_dict[field]
        if c_type not in types_written:
          #print c_type, "NOT IN TYPES WRITTEN"
          field_types_written = False
          break
      if not field_types_written:
        continue
          
      
      # Write type
      types_written.append(struct_name)
      done = False
        
      text += '''
  type ''' + struct_name + ''' is record
  '''
      for field in field_type_dict:
        c_type = field_type_dict[field]
        vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type,parser_state)
        text += '''
    ''' + field + ''' : ''' + vhdl_type + ''';'''
      
      text += '''
  end record;
  '''

      # Null value
      text += '''
  constant ''' + struct_name + '''_NULL : ''' + struct_name + ''' := (
  '''
      for field in field_type_dict:
        c_type = field_type_dict[field]
        vhdl_null_str = C_TYPE_STR_TO_VHDL_NULL_STR(c_type,parser_state)
        text += '''
    ''' + field + ''' => ''' + vhdl_null_str + ''','''
    
      text = text.strip(",")
      
      text += '''
  );
  '''
      
      # SLV LENGTH
      text += '''
  constant ''' + struct_name + '''_SLV_LEN : integer := (
  '''
      for field in field_type_dict:
        c_type = field_type_dict[field]
        slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type,parser_state)
        text += slv_len_str + "+"
      text = text.strip("+")
      text += '''
  );
  '''
  
      # type_to_slv
      func_decl_text = ""
      func_decl_text += '''
  function ''' + struct_name + '''_to_slv(data : ''' + struct_name + ''') return std_logic_vector'''
      func_body_text = ""
      func_body_text += ''' is
    variable rv : std_logic_vector('''+struct_name+'''_SLV_LEN-1 downto 0);
    variable pos : integer := 0;
  begin
'''
      for field in field_type_dict:
        c_type = field_type_dict[field]
        vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type,parser_state)
        vhdl_slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type,parser_state)
        to_slv_toks = VHDL_TYPE_TO_SLV_TOKS(vhdl_type, parser_state)
        func_body_text += '''
        rv((pos+'''+vhdl_slv_len_str+''')-1 downto pos) := ''' + to_slv_toks[0] + "data." + field + to_slv_toks[1] + ''';
        pos := pos + '''+vhdl_slv_len_str+''';
'''
      func_body_text += '''
      return rv;
  end function;
'''
      text += func_decl_text + ";\n"
      pkg_body_text += func_decl_text + func_body_text
      
      
      # slv to type
      func_decl_text = ""
      func_decl_text += '''
  function slv_to_''' + struct_name + '''(data : std_logic_vector) return ''' + struct_name
      func_body_text = ""
      func_body_text += ''' is
    variable rv : ''' + struct_name + ''';
    variable pos : integer := 0;'''
      # Need intermediate 'downto 0' slv slices for passing into from_slv func for each field
      for field in field_type_dict:
        c_type = field_type_dict[field]
        vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type,parser_state)
        vhdl_slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type,parser_state)
        from_slv_toks = VHDL_TYPE_FROM_SLV_TOKS(vhdl_type, parser_state)
        func_body_text += '''
    variable ''' + field + '''_slv : std_logic_vector(''' + vhdl_slv_len_str + '''-1 downto 0);'''
      # Rest of func body
      func_body_text += '''
  begin
'''
      for field in field_type_dict:
        c_type = field_type_dict[field]
        vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type,parser_state)
        vhdl_slv_len_str = C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type,parser_state)
        from_slv_toks = VHDL_TYPE_FROM_SLV_TOKS(vhdl_type, parser_state)
        func_body_text += '''
        ''' + field + '''_slv := data((pos+'''+vhdl_slv_len_str+''')-1 downto pos);
        rv.''' + field + ''' := ''' + from_slv_toks[0] + field + '''_slv''' + from_slv_toks[1] + ''';
        pos := pos + '''+vhdl_slv_len_str+''';
'''
      func_body_text += '''
      return rv;
  end function;
'''
      text += func_decl_text + ";\n"
      pkg_body_text += func_decl_text + func_body_text
      
      
      
      
       
  
  ######################
  # End dumb while loop  
  text += '''
end c_structs_pkg;
'''  
  
  if pkg_body_text != "":
    text += "package body c_structs_pkg is\n"
    text += pkg_body_text
    text += "end package body c_structs_pkg;\n"
  

  if not os.path.exists(SYN.SYN_OUTPUT_DIRECTORY):
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY) 
  
  
  path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "c_structs_pkg" + VHDL_PKG_EXT
  
  f=open(path,"w")
  f.write(text)
  f.close()
  
# Sufjan Stevens - Adlai Stevenson
# Similar to TYPE_RESOLVE_ASSIGNMENT_RHS
def VHDL_TYPE_TO_SLV_TOKS(vhdl_type, parser_state):
  if vhdl_type.startswith("std_logic_vector"):
    return ["",""]
  elif vhdl_type.startswith("unsigned") or vhdl_type.startswith("signed"):
    return ["std_logic_vector(",")"]
  elif vhdl_type in parser_state.enum_to_ids_dict: # same name as c type hacky
    num_ids = len(parser_state.enum_to_ids_dict[vhdl_type])
    width = int(math.ceil(math.log(num_ids,2)))
    return ["std_logic_vector(to_unsigned(" + vhdl_type + "'pos(" , ") ," + str(width) + "))"]
  else:
    return [vhdl_type + "_to_slv(",")"]
    
def VHDL_TYPE_FROM_SLV_TOKS(vhdl_type, parser_state):
  if vhdl_type.startswith("std_logic_vector"):
    return ["",""]
  elif vhdl_type.startswith("unsigned"):
    return ["unsigned(",")"] 
  elif vhdl_type.startswith("signed"):
    return ["signed(",")"]
  elif vhdl_type in parser_state.enum_to_ids_dict: # same name as c type hacky
    num_ids = len(parser_state.enum_to_ids_dict[vhdl_type])
    width = int(math.ceil(math.log(num_ids,2)))
    return [vhdl_type + "'val(to_integer(unsigned(", ")))"]
  else:
    return ["slv_to_" + vhdl_type + "(",")"]

def LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state):
  # Submodules determine if logic needs port    
  needs_clk_cross_to_module = False
  for inst in Logic.submodule_instances:
    submodule_logic_name = Logic.submodule_instances[inst]
    if submodule_logic_name in parser_state.FuncLogicLookupTable:
      submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
      if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
        var_name = C_TO_LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(submodule_logic_name)
        clk_cross_info = parser_state.clk_cross_var_info[var_name]
        needs_clk_cross_to_module = needs_clk_cross_to_module or ("_READ" in submodule_logic_name) or clk_cross_info.flow_control
      if needs_clk_cross_to_module:
        return True
      # Then check sub-sub modules
      needs_clk_cross_to_module = needs_clk_cross_to_module or LOGIC_NEEDS_CLK_CROSS_TO_MODULE(submodule_logic, parser_state)
      if needs_clk_cross_to_module:
        return True
        
  return needs_clk_cross_to_module

def LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state):
  # Submodules determine if logic needs port    
  needs_module_to_clk_cross = False
  for inst in Logic.submodule_instances:
    submodule_logic_name = Logic.submodule_instances[inst]
    if submodule_logic_name in parser_state.FuncLogicLookupTable:
      submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
      if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
        var_name = C_TO_LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(submodule_logic_name)
        clk_cross_info = parser_state.clk_cross_var_info[var_name]
        needs_module_to_clk_cross = needs_module_to_clk_cross or ("_WRITE" in submodule_logic_name) or clk_cross_info.flow_control
      if needs_module_to_clk_cross:
        return True
      # Then check sub-sub modules
      needs_module_to_clk_cross = needs_module_to_clk_cross or LOGIC_NEEDS_MODULE_TO_CLK_CROSS(submodule_logic, parser_state)
      if needs_module_to_clk_cross:
        return True
    
  return needs_module_to_clk_cross

def LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable):
  timing_params = TimingParamsLookupTable[inst_name]
  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  i_need_clk = LOGIC_NEEDS_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable) or Logic.is_vhdl_text_module
  needs_clk = i_need_clk
  # No need ot check subs if self needs already
  if needs_clk:
    return needs_clk
  
  # Check submodules too
  for inst in Logic.submodule_instances:
    instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
    submodule_logic_name = Logic.submodule_instances[inst]
    submodule_logic = parser_state.LogicInstLookupTable[instance_name]
    needs_clk = needs_clk or LOGIC_NEEDS_CLOCK(instance_name, submodule_logic, parser_state, TimingParamsLookupTable)
    if needs_clk: # got set
      break
      
  return needs_clk
  
def LOGIC_NEEDS_SELF_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable):
  # Only need self regs if latency >0 clocks
  timing_params = TimingParamsLookupTable[inst_name]
  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  i_need_self_regs = latency>0
  
  return i_need_self_regs
  
def LOGIC_NEEDS_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable):
  # Types of regs: self, global, volatile global
  needs_self_regs = LOGIC_NEEDS_SELF_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable)
  return needs_self_regs or len(Logic.state_regs) > 0
  
def GET_VHDL_TEXT_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
    # Logic should have exactly one __vhdl__ func submodule to get text from
    if len(Logic.submodule_instances) != 1:
      print("Bad vhdl text sub count", len(Logic.submodule_instances))
      sys.exit(-1)
    sub_func_name = list(Logic.submodule_instances.values())[0]
    sub_inst_name = list(Logic.submodule_instances.keys())[0]
    if sub_func_name != C_TO_LOGIC.VHDL_FUNC_NAME:
      print("Bad vhdl text sub func name")
      sys.exit(-1)      
    c_ast_node = Logic.submodule_instance_to_c_ast_node[sub_inst_name]
    text = c_ast_node.args.exprs[0].value.strip('"')[:]
    # hacky replace two chars \n with single char '\n'
    text = text.replace('\\' + 'n', '\n')
    #print text
    return text
    
def GET_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  if SW_LIB.IS_MEM(Logic):
    return RAW_VHDL.GET_MEM_ARCH_DECL_TEXT(Logic, parser_state, TimingParamsLookupTable)
  else:
    return GET_PIPELINE_ARCH_DECL_TEXT(inst_name,Logic, parser_state, TimingParamsLookupTable)
    
def GET_PIPELINE_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  timing_params = TimingParamsLookupTable[inst_name]
  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  needs_clk = LOGIC_NEEDS_CLOCK(inst_name,Logic, parser_state, TimingParamsLookupTable)
  needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
  needs_regs = LOGIC_NEEDS_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable)
  needs_self_regs = LOGIC_NEEDS_SELF_REGS(inst_name,Logic, parser_state, TimingParamsLookupTable)
  
  rv = ""
  # Stuff originally in package
  rv += "-- Types and such\n"
  rv += "-- Declarations\n"
  
  # Declare total latency for Logic
  rv += "constant LATENCY : integer := " + str(latency) + ";\n"
  
  # Type for wires/variables
  varables_t_pre = ""
  varables_t_pre += "\n"
  varables_t_pre += "-- One struct to represent this modules variables\n"
  varables_t_pre += "type variables_t is record\n"
  varables_t_pre += " -- All of the wires in function\n"
  wrote_variables_t = False
  # Raw HDL functions are done differently
  if len(Logic.submodule_instances) <= 0 and Logic.func_name not in parser_state.main_mhz:
    text = RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(inst_name, Logic, parser_state, timing_params)
    if text != "":
      rv += varables_t_pre
      rv += text
      rv += "end record;\n"
      wrote_variables_t = True
  else:
    wrote_variables_t = True
    rv += varables_t_pre
    # Not c built in
    # First get wires from declarations and assignments Logic itself
    # sort wires so easy to find bugs?
    text_additions = []
    for wire_name in Logic.wire_to_c_type:
      # Skip constants here
      if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name):
        continue

      # Skip globals too
      # Dont skip volatile globals, they are like regular wires   
      if wire_name in Logic.state_regs and not Logic.state_regs[wire_name].is_volatile:
        continue      
      
      # Skip VHDL input wires 
      if C_TO_LOGIC.WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(wire_name, Logic, parser_state):
        continue
      if C_TO_LOGIC.WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(wire_name, Logic, parser_state):
        continue
        
      #print "wire_name", wire_name
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(wire_name, Logic, parser_state)
      #print "wire_name",wire_name
      write_pipe_wire_var_vhdl = WIRE_TO_VHDL_NAME(wire_name, Logic)
      #print "write_pipe_wire_var_vhdl",write_pipe_wire_var_vhdl
      text_additions.append(" " + write_pipe_wire_var_vhdl + " : " + vhdl_type_str + ";\n")
    text_additions.sort()
    for text_addition in text_additions:
      rv += text_addition
      
    rv += "end record;\n"
  
  
  
  if wrote_variables_t:
    rv += '''
-- Type for this modules register pipeline
type register_pipeline_t is array(0 to LATENCY) of variables_t;
  '''
  
  # State registers
  if len(Logic.state_regs) > 0:
    rv += '''
-- Type holding all state registers
type state_registers_t is record'''
    rv += '''
  -- State reg vars\n'''
    for state_reg in Logic.state_regs:
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(state_reg, Logic, parser_state)
      vhdl_name = WIRE_TO_VHDL_NAME(state_reg, Logic)
      rv += " " + vhdl_name + " : " + vhdl_type_str + ";\n"
    rv += "end record;\n"
    
  # Feedback wires
  if len(Logic.feedback_vars) > 0:
    rv += '''
-- Type holding all locally declared (feedback) wires of the func 
type feedback_vars_t is record'''
    rv += '''
  -- Feedback vars\n'''
    for feedback_var in Logic.feedback_vars:
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(feedback_var, Logic, parser_state)
      vhdl_name = WIRE_TO_VHDL_NAME(feedback_var, Logic)
      rv += " " + vhdl_name + " : " + vhdl_type_str + ";\n"
    rv += "end record;\n"
    
  # ALL REGISTERS
  if needs_regs:
    rv += ''' 
  -- Type holding all registers for this function
  type registers_t is record'''
    # Self regs
    if wrote_variables_t and needs_self_regs:
      rv += '''
    self : register_pipeline_t;'''
    # State regs
    if len(Logic.state_regs) > 0:
      rv += '''
    state_regs : state_registers_t;'''
    # End
    rv += ''' 
  end record;
  '''
  
  if needs_regs:
    # Function to null out globals
    rv += "\n-- Function to null out just global regs\n"
    rv += "function registers_NULL return registers_t is\n"
    rv += ''' variable rv : registers_t;
  begin
  '''
    # Do each global var
    for state_reg in Logic.state_regs:
      rv += " rv.state_regs." + WIRE_TO_VHDL_NAME(state_reg, Logic) + " := " + STATE_REG_TO_VHDL_INIT_STR(state_reg, Logic, parser_state) + ";\n"    
    rv += '''
    return rv;
  end function;\n
  '''
  
  
  if needs_regs:
    rv += '''-- Registers and signals for this function\n'''
    # Comb signal of main regs
    rv += "signal " + "registers : registers_t;\n"
    # Main regs nulled out
    rv += "signal " + "registers_r : registers_t := registers_NULL;\n"
    # Mark debug?
    if Logic.func_name in parser_state.func_marked_debug:
      rv += "attribute mark_debug : string;\n"
      rv += '''attribute mark_debug of registers_r : signal is "true";\n'''
    rv += "\n"

  if len(Logic.feedback_vars) > 0:
    rv += "signal " + "feedback_vars : feedback_vars_t;\n"

  # Signals for submodule ports
  rv += '''-- Each function instance gets signals\n'''
  for inst in Logic.submodule_instances:
    instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
    submodule_logic_name = Logic.submodule_instances[inst]
    submodule_logic = parser_state.LogicInstLookupTable[instance_name]
    submodule_logic_needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic,parser_state)
    
    # Skip VHDL
    if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
      continue
    # Skip clock cross
    if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
      continue
    
    rv += "-- " + instance_name + "\n"
    # Clock enable
    if submodule_logic_needs_clk_en:
      ce_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(ce_wire,Logic,parser_state)
      rv += "signal " + WIRE_TO_VHDL_NAME(ce_wire, Logic)  + " : " + vhdl_type_str + ";\n"
    # Inputs
    for in_port in submodule_logic.inputs:
      in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(in_wire,Logic,parser_state)
      rv += "signal " + WIRE_TO_VHDL_NAME(in_wire, Logic)  + " : " + vhdl_type_str + ";\n"
    # Outputs
    for out_port in submodule_logic.outputs:
      out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(out_wire,Logic,parser_state)
      rv += "signal " + WIRE_TO_VHDL_NAME(out_wire, Logic) + " : " + vhdl_type_str + ";\n"
    rv += "\n"
    
    
  # Certain submodules are always 0 delay "IS_VHDL_FUNC"
  rv += GET_VHDL_FUNC_SUBMODULE_DECLS(inst_name, Logic, parser_state, TimingParamsLookupTable)

  rv += "\n"
  
  return rv
  
  
def GET_VHDL_FUNC_SUBMODULE_DECLS(inst_name, Logic, parser_state, TimingParamsLookupTable):
  rv = ""
  vhdl_funcs = []
  for inst in Logic.submodule_instances:
    instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
    submodule_logic_name = Logic.submodule_instances[inst]
    timing_params = TimingParamsLookupTable[instance_name]
    submodule_logic = parser_state.LogicInstLookupTable[instance_name]
    if submodule_logic.is_vhdl_func and submodule_logic.func_name not in vhdl_funcs:
      vhdl_funcs.append(submodule_logic.func_name)
      rv += GET_VHDL_FUNC_DECL(instance_name, submodule_logic, parser_state, timing_params)
      rv += "\n"
  return rv;
  
def GET_VHDL_FUNC_DECL(inst_name, vhdl_func_logic, parser_state, timing_params):
  # Modelsim doesnt like 'subtype' names in funcs?
  # (vcom-1115) Subtype indication found where type mark is required.
  def modeldumbsim(vhdl_type_str):
    if vhdl_type_str.startswith("unsigned"):
      vhdl_type_str = "unsigned"
    if vhdl_type_str.startswith("signed"):
      vhdl_type_str = "signed"
    if vhdl_type_str.startswith("std_logic_vector"):
      vhdl_type_str = "std_logic_vector"
    return vhdl_type_str    
  
  rv = ""
  
  rv = '''
function ''' + vhdl_func_logic.func_name + '''('''
  # The inputs of the Logic
  for input_name in vhdl_func_logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,vhdl_func_logic,parser_state)
    vhdl_type_str = modeldumbsim(vhdl_type_str)   
    rv += " " + WIRE_TO_VHDL_NAME(input_name, vhdl_func_logic) + " : " + vhdl_type_str + ";\n"
  
  # Remove last line and semi
  rv = rv.strip("\n")
  rv = rv.strip(";")
  
  # Output is type of return wire
  vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(vhdl_func_logic.outputs[0],vhdl_func_logic,parser_state)
  vhdl_type_str = modeldumbsim(vhdl_type_str)
  
  # Finish params
  rv += ") return " + vhdl_type_str + " is\n"
  
  # Wires (abusing existing function)
  rv += RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT(inst_name, vhdl_func_logic, parser_state, timing_params)
  
  # Func logic (abuse existing logic)
  rv += "\n"
  rv += "begin\n"
  rv += RAW_VHDL.GET_RAW_HDL_ENTITY_PROCESS_STAGES_TEXT(inst_name, vhdl_func_logic, parser_state, timing_params)
  rv += "\n"
  # End func
  rv += '''
end function;
  '''
  
  return rv
  
def GET_FLOAT_PKG_INCLUDE_TEXT():
  if SYN.SYN_TOOL is VIVADO:
    return ""
    return '''
-- TODO WHAT FLOAT PKG WORKS FOR VHDL 2008?
--library ieee_proposed;
--use ieee_proposed.float_pkg.all;
--use ieee.float_pkg.all;
'''
  else:
    return ""

  
def WRITE_LOGIC_ENTITY(inst_name, Logic, output_directory, parser_state, TimingParamsLookupTable,is_final_files=False): 
  # Sanity check until complete sanity has been 100% ensured with absolute certainty ~~~
  if Logic.is_vhdl_func or Logic.is_vhdl_expr:
    print("Why write vhdl func/expr entity?")
    print(0/0)
    sys.exit(-1)
  
  timing_params = TimingParamsLookupTable[inst_name]
  
  filename = GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + ".vhd"

  latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  needs_clk = LOGIC_NEEDS_CLOCK(inst_name,Logic, parser_state, TimingParamsLookupTable)
  needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
  needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state)#, TimingParamsLookupTable)
  needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state)#, TimingParamsLookupTable)
    
  rv = ""
  rv += "library ieee;" + "\n"
  rv += "use ieee.std_logic_1164.all;" + "\n"
  rv += "use ieee.numeric_std.all;" + "\n"
  rv += GET_FLOAT_PKG_INCLUDE_TEXT()
  # Include C defined structs
  rv += "use work.c_structs_pkg.all;\n"
  # Include clock crossing type
  if needs_clk_cross_to_module or needs_module_to_clk_cross:
    rv += "use work.clk_cross_t_pkg.all;\n"

  # Debug
  if not Logic.is_vhdl_text_module:
    num_non_vhdl_expr_submodules = 0
    for submodule_inst in Logic.submodule_instances:
      submodule_func_name = Logic.submodule_instances[submodule_inst]
      submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
      if not submodule_logic.is_vhdl_expr and not submodule_logic.func_name == C_TO_LOGIC.VHDL_FUNC_NAME:
        num_non_vhdl_expr_submodules = num_non_vhdl_expr_submodules + 1
    rv += "-- Submodules: " + str(num_non_vhdl_expr_submodules) + "\n"
  
  
  rv += "entity " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + " is" + "\n"
  
  rv += "port(" + "\n"
  
  # Clock?
  if needs_clk:
    rv += " clk : in std_logic;" + "\n"
    
  # Clock enable
  if needs_clk_en:
    rv += " " + C_TO_LOGIC.CLOCK_ENABLE_NAME + " : in unsigned(0 downto 0);" + "\n"
    
  # Clock cross inputs?
  if needs_clk_cross_to_module:
    rv += " clk_cross_to_module : in " + Logic.func_name + "_clk_cross_to_module_t;" + "\n"
  
  # Clock cross outputs?
  if needs_module_to_clk_cross:
    rv += " module_to_clk_cross : out " + Logic.func_name + "_module_to_clk_cross_t;" + "\n"
    
  # The inputs of the Logic
  for input_name in Logic.inputs:
    # Get type for input
    vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_name,Logic,parser_state)
    
    rv += " " + WIRE_TO_VHDL_NAME(input_name, Logic) + " : in " + vhdl_type_str + ";" + "\n"
  
  # Output is type of return wire
  if len(Logic.outputs) > 0:
    for out_port in Logic.outputs:
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(out_port,Logic,parser_state)
      rv += " " + WIRE_TO_VHDL_NAME(out_port, Logic) + " : out " + vhdl_type_str + ";" + "\n"
  
  rv = rv.strip("\n").strip(";")
  rv += ");" + "\n"
  
  
  rv += "end " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + ";" + "\n"
  
      
  rv += "architecture arch of " + GET_ENTITY_NAME(inst_name, Logic,TimingParamsLookupTable, parser_state) + " is" + "\n"
  
  # Blackboxes replaced with io regs only for timing paths, until final files
  if not is_final_files and Logic.func_name in parser_state.func_marked_blackbox:
    rv += GET_BLACKBOX_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
  # Tool specific hard macros replace entire arch decl and body
  elif C_TO_LOGIC.FUNC_IS_PRIMITIVE(Logic.func_name):
    rv += SYN.SYN_TOOL.GET_PRIMITIVE_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
  # VHDL func replaces arch decl and body
  elif Logic.is_vhdl_text_module:
    rv += GET_VHDL_TEXT_MODULE_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
  else:
    # Get declarations for this arch
    rv += GET_ARCH_DECL_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
    
    rv += "begin" + "\n"

    rv += "\n"
    # Connect submodules
    if len(Logic.submodule_instances) > 0:
      rv += "-- SUBMODULE INSTANCES \n"
      for inst in Logic.submodule_instances:
        instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
        submodule_logic_name = Logic.submodule_instances[inst]
        submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
        
        # Skip VHDL
        if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
          continue 
        # Skip clock crossing
        if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
          continue
        
        new_inst_name = WIRE_TO_VHDL_NAME(inst, Logic)
        rv += "-- " + new_inst_name + "\n"

        # ENTITY
        submodule_timing_params = TimingParamsLookupTable[instance_name];
        submodule_latency = submodule_timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
        submodule_needs_clk = LOGIC_NEEDS_CLOCK(instance_name, submodule_logic, parser_state, TimingParamsLookupTable)
        submodule_needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state)
        submodule_needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(submodule_logic, parser_state)
        submodule_needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(submodule_logic, parser_state)
        rv += new_inst_name+" : entity work." + GET_ENTITY_NAME(instance_name, submodule_logic,TimingParamsLookupTable, parser_state) +" port map (\n"
        if submodule_needs_clk:
          rv += "clk,\n"
        if submodule_needs_clk_en:
          ce_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
          rv += WIRE_TO_VHDL_NAME(ce_wire, Logic) + ",\n"
        # Clock cross in
        if submodule_needs_clk_cross_to_module:
          rv += "clk_cross_to_module." + WIRE_TO_VHDL_NAME(inst) + ",\n"
        # Clock cross out 
        if submodule_needs_module_to_clk_cross:
          rv += "module_to_clk_cross." + WIRE_TO_VHDL_NAME(inst) + ",\n"
        # Inputs
        for in_port in submodule_logic.inputs:
          in_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
          rv += WIRE_TO_VHDL_NAME(in_wire, Logic) + ",\n"
        # Outputs
        for out_port in submodule_logic.outputs:
          out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
          rv += WIRE_TO_VHDL_NAME(out_wire, Logic) + ",\n"
        # Remove last two chars
        rv = rv[0:len(rv)-2]
        rv += ");\n\n"
          
    # Get the text that is actually the pipeline logic in this entity
    rv += "\n"
    rv += GET_PIPELINE_LOGIC_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
  
  # Done with entity
  rv += "\n" + "end arch;" + "\n"

  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
  
  #print "NOT WRITE ENTITY"
  f = open(output_directory+ "/" + filename,"w")
  f.write(rv)
  f.close()
  
def GET_PIPELINE_LOGIC_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  # Special case logic that does not do usage pipeline
  if SW_LIB.IS_MEM(Logic):
    return RAW_VHDL.GET_MEM_PIPELINE_LOGIC_TEXT(Logic, parser_state, TimingParamsLookupTable)
  else:
    # Regular comb logic pipeline
    return GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)

def GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable):
  # Comb Logic pipeline
  needs_clk = LOGIC_NEEDS_CLOCK(inst_name, Logic, parser_state, TimingParamsLookupTable)
  needs_clk_en = C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(Logic, parser_state)
  needs_regs = LOGIC_NEEDS_REGS(inst_name, Logic, parser_state, TimingParamsLookupTable)
  needs_self_regs = LOGIC_NEEDS_SELF_REGS(inst_name,Logic, parser_state, TimingParamsLookupTable)
  needs_clk_cross_to_module = LOGIC_NEEDS_CLK_CROSS_TO_MODULE(Logic, parser_state)#, TimingParamsLookupTable)
  #needs_module_to_clk_cross = LOGIC_NEEDS_MODULE_TO_CLK_CROSS(Logic, parser_state)#, TimingParamsLookupTable)
  
  rv = ""
  rv += "\n"
  rv += " -- Combinatorial process for pipeline stages\n"
  rv += "process "
  process_sens_list = ""
  if needs_clk_en:
    process_sens_list += " CLOCK_ENABLE,\n"
  if len(Logic.inputs) > 0:
    process_sens_list += " -- Inputs\n"
    for input_wire in Logic.inputs:
      vhdl_type_str = WIRE_TO_VHDL_TYPE_STR(input_wire, Logic, parser_state)
      process_sens_list += " " + WIRE_TO_VHDL_NAME(input_wire, Logic) + ",\n"
  if len(Logic.feedback_vars) > 0:
    process_sens_list += " -- Feedback vars\n"
    process_sens_list += " " + "feedback_vars,\n"
  if needs_regs:
    process_sens_list += " -- Registers\n"
    process_sens_list += " " + "registers_r,\n"
  if needs_clk_cross_to_module:
    process_sens_list += " -- Clock cross input\n"
    process_sens_list += " " + "clk_cross_to_module,\n"
  submodule_text = ""
  has_submodules_to_print = False
  if len(Logic.submodule_instances) > 0:
    submodule_text += " -- All submodule outputs\n"
    # Connect submodules
    for inst in Logic.submodule_instances:
      instance_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + inst
      submodule_logic_name = Logic.submodule_instances[inst]
      submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
      
      # Skip vhdl
      if submodule_logic.is_vhdl_func or submodule_logic.is_vhdl_expr:
        continue
      # Skip clock cross
      if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
        continue
      
      has_submodules_to_print = True        
      new_inst_name = C_TO_LOGIC.LEAF_NAME(instance_name, do_submodule_split=True)
      submodule_text += " -- " + new_inst_name + "\n"
      # Outputs
      for out_port in submodule_logic.outputs:
        out_wire = inst + C_TO_LOGIC.SUBMODULE_MARKER + out_port
        submodule_text += " " + WIRE_TO_VHDL_NAME(out_wire, Logic) + ",\n"
  if has_submodules_to_print:
    process_sens_list += submodule_text 
    
  if process_sens_list != "":
    rv += "(\n"
    # Remove last two chars
    process_sens_list = process_sens_list[0:len(process_sens_list)-2]
    rv += process_sens_list
    rv += ")\n"

  rv += "is \n"
  
  # READ PIPE
  rv += " -- Read and write variables to do register transfers per clock\n"
  rv += " -- from the previous to next stage\n"
  rv += " " + "variable read_pipe : variables_t;\n"
  rv += " " + "variable write_pipe : variables_t;\n"
  
  
  # Self regs
  rv += '''
  -- This modules self pipeline registers read once per clock
  variable read_self_regs : register_pipeline_t;
  variable write_self_regs : register_pipeline_t;
''' 
  
  # State regs
  if len(Logic.state_regs) > 0:
    rv += " " + "-- State registers read once per clock\n"
    rv += " " + "variable read_state_regs : state_registers_t;\n"
    rv += " " + "variable write_state_regs : state_registers_t;\n"  
  
  # BEGIN BEGIN BEGIN
  rv += "begin\n"
  
  if needs_self_regs:
    # Self regs
    rv += '''
  -- SELF REGS
  -- Default read self regs once per clock
  read_self_regs := registers_r.self;
  -- Default write contents of self regs
  write_self_regs := read_self_regs;'''
  
  
  # Globals
  if len(Logic.state_regs) > 0:
    rv += '''
  -- STATE REGS
  -- Default read regs once per clock
  read_state_regs := registers_r.state_regs;
  -- Default write contents of regs
  write_state_regs := read_state_regs;
'''
  
  rv += " -- Loop to construct simultaneous register transfers for each of the pipeline stages\n"
  rv += " -- LATENCY=0 is combinational Logic\n"
  rv += " " + "for STAGE in 0 to LATENCY loop\n"
  rv += " " + " " + "-- Input to first stage are inputs to function\n"
  rv += " " + " " + "if STAGE=0 then\n"
  
  if needs_clk_en:
    rv += " " + " " + " " + "-- Mux in clock enable\n"
    rv += " " + " " + " " + "read_pipe." + WIRE_TO_VHDL_NAME(C_TO_LOGIC.CLOCK_ENABLE_NAME, Logic) + " := " + WIRE_TO_VHDL_NAME(C_TO_LOGIC.CLOCK_ENABLE_NAME, Logic) + ";\n"
  
  if len(Logic.inputs) > 0:
    rv += " " + " " + " " + "-- Mux in inputs\n"
    for input_wire in Logic.inputs:
      rv += " " + " " + " " + "read_pipe." + WIRE_TO_VHDL_NAME(input_wire, Logic) + " := " + WIRE_TO_VHDL_NAME(input_wire, Logic) + ";\n"
  
  # Also mux volatile global regs into wire - act like regular wire
  for state_reg in Logic.state_regs:
    if Logic.state_regs[state_reg].is_volatile:
      rv += " " + " " + " " + "read_pipe." + WIRE_TO_VHDL_NAME(state_reg, Logic) + " := write_state_regs." + WIRE_TO_VHDL_NAME(state_reg, Logic) + ";\n"
      
  rv += " " + " " + "else\n"
  rv += " " + " " + " " + "-- Default read from previous stage\n"
  rv += " " + " " + " " + "read_pipe := " + "read_self_regs(STAGE-1);\n"
  rv += " " + " " + "end if;\n"
  rv += " " + " " + "-- Default write contents of previous stage\n"
  rv += " " + " " + "write_pipe := read_pipe;\n"
  rv += "\n"
  
  # C built in Logic is static in the stages code here but coded as generic
  rv += GET_ENTITY_PROCESS_STAGES_TEXT(inst_name, Logic, parser_state, TimingParamsLookupTable)
    
  rv += " " + " " + "-- Write to stage reg\n"
  rv += " " + " " + "write_self_regs(STAGE) := write_pipe;\n"
  rv += " " + "end loop;\n"
  rv += "\n"

  # -- Last stage of pipeline volatile global wires write to function volatile global regs
  rv += " " + "-- Drive volatiles from last stage\n"
  for state_reg in Logic.state_regs:
    if Logic.state_regs[state_reg].is_volatile:
      rv += " " + "write_state_regs." + WIRE_TO_VHDL_NAME(state_reg, Logic) + " := write_self_regs(LATENCY)." + WIRE_TO_VHDL_NAME(state_reg, Logic) + ";\n"
    
  rv += "\n"  
  rv += " " + "-- Drive registers and outputs\n"
  
  for output_wire in Logic.outputs:
    rv += " " + "-- Last stage of pipeline return wire to entity return port\n"
    rv += " " + WIRE_TO_VHDL_NAME(output_wire, Logic) + " <= " + "write_self_regs(LATENCY)." + WIRE_TO_VHDL_NAME(output_wire, Logic) + ";\n"
    
  if needs_self_regs:
    rv += " " + "registers.self <= write_self_regs;\n"
  #   State regs
  if len(Logic.state_regs) > 0:
    rv += " " + "registers.state_regs <= write_state_regs;\n"
    
  # Add wait statement if nothing in sensitivity list for simulation?
  if process_sens_list == "":
    rv += " " + "-- For simulation? \n"
    rv += " " + "wait;\n"
    
  rv += "end process;\n"
  
  # Register the combinatorial registers signal
  if needs_regs:
    rv += "registers_r <= registers when rising_edge(clk)"
    if needs_clk_en:
      rv += " and CLOCK_ENABLE(0)='1'"
    rv += ";\n"
    
  return rv
  

      
# Returns dict[stage_num]=stage_text
def GET_C_ENTITY_PROCESS_PER_STAGE_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
  LogicInstLookupTable = parser_state.LogicInstLookupTable
  # Get the per stage texts and combine
  per_stage_texts = GET_C_ENTITY_PROCESS_PER_STAGE_SUDMODULE_LEVEL_TEXTS(inst_name, logic, parser_state, TimingParamsLookupTable)
  
  per_stage_text = dict()
  for stage in per_stage_texts:
    per_stage_text[stage] = ""
    stages_texts = per_stage_texts[stage]
    for text in stages_texts:
      per_stage_text[stage] += text
  
  return per_stage_text
  
def TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driving_wire, driven_wire, parser_state):
  # Need conversion from right to left?
  right_type = logic.wire_to_c_type[driving_wire]
  #print "driving_wire",driving_wire, right_type
  left_type = logic.wire_to_c_type[driven_wire]
  if left_type != right_type:
    # DO VHDL CONVERSION FUNCTIONS
    resize_toks = []
    
    # Combine driving and driven into one list
    wires_to_check = [driving_wire, driven_wire]
    # If both are of same type then VHDL resize should work
    if WIRES_ARE_INT_N(wires_to_check, logic) or  WIRES_ARE_UINT_N(wires_to_check, logic):
      # Do integer promotion conversion
      right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
      left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
      # Can resize do smaller, and unsigned to unsigned too?
      resize_toks = ["resize(", ", " + str(left_width) + ")" ]
      
    # Otherwise need to 
    # UINT driving INT
    elif WIRES_ARE_INT_N([driven_wire], logic) and WIRES_ARE_UINT_N([driving_wire], logic):
      right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
      left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
      # Just need to add sign bit
      #signed(std_logic_vector(resize(x,left_width)))
      resize_toks = ["signed(std_logic_vector(resize(", ", " + str(left_width) + ")))" ]    
      
    # INT driving UINT
    elif WIRES_ARE_UINT_N([driven_wire], logic) and WIRES_ARE_INT_N([driving_wire], logic):
      right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
      left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
      
      # Dont infer sign extend - why not past me? Were you smarter? Does this break mult?
      if left_width > right_width:
        resize_toks = ["unsigned(std_logic_vector(resize(", "," + str(left_width) + ")))" ]
      else:     
        # Cast int to slv then to unsigned then resize
        #resize(unsigned(std_logic_vector(x)),31)
        #signed(std_logic_vector(resize(x,left_width)))
        resize_toks = ["resize(unsigned(std_logic_vector(", "))," + str(left_width) + ")" ] 
      
    # ENUM DRIVING UINT is ok
    elif WIRES_ARE_UINT_N([driven_wire], logic) and (logic.wire_to_c_type[driving_wire] in parser_state.enum_to_ids_dict):
      left_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_type)
      if right_type in parser_state.enum_to_ids_dict:
        num_ids = len(parser_state.enum_to_ids_dict[right_type])
        right_width = int(math.ceil(math.log(num_ids,2)))
      else:
        right_width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_type)
      max_width = max(left_width,right_width)
      resize_toks = ["to_unsigned(" + right_type + "'pos(" , ") ," + str(max_width) + ")"]
      
    # Making yourself sad to work around issues you didnt forsee is ok
    elif SW_LIB.C_TYPE_IS_ARRAY_STRUCT(left_type, parser_state):
      # Assigning to dumb , dumb = (data => value);  -- no others in struct
      resize_toks = ["(data => ",")"]
    elif SW_LIB.C_TYPE_IS_ARRAY_STRUCT(right_type, parser_state):
      # Assigning to arry from dumb
      # array = dumb.data
      resize_toks = ["",".data"]
    else:
      print("What cant support this assignment in vhdl?")
      print(driving_wire, right_type)
      print("DRIVING")
      print(driven_wire, left_type)
      print(0/0)
      sys.exit(-1)
    
    
    # APPPLY CONVERSION
    RHS = resize_toks[0] + RHS + resize_toks[1] 
    
      
  return RHS


  
def GET_C_ENTITY_PROCESS_PER_STAGE_SUDMODULE_LEVEL_TEXTS(inst_name, logic, parser_state, TimingParamsLookupTable):
  pipeline_map = SYN.GET_PIPELINE_MAP(inst_name, logic, parser_state, TimingParamsLookupTable)
  return pipeline_map.per_stage_texts 

def GET_C_ENTITY_PROCESS_STAGES_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable):
  # Get text per stage
  per_stage_text = GET_C_ENTITY_PROCESS_PER_STAGE_TEXT(inst_name, logic, parser_state, TimingParamsLookupTable)
  
  package_file_text = ""
  for stage_num in range(0, len(per_stage_text)):
    # Write if stage= portion
    if stage_num == 0:
      package_file_text += "  " + " " + "if STAGE = 0 then\n"
    else:
      package_file_text += "  " + " " + "elsif STAGE = " + str(stage_num) + " then\n"
  
    # Write the text
    package_file_text += per_stage_text[stage_num]
    
  # End the stages if
  package_file_text += "  " + " " + "end if;\n"
  
  return package_file_text
  

  
def WIRES_ARE_ENUM(wires, logic, parser_state):
  for wire in wires:
    #print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
    if not C_TO_LOGIC.WIRE_IS_ENUM(wire, logic, parser_state):
      return False
  return True

  

def WIRES_ARE_C_TYPE(wires,c_type_str, logic):
  for wire in wires:
    #print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
    if c_type_str != logic.wire_to_c_type[wire]:
      return False
  return True
  

def WIRES_ARE_UINT_N(wires, logic):
  for wire in wires:
    #print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
    if not C_TYPE_IS_UINT_N(logic.wire_to_c_type[wire]):
      return False
  return True

def WIRES_ARE_INT_N(wires, logic):
  for wire in wires:
    #print "wire",wire,"logic.wire_to_c_type[wire]",logic.wire_to_c_type[wire]
    if not C_TYPE_IS_INT_N(logic.wire_to_c_type[wire]):
      return False
  return True


  
  
def WIRES_TO_C_INT_BIT_WIDTH(wires,logic):
  rv_width = None
  for wire in wires:
    c_type = logic.wire_to_c_type[wire]
    width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
    if rv_width is None:
      rv_width = width
    else:
      if rv_width != width:
        print("Inputs not all same width for C int?", logic.func_name)
        print(logic.wire_to_c_type)
        print("rv_width, width", rv_width, width)
        print(0/0)
        sys.exit(-1)
  return rv_width
  
def GET_RHS(driving_wire_to_handle, inst_name, logic, parser_state, TimingParamsLookupTable, stage_ordered_submodule_list, stage):
  timing_params = TimingParamsLookupTable[inst_name]
  RHS = ""
  # SUBMODULE PORT?
  if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driving_wire_to_handle, logic):    
    # Get submodule name
    toks=driving_wire_to_handle.split(C_TO_LOGIC.SUBMODULE_MARKER)
    driving_submodule_name = C_TO_LOGIC.SUBMODULE_MARKER.join(toks[0:len(toks)-1])
    driving_submodule_inst_name = inst_name + C_TO_LOGIC.SUBMODULE_MARKER + driving_submodule_name
    driving_submodule_latency = timing_params.GET_SUBMODULE_LATENCY(driving_submodule_inst_name, parser_state, TimingParamsLookupTable)
    
    # Which stage was the driving submodule inst, cant just check latency because of sling in betwenes submodules?
    driving_submodule_stage = None
    for stage_i in stage_ordered_submodule_list:
      submodules_in_stage = stage_ordered_submodule_list[stage_i]
      if driving_submodule_name in submodules_in_stage:
        driving_submodule_stage = stage_i
      
    
    # DO NOT USE write_pipe FOR SUBMOUDLE OUTPUT LATER LATENCY
    '''
    if STAGE = 0 then
      write_pipe.BIN_OP_PLUS_main_c_7_left := write_pipe.x; -- main____BIN_OP_PLUS[main_c_7]____left <= main____x
      write_pipe.BIN_OP_PLUS_main_c_7_right := write_pipe.y; -- main____BIN_OP_PLUS[main_c_7]____right <= main____y
      -- BIN_OP_PLUS[main_c_7] LATENCY=2
      main_BIN_OP_PLUS_main_c_7(write_pipe.BIN_OP_PLUS_main_c_7_right, write_pipe.BIN_OP_PLUS_main_c_7_left, write_submodule_regs.BIN_OP_PLUS_main_c_7_registers, write_pipe.BIN_OP_PLUS_main_c_7_return_output);
    elsif STAGE = 1 then
    elsif STAGE = 2 then
      write_pipe.local_main_c_7_0 := write_pipe.BIN_OP_PLUS_main_c_7_return_output; -- main____local_main_c_7_0 <= main____BIN_OP_PLUS[main_c_7]____return_output
      write_pipe.return_output := write_pipe.local_main_c_7_0; -- main____return_output <= main____local_main_c_7_0
    end if;
    '''
    # In above example read of "write_pipe.BIN_OP_PLUS_main_c_7_return_output" in stage 2 is getting the value of BIN_OP_PLUS's output during stage 0 not what we want
    if driving_submodule_stage == stage:
      # Same stage / zero latency use regular write pipe
      RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
    else:
      # Different, previous stage, use signal from submodule instance if latency > 0 
      if driving_submodule_latency > 0:
        # Use signal from submodule entity
        RHS = WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
      else:
        RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
    
  
  # Feedback vars wires
  elif driving_wire_to_handle in logic.feedback_vars:
    RHS = "feedback_vars." + WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
  
  # State regs?
  
  # GLOBAL?
  elif driving_wire_to_handle in logic.state_regs and not logic.state_regs[driving_wire_to_handle].is_volatile:
    #print "DRIVING WIRE GLOBAL"            
    # Globals are special since can contain backwards logic, ex.
    #
    #     end of func driving wire -> global_reg -> start of func input wire
    #         *Logic connects the right side back to the left (assumes global state depends on current state)
    # Since both end+start wires have the same name it looks equivalent to
    #    start of func input wire -> end of func driving wire -> global_reg
    # Also could think about it sort of like of bidir port?
    # BLAH hope this is right. Vote for Bernie Sanders.
    # To clarify whats going on, force use of read_state_regs
    #   This is correct to do for other special
    #   'only used as read' wires like inputs, but not required since those
    #   other wires dont have this same looping backwards behavior
  
    RHS = "read_state_regs." + WIRE_TO_VHDL_NAME(driving_wire_to_handle, logic)
    
  # Volatile globals are like regular wires
  #elif
  
  else:
    # Otherwise use regular wire connection
    RHS = GET_WRITE_PIPE_WIRE_VHDL(driving_wire_to_handle, logic, parser_state)
    
  return RHS
  
def GET_LHS(driven_wire_to_handle, logic, parser_state):
  LHS = ""
  # SUBMODULE PORT?
  if C_TO_LOGIC.WIRE_IS_SUBMODULE_PORT(driven_wire_to_handle, logic):
    LHS = GET_WRITE_PIPE_WIRE_VHDL(driven_wire_to_handle, logic, parser_state)

  # FEEDBACK WIRE?
  elif driven_wire_to_handle in logic.feedback_vars:
    LHS = "feedback_vars." + WIRE_TO_VHDL_NAME(driven_wire_to_handle, logic)

  # GLOBAL?
  elif driven_wire_to_handle in logic.state_regs and not logic.state_regs[driven_wire_to_handle].is_volatile:
    #print "DRIVING WIRE GLOBAL"            
    # Use write side as expected, RHS is special case using read side
    LHS = "write_state_regs." + WIRE_TO_VHDL_NAME(driven_wire_to_handle, logic)
  
  # Volatile globals are like regular wires
  #elif
  
  else:
    # Otherwise use regular wire connection
    LHS = GET_WRITE_PIPE_WIRE_VHDL(driven_wire_to_handle, logic, parser_state)
    
  return LHS

def GET_WRITE_PIPE_WIRE_VHDL(wire_name, Logic, parser_state): 
  # If a constant 
  if C_TO_LOGIC.WIRE_IS_CONSTANT(wire_name):
    # Use type to cast value string to type
    c_type =  Logic.wire_to_c_type[wire_name]
    val_str = C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE(wire_name, Logic, parser_state)
    
    if c_type == 'char':
      vhdl_char_str = "'" + val_str + "'"
      if val_str == '\\n':
        vhdl_char_str = "LF"
      #HAHA have fun filling this in dummy    
      return "to_unsigned(character'pos(" + vhdl_char_str + "), 8)";
    elif C_TYPE_IS_UINT_N(c_type):
      width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
      #Hack hacky?
      # A VHDL integer is defined from range -2147483648 to +2147483647
      if int(val_str) > 2147483647:
        #print("wire_name",wire_name)
        #print("c_type",c_type)
        #print("width",width)
        hex_str = str(hex(int(val_str))).replace("0x","")
        need_resize = len(hex_str)*4 > width
        hex_str = 'X"' + hex_str + '"'
        #print("hex_str",hex_str)
        #sys.exit(0)
        if need_resize:
          return "resize(" + hex_str + ", " + str(width) + ")" # Extra resize needed
        else:
          return hex_str # No extra resizing needed
      else:
        return "to_unsigned(" + val_str + ", " + str(width) + ")"
    elif C_TYPE_IS_INT_N(c_type):
      width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
      return "to_signed(" + val_str + ", " + str(width) + ")"
    elif c_type == "float":
      return "to_slv(to_float(" + val_str + ", 8, 23))"
    else:
      # ASSUMING ENUM AAUAUGHGHGHG????
      #print "wire_name",wire_name
      toks = wire_name.split(C_TO_LOGIC.SUBMODULE_MARKER)
      toks.reverse()
      local_name = toks[0]
      enum_wire = local_name.split("$")[0]
      if not enum_wire.startswith(C_TO_LOGIC.CONST_PREFIX):
        print("Non const enum constant?",enum_wire)
        sys.exit(-1)
      enum_name = enum_wire[len(C_TO_LOGIC.CONST_PREFIX):]
      #print "local_name",local_name
      #print "enum_name",enum_name
      
      # Sanity check that enum exists?
      match = False
      for enum_type in parser_state.enum_to_ids_dict:
        ids = parser_state.enum_to_ids_dict[enum_type]
        if enum_name in ids:
          match = True
          break
      if not match:
        print(parser_state.enum_to_ids_dict)
        print(enum_name, "doesn't look like an ENUM constant?")
        sys.exit(-1)
      
      return enum_name
    
  else:
    #print wire_name, "IS NOT CONSTANT"
    return "write_pipe." + WIRE_TO_VHDL_NAME(wire_name, Logic)  
  
  
def WIRE_TO_VHDL_NAME(wire_name, Logic=None): # TODO remove Logic
  leaf_name = C_TO_LOGIC.LEAF_NAME(wire_name)
  rv = leaf_name.replace(C_TO_LOGIC.SUBMODULE_MARKER,"_").replace("_*","_STAR").replace("[*]","_STAR").replace(".","_").replace("[","_").replace("]","")
  return rv

def GET_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, stage_ordered_submodule_list, stage):
  if submodule_logic.is_vhdl_expr:
    return GET_VHDL_EXPR_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, stage_ordered_submodule_list, stage)
  elif submodule_logic.is_vhdl_func:
    return GET_VHDL_FUNC_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, stage_ordered_submodule_list, stage)
  elif SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
    return GET_CLOCK_CROSS_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic)
  else:
    return GET_NORMAL_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic)

def GET_VHDL_EXPR_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, stage_ordered_submodule_list, stage):
  if submodule_logic.func_name.startswith(C_TO_LOGIC.CONST_REF_RD_FUNC_NAME_PREFIX):
    return GET_CONST_REF_RD_VHDL_EXPR_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, stage_ordered_submodule_list, stage)
  else:
    print("VHDL EXPR connection text for",submodule_logic.func_name)
    sys.exit(-1)

def GET_CONST_REF_RD_VHDL_EXPR_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic, stage_ordered_submodule_list, stage):
  input_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + submodule_logic.inputs[0] 
  driver_of_input = logic.wire_driven_by[input_port_wire]
  output_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + submodule_logic.outputs[0]
  
  # What is the simple expression to append?
  ref_toks = logic.ref_submodule_instance_to_ref_toks[submodule_inst]
  vhdl_ref_str= ""
  for ref_tok in ref_toks[1:]: # Skip base var name
    if type(ref_tok) == int:
      vhdl_ref_str += "(" + str(ref_tok) + ")"
    elif type(ref_tok) == str:
      vhdl_ref_str += "." + ref_tok
    else:
      print("Only constant references right now blbblbaaaghghhh2!", logic.c_ast_node.coord)
      sys.exit(-1)
  
  text = ""
  RHS = GET_RHS(driver_of_input, inst_name, logic, parser_state, TimingParamsLookupTable, stage_ordered_submodule_list, stage)
  TYPE_RESOLVED_RHS = TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driver_of_input, input_port_wire, parser_state)
  text +=  "      " + GET_LHS(output_port_wire, logic, parser_state) + " := " + TYPE_RESOLVED_RHS + vhdl_ref_str + ";\n"
    
  return text
  
def GET_VHDL_FUNC_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, stage_ordered_submodule_list, stage):
  rv = "      "
  # FUNC INSTANCE
  out_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + submodule_logic.outputs[0]
  rv += GET_LHS(out_wire, logic, parser_state) + " := " + submodule_logic.func_name + "(\n"
  for in_port in submodule_logic.inputs:
    in_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + in_port
    driver_of_input = logic.wire_driven_by[in_wire]
    RHS = GET_RHS(driver_of_input, inst_name, logic, parser_state, TimingParamsLookupTable, stage_ordered_submodule_list, stage)
    TYPE_RESOLVED_RHS = TYPE_RESOLVE_ASSIGNMENT_RHS(RHS, logic, driver_of_input, in_wire, parser_state)
    rv += "       " + TYPE_RESOLVED_RHS + ",\n"
  # Remove last two chars
  rv = rv[0:len(rv)-2]
  rv += ");\n"

  return rv

def GET_CLOCK_CROSS_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic):
  # Use logic to write vhdl
  timing_params = TimingParamsLookupTable[inst_name]
  text = ""
  
  var_name = C_TO_LOGIC.CLK_CROSS_FUNC_TO_VAR_NAME(submodule_logic.func_name) 
  clk_cross_info = parser_state.clk_cross_var_info[var_name]
  
  text += "     -- Clock enable" + "\n"
  ce_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
  text += "     module_to_clk_cross." + submodule_logic.func_name + "_" + C_TO_LOGIC.CLOCK_ENABLE_NAME + " <= " + GET_WRITE_PIPE_WIRE_VHDL(ce_port_wire, logic, parser_state) + ";\n"
  
  if len(submodule_logic.inputs) > 0:
    text += "     -- Inputs" + "\n"
  for input_port in submodule_logic.inputs:
    input_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + input_port
    text += "     module_to_clk_cross." + submodule_logic.func_name + "_" + input_port + " <= " + GET_WRITE_PIPE_WIRE_VHDL(input_port_wire, logic, parser_state) + ";\n"

  # Only do output connection if zero clk which it should be
  if submodule_latency_from_container_logic != 0:
    print("Wtf latency clock cross?")
    sys.exit(-1)
  
  if len(submodule_logic.outputs) > 0:
    text += "     -- Outputs" + "\n"
  for output_port in submodule_logic.outputs:
    output_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
    text +=  "      " + GET_WRITE_PIPE_WIRE_VHDL(output_port_wire, logic, parser_state) + " := clk_cross_to_module." + submodule_logic.func_name + "_" + output_port + ";\n"
  
  return text

def GET_NORMAL_ENTITY_CONNECTION_TEXT(submodule_logic, submodule_inst, inst_name, logic, TimingParamsLookupTable, parser_state, submodule_latency_from_container_logic):
  # Use logic to write vhdl
  timing_params = TimingParamsLookupTable[inst_name]
  text = ""
  
  # Maybe drive clock enable
  if C_TO_LOGIC.LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state):
    text += "     -- Clock enable" + "\n"
    ce_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + C_TO_LOGIC.CLOCK_ENABLE_NAME
    text += "     " + WIRE_TO_VHDL_NAME(ce_port_wire, logic) + " <= " + GET_WRITE_PIPE_WIRE_VHDL(ce_port_wire, logic, parser_state) + ";\n"
    
  # Drive input ports
  text += "     -- Inputs" + "\n"
  for input_port in submodule_logic.inputs:
    input_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + input_port
    text += "     " + WIRE_TO_VHDL_NAME(input_port_wire, logic) + " <= " + GET_WRITE_PIPE_WIRE_VHDL(input_port_wire, logic, parser_state) + ";\n"

  # Only do output connection if zero clk 
  if submodule_latency_from_container_logic == 0:
    text += "     -- Outputs" + "\n"
    for output_port in submodule_logic.outputs:
      output_port_wire = submodule_inst + C_TO_LOGIC.SUBMODULE_MARKER + output_port
      text +=  "      " + GET_WRITE_PIPE_WIRE_VHDL(output_port_wire, logic, parser_state) + " := " + WIRE_TO_VHDL_NAME(output_port_wire, logic) + ";\n"
    
  return text

def GET_TOP_ENTITY_NAME(parser_state, multimain_timing_params, inst_name=None):
  if inst_name:
    Logic = parser_state.LogicInstLookupTable[inst_name]
    top_entity_name = GET_ENTITY_NAME(inst_name, Logic,multimain_timing_params.TimingParamsLookupTable, parser_state) + "_top"
  else:
    # Hash for multi main is just hash of main pipes
    hash_ext = multimain_timing_params.GET_HASH_EXT(parser_state)
    # Entity and file name
    top_entity_name = "top" + hash_ext
    
  return top_entity_name

# FUCK? Really need to pull latency calculation out of pipeline map and file names and wtf help
def GET_ENTITY_NAME(inst_name, Logic, TimingParamsLookupTable, parser_state, est_total_latency=None):
  # Sanity check?
  if Logic.is_vhdl_func or Logic.is_vhdl_expr:
    print("Why entity for vhdl func?")
    print(0/0)
    sys.exit(-1)
  
  timing_params = TimingParamsLookupTable[inst_name]
  latency = est_total_latency
  if latency is None:
    latency = timing_params.GET_TOTAL_LATENCY(parser_state, TimingParamsLookupTable)
  return Logic.func_name + "_" +  str(latency) + "CLK" + timing_params.GET_HASH_EXT(TimingParamsLookupTable, parser_state)

def C_ARRAY_TYPE_STR_TO_VHDL_TYPE_STR(c_array_type_str):
  # Just replace brackets with _
  # And add array
  c_array_type_str = c_array_type_str.replace("]","")
  vhdl_type = c_array_type_str.replace("[","_")
  # Like fuck it for now, dont think about it
  return vhdl_type
  
def C_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str, parser_state):
  # Check for int types
  if C_TYPE_IS_INT_N(c_type_str):
    # Get bit width
    width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str)
    return "signed(" + str(width-1) + " downto 0)"
  elif C_TYPE_IS_UINT_N(c_type_str):
    # Get bit width
    width = GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type_str)
    return "unsigned(" + str(width-1) + " downto 0)"
  elif c_type_str == C_TO_LOGIC.BOOL_C_TYPE:
    return "unsigned(0 downto 0)"
  elif c_type_str =="float":
    return "std_logic_vector(31 downto 0)"
  elif C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type_str, parser_state):
    # Use same type from C
    return c_type_str
  elif C_TO_LOGIC.C_TYPE_IS_ENUM(c_type_str, parser_state):
    # Use same type from C
    return c_type_str
  elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type_str):
    return C_ARRAY_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str)    
  else:
    print("Unknown VHDL type for C type: '" + c_type_str + "'")
    #print 0/0
    sys.exit(-1)

def C_TYPE_STR_TO_VHDL_SLV_LEN_STR(c_type_str, parser_state):
  width = GET_WIDTH_FROM_C_TYPE_STR(parser_state,c_type_str,allow_fail=True)
  if width is not None:
    return str(width)
  if C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type_str, parser_state):
    return c_type_str + "_SLV_LEN"
  elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type_str):
    vhdl_type = C_TYPE_STR_TO_VHDL_TYPE_STR(c_type_str, parser_state)
    return vhdl_type + "_SLV_LEN"
  else:
    print("Unknown VHDL slv len str for C type: '" + c_type_str + "'")
    sys.exit(-1)
    
    
def C_TYPE_STR_TO_VHDL_NULL_STR(c_type_str, parser_state):
  # Check for int types
  if C_TYPE_IS_INT_N(c_type_str) or C_TYPE_IS_UINT_N(c_type_str) or (c_type_str == C_TO_LOGIC.BOOL_C_TYPE) or (c_type_str =="float"):
    return "(others => '0')"
  elif C_TO_LOGIC.C_TYPE_IS_STRUCT(c_type_str, parser_state):
    # Use same type from C
    return c_type_str + "_NULL"
  elif C_TO_LOGIC.C_TYPE_IS_ENUM(c_type_str, parser_state):
    # Null is always first,left value
    return c_type_str + "'left"
  elif C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type_str):
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type_str)
    text = ""
    for dim in dims:
      text += "(others => "
    # Null type
    elem_null = C_TYPE_STR_TO_VHDL_NULL_STR(elem_type, parser_state)
    text += elem_null
    # Close parens
    for dim in dims:
      text += ")"
    return text
  else:
    print("Unknown VHDL null str for C type: '" + c_type_str + "'")
    print(0/0)
    sys.exit(-1)
