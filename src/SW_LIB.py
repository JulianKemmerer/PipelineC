import os
import sys
import math
import re
import copy
from pycparser import c_parser, c_ast, c_generator

import C_TO_LOGIC
import VHDL
import SYN
import C_TO_FSM

# Hey lets bootstrap for fun
# Yeah... fun ;)

BIT_MANIP_HEADER_FILE = "bit_manip.h"
BIT_MATH_HEADER_FILE = "bit_math.h"
MEM_HEADER_FILE = "mem.h"
RAM_SP_RF="RAM_SP_RF"
RAM_DP_RF="RAM_DP_RF"

CLOCK_CROSS_HEADER = "var_clock_cross.h"
TYPE_ARRAY_N_T_HEADER = "type_array_N_t.h"
TYPE_BYTES_T_HEADER = "type_bytes_t.h"
FSM_CLK_HEADER = "func"+C_TO_FSM.FSM_EXT+".h"
SINGLE_INST_HEADER = "func_SINGLE_INST.h"
GENERATED_HEADER_DIRS = [
  CLOCK_CROSS_HEADER, 
  TYPE_ARRAY_N_T_HEADER,
  TYPE_BYTES_T_HEADER, 
  FSM_CLK_HEADER,
  SINGLE_INST_HEADER
]

# Find generated logic and apply additional 'parsed' information
def GEN_CODE_POST_PARSE_LOGIC_ADJUST(func_logic, parser_state):
  # Hacky detect+tag clock crossing
  is_clk_cross = False
  if not func_logic.is_c_built_in:
    if '_READ' in func_logic.func_name:
      read_toks = func_logic.func_name.split('_READ')
      var = read_toks[0]
      if var in parser_state.clk_cross_var_info:
        is_clk_cross = True
    if '_WRITE' in func_logic.func_name:
      write_toks = func_logic.func_name.split('_WRITE')
      var = write_toks[0]
      if var in parser_state.clk_cross_var_info:
        is_clk_cross = True
  if is_clk_cross:
    func_logic.is_clock_crossing = True
    # Hacky marking clk cross func read+write as not able to be pipelined
    func_logic.uses_nonvolatile_state_regs = True
    
  return func_logic

def WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE(preprocessed_c_text, parser_state, regenerate_files):
  new_regenerate_files = set()
  new_regenerate_files |= GEN_CLOCK_CROSS_HEADERS(preprocessed_c_text, parser_state, regenerate_files)
  new_regenerate_files |= GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_TYPE_BYTES_HEADERS(preprocessed_c_text, parser_state, regenerate_files)
  new_regenerate_files |= GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_FSM_CLK_FUNC_HEADERS(preprocessed_c_text, parser_state, regenerate_files)
  return new_regenerate_files
  
def GEN_CLOCK_CROSS_HEADERS(preprocessed_c_text, parser_state, regenerate_files): 
  new_regenerate_files = set()
  # Write two funcs in a header for each var
  for var_name in parser_state.clk_cross_var_info:
    c_type = parser_state.global_state_regs[var_name].type_name
    #is_volatile = parser_state.global_state_regs[var_name].is_volatile
    write_size,read_size = parser_state.clk_cross_var_info[var_name].write_read_sizes
    write_func_name, read_func_name = parser_state.clk_cross_var_info[var_name].write_read_funcs
    flow_control = parser_state.clk_cross_var_info[var_name].flow_control
    ratio = 0
    if write_size > read_size:
      ratio = write_size/read_size
    else:
      ratio = read_size/write_size
    ratio = int(ratio)
    text = "#pragma once\n"
    text += '#include "uintN_t.h"\n'
    text += '#define ' + var_name + "_RATIO " + str(ratio) + "\n"
    
    if flow_control:
      # Flow control
      c_type = parser_state.global_state_regs[var_name].type_name
      # Needs to be a 1 dim array for now
      elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
      if len(dims) > 1:
        print("Only single dim in flow control crossing!", var_name)
        sys.exit(0)
      if len(dims) < 1:
        print("No async fifo depth provided for var?:",var_name)
        sys.exit(-1)
      fifo_depth = dims[0]
      c_type = elem_t
      write_in_t = c_type + "[" + str(write_size) + "]"
      read_out_t = c_type + "[" + str(read_size) + "]"
         
      # Define read and write structs
      write_out_t = var_name + "_write_t"
      text += '''typedef struct ''' + write_out_t + '''
{
'''
      text += "uint1_t ready;\n"
      text += "}" + write_out_t + ''';
'''     
      read_out_t = var_name + "_read_t"
      text += '''typedef struct ''' + read_out_t + '''
{
'''
      text += c_type + " data[" + str(read_size) + "]" + ";\n"
      text += "uint1_t valid;\n"
      text += "}" + read_out_t + ''';
'''
    else:
      # No flow control, arrays
      c_type = None
      if var_name in parser_state.global_state_regs:
        c_type = parser_state.global_state_regs[var_name].type_name
      text += '#include "' + c_type + '_array_N_t.h"\n'
      new_regenerate_files.add(c_type + "_array_N_t.h")
      write_out_t = "void"
      write_in_t = c_type + "_array_" + str(write_size) + "_t"
      read_out_t = c_type + "_array_" + str(read_size) + "_t"
      text += '#define ' + var_name + "_write_t " + write_in_t + "\n"
      text += '#define ' + var_name + "_read_t " + read_out_t + "\n"
    
    text += '''
// Clock cross write
'''
    if flow_control:
      text += write_out_t + ''' ''' + write_func_name + "(" + c_type + " write_data[" + str(write_size) + "], uint1_t write_enable)"
    else:
      text += write_out_t + ''' ''' + write_func_name + "(" + write_in_t + " in_data)"
    text += '''
{
  // TODO
}
'''

    text += '''
// Clock cross read
'''
    
    if flow_control:
      text += read_out_t + ''' ''' + read_func_name + "(uint1_t read_enable)"
    else:
      read_in_t = "void"
      text += read_out_t + ''' ''' + read_func_name + "()"
    text += '''
{
  // TODO
}
'''
    # Write file
    path = SYN.SYN_OUTPUT_DIRECTORY + "/" + "clock_crossing" + "/" + var_name + ".h"
    open(path,'w').write(text)
    
  return new_regenerate_files

def WRITE_POST_PREPROCESS_GEN_CODE(preprocessed_c_text, regenerate_files, parser_state):  
  new_regenerate_files = set()
  # type_array_N_t - Since C can return constant size arrays
  new_regenerate_files |= GEN_TYPE_ARRAY_N_HEADERS(preprocessed_c_text, regenerate_files)
  # type_bytes_t - For converting types to/from bytes
  new_regenerate_files |= GEN_POST_PREPROCESS_TYPE_BYTES_HEADERS(preprocessed_c_text, regenerate_files)
  # Clock fsm gen
  new_regenerate_files |= GEN_POST_PREPROCESS_FSM_CLK_HEADERS(preprocessed_c_text, regenerate_files)
  # Single inst gen
  new_regenerate_files |= GEN_POST_PREPROCESS_SINGLE_INST_HEADERS(preprocessed_c_text, regenerate_files, parser_state)
  
  return new_regenerate_files

def FIND_REGEX_MATCHES(regex, text):
  p = re.compile(regex)
  matches = p.findall(text)
  matches = list(set(matches))
  return matches

def GEN_EMPTY_GENERATED_HEADERS(all_code_files, inital_missing_files, parser_state):
  # These headers are generated 
  # by looking for autogenerated header files to be included
  
  existing_files = []
  for f in all_code_files:
    if os.path.exists(f):
      existing_files.append(f)
      
  new_regenerate_files = set()
  
  new_regenerate_files |= GEN_EMPTY_TYPE_ARRAY_N_HEADERS(existing_files, inital_missing_files)
  new_regenerate_files |= GEN_EMPTY_CLOCK_CROSS_HEADERS(existing_files, inital_missing_files)
  new_regenerate_files |= GEN_EMPTY_TYPE_BYTES_HEADERS(existing_files, inital_missing_files)
  new_regenerate_files |= GEN_EMPTY_FSM_CLK_FUNC_HEADERS(existing_files, inital_missing_files, parser_state)
  new_regenerate_files |= GEN_EMPTY_SINGLE_INST_FUNC_HEADERS(existing_files, inital_missing_files, parser_state)
  
  return new_regenerate_files

def GEN_EMPTY_SINGLE_INST_FUNC_HEADERS(existing_files, inital_missing_files, parser_state):
  new_regenerate_files = set()
  for inital_missing_file in inital_missing_files:
    # Regex search c_text for "<func>_SINGLE_INST.h"
    r='\w+_SINGLE_INST.h'
    header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
    func_names = []
    for header_str_quote in header_str_quotes:
      header = header_str_quote.strip('"')
      toks = header.split("_SINGLE_INST.h")
      func_name = toks[0]
      dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + SINGLE_INST_HEADER
      path = dir_name + "/" + func_name + "_SINGLE_INST.h"
      if not os.path.exists(dir_name):
        os.makedirs(dir_name)
      if not os.path.exists(path):
        f = open(path, 'w')
        text = ""
        text += '#include "wire.h"\n'
        #text += '#include "'+func_name+'_INPUT_t_array_N_t.h"\n'
        #text += '#include "'+func_name+'_OUTPUT_t_array_N_t.h"\n'
        f.write(text)
        f.close()
      parser_state.func_single_inst_header_included.add(func_name)
      
  return new_regenerate_files

def GEN_EMPTY_CLOCK_CROSS_HEADERS(all_code_files, inital_missing_files):
  new_regenerate_files = set()
  #for f in all_code_files:
  #  text = C_TO_LOGIC.READ_FILE_REMOVE_COMMENTS(f)
  for inital_missing_file in inital_missing_files:
    # Regex search c_text for "clock_crossing/<type>/<var>.h"
    r='.*clock_crossing.*'
    clock_cross_header_strs = FIND_REGEX_MATCHES(r, inital_missing_file)
    #print("clock_cross_header_str_quotes", clock_cross_header_str_quotes)
    var_names = []
    for clock_cross_header_str in clock_cross_header_strs:
      toks = clock_cross_header_str.split(".h")
      type_slash_var = toks[0]
      if "/" not in type_slash_var:
        var_name = type_slash_var.split("_clock_crossing")[0]
        print("")
        print("Please remove array include:")
        print(f'#include "<type>_array_N_t.h"')
        print("")
        print("And change clock crossing variable in include statement to be like:")
        print(f'#include "clock_crossing/{var_name}.h"')
        sys.exit(-1)
        
      type_slash_toks = type_slash_var.split("/")
      #is_volatile = False
      if len(type_slash_toks)==2:
        cc_str,var_name = type_slash_toks
        dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + "clock_crossing" #+ "/" + var_type
      
      path = dir_name + "/" + var_name + ".h"
      if not os.path.exists(dir_name):
        os.makedirs(dir_name)
      if not os.path.exists(path):
        f = open(path, 'w')
        #f.write(decl_text)
        # Need dummy defines
        f.write('#define ' + var_name + "_RATIO 0\n")
        #f.write('#define ' + var_name + "_write_t int\n")
        #f.write('#define ' + var_name + "_read_t int\n")
        f.write('typedef int ' + var_name + "_write_t;\n")
        f.write('typedef int ' + var_name + "_read_t;\n")
        f.write("")
        f.close()     
  
  return new_regenerate_files
    
def C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state):
  r="\w+_array(_[0-9]+)+_t"
  array_struct_types = FIND_REGEX_MATCHES(r, c_type)
  is_array_type = len(array_struct_types) == 1
  #print "c_type array struct?",c_type, is_array_type
  #TODO inspect type is defined and elem type exists?
  return is_array_type
  
def C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(array_struct_c_type, parser_state):
  s = array_struct_c_type.strip("_t")
  toks = s.split("_array_")
  elem_t = toks[0]
  dims = toks[1].split("_")
  array_c_type = elem_t
  for dim in dims:
    array_c_type += "[" + dim + "]"
  #print "c_type array struct type to array type",array_struct_c_type, array_c_type 
  return array_c_type

def GEN_EMPTY_TYPE_ARRAY_N_HEADERS(all_code_files, inital_missing_files):
  new_regenerate_files = set()
  #for f in all_code_files:
  #  text = C_TO_LOGIC.READ_FILE_REMOVE_COMMENTS(f)
  for inital_missing_file in inital_missing_files:
    # Regex search c_text for "<type>_array_<num>_t.h"
    r='\w+_array_N_t.h'
    array_type_header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
    var_names = []
    for array_type_header_str_quote in array_type_header_str_quotes:
      array_type_header = array_type_header_str_quote.strip('"')
      toks = array_type_header.split("_array_")
      type_name = toks[0]
      dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + TYPE_ARRAY_N_T_HEADER + "/" + type_name + "_array_N_t.h"
      path = dir_name + "/" + type_name + "_array_N_t.h"
      if not os.path.exists(dir_name):
        os.makedirs(dir_name)
      if not os.path.exists(path):
        open(path, 'w').write("")
        
  return new_regenerate_files
      
def GEN_EMPTY_TYPE_BYTES_HEADERS(all_code_files, inital_missing_files):
  new_regenerate_files = set()
  #for f in all_code_files:
  #  text = C_TO_LOGIC.READ_FILE_REMOVE_COMMENTS(f)
  for inital_missing_file in inital_missing_files:
    # Regex search c_text for "<type>_bytes_t.h"
    r='\w+_bytes_t.h'
    bytes_header_str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
    var_names = []
    for bytes_header_str_quote in bytes_header_str_quotes:
      bytes_header = bytes_header_str_quote.strip('"')
      toks = bytes_header.split("_bytes_t.h")
      type_name = toks[0]
      dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + TYPE_BYTES_T_HEADER + "/" + type_name + "_bytes_t.h"
      path = dir_name + "/" + type_name + "_bytes_t.h"
      if not os.path.exists(dir_name):
        os.makedirs(dir_name)
      if not os.path.exists(path):
        open(path, 'w').write("")
        
  return new_regenerate_files
      
def GEN_EMPTY_FSM_CLK_FUNC_HEADERS(all_code_files, inital_missing_files, parser_state):
  new_regenerate_files = set()
  #for f in all_code_files:
  #  text = C_TO_LOGIC.READ_FILE_REMOVE_COMMENTS(f)
  for inital_missing_file in inital_missing_files:
    # Regex search c_text
    r='\w+'+C_TO_FSM.FSM_EXT+'.h'
    str_quotes = FIND_REGEX_MATCHES(r, inital_missing_file)
    var_names = []
    for str_quote in str_quotes:
      header = str_quote.strip('"')
      toks = header.split(C_TO_FSM.FSM_EXT + ".h")
      func_name = toks[0]
      dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + FSM_CLK_HEADER + "/" + func_name + C_TO_FSM.FSM_EXT + ".h"
      path = dir_name + "/" + func_name + C_TO_FSM.FSM_EXT + ".h"
      if not os.path.exists(dir_name):
        os.makedirs(dir_name)
      if not os.path.exists(path):
        open(path, 'w').write("")
      parser_state.func_fsm_header_included.add(func_name)
      
  return new_regenerate_files
      
def GEN_POST_PREPROCESS_SINGLE_INST_HEADERS(preprocessed_c_text, regenerate_files, parser_state):
  # Nothing in preprocessed text to look at so use 
  #parser_state.func_single_inst_header_included
  new_regenerate_files = set()
  
  for func_name in parser_state.func_single_inst_header_included:
    dir_name = SYN.SYN_OUTPUT_DIRECTORY + "/" + SINGLE_INST_HEADER
    path = dir_name + "/" + func_name + "_SINGLE_INST.h"
    if not os.path.exists(dir_name):
      os.makedirs(dir_name)
    if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
      f = open(path, 'w')
      text = ""
      text += '#include "wire.h"\n'
      text += '#include "'+func_name+'_FSM.h"\n'
      new_regenerate_files.add(func_name+'_FSM.h')
      text += func_name+'_INPUT_t '+func_name+'_arb_inputs;\n'
      text += func_name+'_OUTPUT_t '+func_name+'_arb_outputs;\n'
      text += '#pragma IO_PAIR '''+func_name+'_arb_inputs ' + func_name+'_arb_outputs\n'
      text += '#include "clock_crossing/'+func_name+'_arb_inputs.h"\n'
      new_regenerate_files.add('clock_crossing/'+func_name+'_arb_inputs.h')
      text += '#include "clock_crossing/'+func_name+'_arb_outputs.h"\n'
      new_regenerate_files.add('clock_crossing/'+func_name+'_arb_outputs.h')
      text += '''#pragma MAIN '''+func_name+'''_arb
void '''+func_name+'''_arb()
{
  '''+func_name+'''_INPUT_t i;
  '''+func_name+'''_OUTPUT_t o;
  WIRE_READ('''+func_name+'''_INPUT_t, i, '''+func_name+'''_arb_inputs)
  o = '''+func_name+'''_FSM(i);
  WIRE_WRITE('''+func_name+'''_OUTPUT_t, '''+func_name+'''_arb_outputs, o)
}
'''
      f.write(text)
      f.close()
            
  return new_regenerate_files
    
def GEN_POST_PREPROCESS_FSM_CLK_HEADERS(preprocessed_c_text, regenerate_files):
  # Regex search c_text for <type>_bytes_t
  r="\w+"+C_TO_FSM.FSM_EXT
  func_names = FIND_REGEX_MATCHES(r, preprocessed_c_text)

  # #define replacing  Typedef each one
  for func_name in func_names:
    toks = func_name.split(C_TO_FSM.FSM_EXT)
    fsm_clk_func_name = toks[0]
    
    # We are beyond asking for help
    # Your biologial and technological distinctiveness will be added to the project
    # Fake IO types?
    text = ""
    text += '''
typedef uint8_t ''' + fsm_clk_func_name + '''_INPUT_t; // DUMMY
typedef uint8_t ''' + fsm_clk_func_name + '''_OUTPUT_t; // DUMMY
'''

    # Write file
    out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + FSM_CLK_HEADER + "/" + fsm_clk_func_name + C_TO_FSM.FSM_EXT + ".h"
    if not os.path.exists(out_dir):
      os.makedirs(out_dir)    
    path = out_dir + "/" + fsm_clk_func_name + C_TO_FSM.FSM_EXT + ".h"
    if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
      open(path,'w').write(text)
      
  # No extra code gen
  return set()
    
def GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_FSM_CLK_FUNC_HEADERS(preprocessed_c_text, parser_state, regenerate_files):
  for func_name,func_logic in parser_state.FuncLogicLookupTable.items():
    #print(func_logic.func_name, ".is_fsm_clk_func",func_logic.is_fsm_clk_func)
    if func_logic.is_fsm_clk_func:
      text = "#pragma once\n"
      text += C_TO_FSM.FSM_LOGIC_TO_C_CODE(func_logic, parser_state)
      # Write file
      out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + FSM_CLK_HEADER + "/" + func_name + C_TO_FSM.FSM_EXT + ".h"
      if not os.path.exists(out_dir):
        os.makedirs(out_dir)    
      path = out_dir + "/" + func_name + C_TO_FSM.FSM_EXT + ".h"
      open(path,'w').write(text)
      
  # FSM clks do not introduce extra code gen - based on existing user code
  return set()
  

def GEN_POST_PREPROCESS_TYPE_BYTES_HEADERS(preprocessed_c_text, regenerate_files):
  # Regex search c_text for <type>_bytes_t
  r="\w+_bytes_t"
  byte_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)

  # #define replacing  Typedef each one
  for byte_type in byte_types:
    #print "array_type",array_type
    toks = byte_type.split("_bytes_t")
    elem_t = toks[0]
    
    # Dummy typedefs for now to fool c parser?? oh plz help - double up on some help wassup
    # Yall sitting round here helplessnshit
    text = ""
    text += '''
typedef uint8_t ''' + byte_type + '''; // DUMMY
#define ''' + elem_t + "_size_t" + ''' uint32_t // DUMMY
#define ''' + elem_t.upper() + '''_TO_BYTES(so,dumb) // DUMMY
'''

    # Write file
    out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + TYPE_BYTES_T_HEADER + "/" + elem_t + "_bytes_t.h"
    if not os.path.exists(out_dir):
      os.makedirs(out_dir)    
    path = out_dir + "/" + elem_t + "_bytes_t.h"
    if not os.path.exists(path) or "#pragma once\n" not in open(path, "r").read():
      open(path,'w').write(text)
      
  # No extra code gen
  return set()
    
# Hey this function is dumb large
# Just sayin
def GEN_POST_PREPROCESS_WITH_NONFUNCDEFS_TYPE_BYTES_HEADERS(preprocessed_c_text, parser_state, regenerate_files):
  new_regenerate_files = set()
  #print preprocessed_c_text
  # Regex search c_text for <type>_bytes_t
  r="\w+_bytes_t"
  byte_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)
  
  # #define replacing each one with array_n_t type
  for byte_type in byte_types:
    #print "array_type",array_type
    toks = byte_type.split("_bytes_t")
    type_t = toks[0]
    
    # Fully generate a good header file for this type
    text = "#pragma once\n"
    
    # Include bytes for any sub fields of this type
    types_to_include = set()
    if C_TO_LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
      field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
      for field in field_to_type_dict:
        field_type = field_to_type_dict[field]
        type_to_include = field_type
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type):
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          type_to_include = elem_t
        # Ok to hacky replace char with u8 here?
        if type_to_include=="char":
          type_to_include = "uint8_t"
        types_to_include.add(type_to_include)
    for type_to_include in types_to_include:
      text += '#include "' + type_to_include + '_bytes_t.h"\n'
      new_regenerate_files.add(type_to_include + '_bytes_t.h')
    
    # #define the _bytes_t to be the uint8_t_array_N_t type
    size = C_TO_LOGIC.C_TYPE_SIZE(type_t, parser_state, allow_fail=True)
    # hacky mchack
    if size <= 0:
      continue
    text += '#include "uint8_t_array_N_t.h"\n'
    new_regenerate_files.add('uint8_t_array_N_t.h')
    text += "#define " + byte_type + " " + "uint8_t_array_" + str(size) + "_t\n"
    # define a size_t for iterating over as many bytes 
    size_t_width = int(math.ceil(math.log(size,2))) + 1
    size_t = "uint" + str(size_t_width) + "_t"
    text += "#define " + type_t+"_SIZE" + " " + str(size) + "\n"
    text += "#define " + type_t+"_size_t" + " " + size_t + "\n"
    func_name = type_t + "_to_bytes"
    
    # Func type to bytes ###############################################
    text += '''
#pragma FUNC_WIRES ''' + func_name + '''
''' + byte_type + " " + func_name + "(" + type_t + ''' x)
{
''' + byte_type + ''' rv;
'''
    # Base type formulas
    if C_TO_LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
      # Counters for packing into rv
      text += size_t + " pos = 0;\n"
      text += size_t + " field_pos = 0;\n"
      
      # Loop over each field
      field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
      for field in field_to_type_dict:
        text += "// " + field + "\n"
        field_type = field_to_type_dict[field]
        # Need to manually handle array fields for now
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type):
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          # Ok to hacky replace char with u8 here?
          if elem_t=="char":
            elem_t = "uint8_t"          
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            dim = dims[dim_i]
            dim_size_t_width = dim.bit_length()
            dim_size_t = "uint"+str(dim_size_t_width)+"_t"
            dim_var = field + "_dim_"+str(dim_i)
            text += dim_size_t + " " + dim_var + ";\n"
            text += "for("+dim_var+"=0;"+dim_var+"<"+str(dim)+";"+dim_var+"="+dim_var+"+1){\n"
            
          # The repeated bytes assignments similar to normal case below
          # Get bytes
          elem_bytes_var = field + "_elem_bytes"
          text += " " + elem_t + "_bytes_t " + elem_bytes_var + " = " + elem_t + "_to_bytes(x." + field
          for dim_i in range(0,len(dims)):
            dim_var = field + "_dim_"+str(dim_i)
            text += "["+dim_var+"]"
          text += ");\n"
          # Do loop to assign bytes
          text += ''' for(field_pos=0;field_pos<sizeof('''+elem_t+''');field_pos = field_pos + 1)
  {
    rv.data[pos] = ''' + elem_bytes_var + '''.data[field_pos];
    pos = pos + 1;
  }
'''
          # Close braces
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            text += "}\n"
        else:
          # Normal, just do recursive _to_bytes
          text += field_type + "_bytes_t " + field + "_bytes = " + field_type + "_to_bytes(x." + field + ");\n"
          text += '''for(field_pos=0;field_pos<sizeof('''+field_type+''');field_pos = field_pos + 1)
{
  rv.data[pos] = ''' + field + '''_bytes.data[field_pos];
  pos = pos + 1;
}
'''
      
    elif VHDL.C_TYPES_ARE_INTEGERS([type_t]):
      width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
      typeprefix = type_t.split("_t")[0]
      low_i = 0
      high_i = 7
      byte_i = 0
      while high_i < width:
        text += "rv.data[" + str(byte_i) + "] = " + typeprefix + "_" + str(high_i) + "_" + str(low_i) + "(x);\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        text += "rv.data[" + str(byte_i) + "] = " + typeprefix + "_" + str(width-1) + "_" + str(low_i) + "(x);\n"
    elif C_TO_LOGIC.C_TYPE_IS_FLOAT_TYPE(type_t):
      float_bytes = C_TYPE_SIZE(type_t, parser_state)
      for float_byte_i in range(0,float_bytes):
        text += f"rv.data[{float_byte_i}] = {type_t}_{((float_byte_i+1)*8)-1}_{float_byte_i*8}(x);\n"
    elif C_TO_LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
      # How many bytes
      width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, type_t)
      typeprefix = "uint" + str(width)
      int_type =  typeprefix + "_t"
      # Convert to uint
      text += int_type + " int_val = x;\n"
      # Copy uint logic from above
      low_i = 0
      high_i = 7
      byte_i = 0
      while high_i < width:
        text += "rv.data[" + str(byte_i) + "] = " + typeprefix + "_" + str(high_i) + "_" + str(low_i) + "(int_val);\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        text += "rv.data[" + str(byte_i) + "] = " + typeprefix + "_" + str(width-1) + "_" + str(low_i) + "(int_val);\n"
      
    else:
      print("to bytes for type:", type_t)
      sys.exit(-1)

    text += '''
    return rv;
}
'''
    
    # Also gen helper macro
    text += '''
#define ''' + type_t.upper() + '''_TO_BYTES(dst_byte_array, ''' + type_t + '''_x)\\
''' + byte_type + " " + type_t+"_to_bytes_WIRE = " + type_t + "_to_bytes(" + type_t + '''_x);\\
uint32_t ''' + type_t+'''_to_bytes_i;\\
for(''' + type_t + "_to_bytes_i=0;" + type_t+"_to_bytes_i<"+type_t+"_SIZE;"+type_t + '''_to_bytes_i+=1)\\
{\\
  dst_byte_array[''' + type_t+'''_to_bytes_i] = ''' + type_t+'''_to_bytes_WIRE.data[''' + type_t+'''_to_bytes_i];\\
}
'''
        
    # Func bytes to type ###############################################
    func_name = "bytes_to_" + type_t
    text += '''
#pragma FUNC_WIRES ''' + func_name + '''
''' + type_t + " " + func_name + "(uint8_t bytes[" + type_t+"_SIZE"+ '''])
{
''' + type_t + ''' rv;
'''
    # Base type formulas
    if C_TO_LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
      # Counters for packing into rv
      text += size_t + " pos = 0;\n"
      text += size_t + " field_pos = 0;\n"
      
      # Loop over each field
      field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
      for field in field_to_type_dict:
        text += "// " + field + "\n"
        field_type = field_to_type_dict[field]
        # Need to manually handle array fields for now
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type):
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          # Ok to hacky replace char with u8 here?
          if elem_t=="char":
            elem_t = "uint8_t"
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            dim = dims[dim_i]
            dim_size_t_width = dim.bit_length()
            dim_size_t = "uint"+str(dim_size_t_width)+"_t"
            dim_var = field + "_dim_"+str(dim_i)
            text += dim_size_t + " " + dim_var + ";\n"
            text += "for("+dim_var+"=0;"+dim_var+"<"+str(dim)+";"+dim_var+"="+dim_var+"+1){\n"
            
          # The repeated bytes assignments similar to normal case below
          elem_bytes_var = field+"_elem_bytes"
          text += " "+ elem_t + "_bytes_t " + elem_bytes_var + ";\n"
          text += ''' for(field_pos=0;field_pos<sizeof('''+elem_t+''');field_pos = field_pos + 1)
  {
    ''' + elem_bytes_var + '''.data[field_pos] = bytes[pos];
    pos = pos + 1;
  }
'''
          text += " rv."+field
          for dim_i in range(0,len(dims)):
            dim_var = field + "_dim_"+str(dim_i)
            text += "["+dim_var+"]"
          text += " = bytes_to_" + elem_t + "(" + elem_bytes_var + ");\n"
          
          # Close braces
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            text += "}\n"
        else:
          # Normal, just do recursive bytes_to_field_t
          # Assemble bytes for field
          text += field_type + "_bytes_t " + field + "_bytes;\n"
          text += '''for(field_pos=0;field_pos<sizeof('''+field_type+''');field_pos = field_pos + 1)
{
  ''' + field + '''_bytes.data[field_pos] = bytes[pos];
  pos = pos + 1;
}
'''
          text += "rv."+field + " = bytes_to_" + field_type + "(" + field + "_bytes);\n"
          
      
    elif VHDL.C_TYPES_ARE_INTEGERS([type_t]):
      width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
      typeprefix = type_t.split("_t")[0]
      low_i = 0
      high_i = 7
      byte_i = 0
      text += "rv = 0;\n"
      while high_i < width:
        text += "rv = " + typeprefix + "_uint8_" + str(low_i) + "(rv, bytes[" + str(byte_i) + "]);\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        rem = width - low_i
        remprefix = "uint"+str(rem)
        text += "rv = " + typeprefix + "_" + remprefix + "_" + str(low_i) + "(rv, bytes[" + str(byte_i) + "]);\n"
    elif type_t == "float":
      text += '''
    // Assemble 4 byte buffer
    uint8_t buff[sizeof(float)];
    uint3_t buff_pos;
    for(buff_pos=0;buff_pos<sizeof(float);buff_pos=buff_pos+1)
    {
      buff[buff_pos] = bytes[buff_pos];
    }
    // Convert as little endian to uint32_t
    uint32_t val_unsigned;
    val_unsigned = uint8_array4_le(buff);
    // Convert uint32_t to float
    rv = float_uint32(val_unsigned);
      '''
      
    elif C_TO_LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
      # How many bytes
      width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, type_t)
      typeprefix = "uint" + str(width)
      int_type =  typeprefix + "_t"
      # Convert to uint like uint case
      text += int_type + " int_val;\n"
      low_i = 0
      high_i = 7
      byte_i = 0
      text += "int_val = 0;\n"
      while high_i < width:
        text += "int_val = " + typeprefix + "_uint8_" + str(low_i) + "(int_val, bytes[" + str(byte_i) + "]);\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        rem = width - low_i
        remprefix = "uint"+str(rem)
        text += "int_val = " + typeprefix + "_" + remprefix + "_" + str(low_i) + "(int_val, bytes[" + str(byte_i) + "]);\n"
      # And then convert uint to enum
      text += "rv = int_val;\n"
    else:
      print("bytes to for type:", type_t)
      #sys.exit(-1)

    text += '''
    return rv;
}'''

    # Write file
    out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + TYPE_BYTES_T_HEADER + "/" + type_t + "_bytes_t.h"
    if not os.path.exists(out_dir):
      os.makedirs(out_dir)   
    path = out_dir + "/" + type_t + "_bytes_t.h"
    open(path,'w').write(text)
    
    ####################################################################
    #
    ## DO THE SAME THING AGAIN FOR REAL C SOFTWARE SIDE
    #
    ####################################################################
    
    # Fully generate a good header file for this type
    text = "#pragma once\n"

    # Include bytes for any sub fields of this type
    for type_to_include in types_to_include:
      text += '#include "type_bytes_t.h/' + type_to_include + '_bytes_t.h/' +  type_to_include + '_bytes.h"\n'

    text += "#define " + type_t+"_SIZE" + " " + str(size) + "\n"
    
    # #define the _bytes_t to be the uint8_t_array_N_t type
    size = C_TO_LOGIC.C_TYPE_SIZE(type_t, parser_state, allow_fail=True)
    # hacky mchack
    if size <= 0:
      continue
    
    # Func type to bytes ###############################################
    text += '''
void ''' + type_t + "_to_bytes(" + type_t + '''* x, uint8_t* bytes)
{
'''
    # Base type formulas
    if C_TO_LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
      # Counters for packing into rv
      text += "size_t pos = 0;\n"
      
      # Loop over each field
      field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
      for field in field_to_type_dict:
        text += "// " + field + "\n"
        field_type = field_to_type_dict[field]
        field_size = C_TO_LOGIC.C_TYPE_SIZE(field_type, parser_state)
        # Need to manually handle array fields for now
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type):
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          # Ok to hacky replace char with u8 here?
          if elem_t=="char":
            elem_t = "uint8_t" 
          elem_size = C_TO_LOGIC.C_TYPE_SIZE(elem_t, parser_state)
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            dim = dims[dim_i]
            dim_size_t_width = dim.bit_length()
            dim_size_t = "uint"+str(dim_size_t_width)+"_t"
            dim_var = field+"_dim_"+str(dim_i)
            text += "size_t " + dim_var + ";\n"
            text += "for("+dim_var+"=0;"+dim_var+"<"+str(dim)+";"+dim_var+"="+dim_var+"+1){\n"
            
          # The repeated bytes assignments similar to normal case below
          text += " " + elem_t + "_to_bytes(&(x->" + field
          for dim_i in range(0,len(dims)):
            dim_var = field+"_dim_"+str(dim_i)
            text += "["+dim_var+"]"
          text += "), &(bytes[pos]));\n"
          text += " pos = pos + " + str(elem_size) + "; // not sizeof()\n"
          
          # Close braces
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            text += "}\n"
        else:
          # Normal, just do recursive _to_bytes
          text += field_type + "_to_bytes(&(x->" + field + "), &(bytes[pos]));\n"
          text += "pos = pos + " + str(field_size) + "; // not sizeof()\n"
      
    elif VHDL.C_TYPES_ARE_INTEGERS([type_t]):
      width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
      typeprefix = type_t.split("_t")[0]
      low_i = 0
      high_i = 7
      byte_i = 0
      while high_i < width:
        text += "bytes[" + str(byte_i) + "] = (uint8_t)(*x>>" + str(low_i) + ");\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        print("Non byte bit width in C?",width)
        print("Dance Hall - Modest Mouse")
        sys.exit(-1)
    elif type_t == "float":
      text += '''memcpy(bytes, x, 4);
'''
    elif C_TO_LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
      # How many bytes
      num_bytes = C_TO_LOGIC.C_TYPE_SIZE(type_t, parser_state)
      width = 8*num_bytes
      typeprefix = "uint" + str(width)
      int_type =  typeprefix + "_t"
      text += int_type + " int_val = *x;\n"
      # Convert to uint like uint case
      low_i = 0
      high_i = 7
      byte_i = 0
      while high_i < width:
        text += "bytes[" + str(byte_i) + "] = (uint8_t)(int_val>>" + str(low_i) + ");\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        print("Non byte bit width enum to sw bytes??",width,type_t)
        sys.exit(-1)
    else:
      print("to sw bytes for type:", type_t)
      sys.exit(-1)

    text += '''
}
'''

    # Func bytes to type ###############################################
    text += '''
void bytes_to_''' + type_t + "(uint8_t* bytes, " + type_t + '''* x)
{
'''
    # Base type formulas
    if C_TO_LOGIC.C_TYPE_IS_STRUCT(type_t, parser_state):
      # Counters for packing into rv
      text += "size_t pos = 0;\n"
      
      # Loop over each field
      field_to_type_dict = parser_state.struct_to_field_type_dict[type_t]
      for field in field_to_type_dict:
        text += "// " + field + "\n"
        field_type = field_to_type_dict[field]
        field_size = C_TO_LOGIC.C_TYPE_SIZE(field_type, parser_state)
        # Need to manually handle array fields for now
        if C_TO_LOGIC.C_TYPE_IS_ARRAY(field_type):
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(field_type)
          # Ok to hacky replace char with u8 here?
          if elem_t=="char":
            elem_t = "uint8_t" 
          elem_size = C_TO_LOGIC.C_TYPE_SIZE(elem_t, parser_state)
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            dim = dims[dim_i]
            dim_size_t_width = dim.bit_length()
            dim_size_t = "uint"+str(dim_size_t_width)+"_t"
            dim_var = field+"_dim_"+str(dim_i)
            text += "size_t " + dim_var + ";\n"
            text += "for("+dim_var+"=0;"+dim_var+"<"+str(dim)+";"+dim_var+"="+dim_var+"+1){\n"
            
          # The repeated bytes assignments similar to normal case below
          text += " bytes_to_" + elem_t + "(&(bytes[pos]), &(x->" + field
          for dim_i in range(0,len(dims)):
            dim_var = field+"_dim_"+str(dim_i)
            text += "["+dim_var+"]"
          text += "));\n"
          text += " pos = pos + " + str(elem_size) + "; // not sizeof()\n"
          
          # Close braces
          # nest for loop for each dim
          for dim_i in range(0,len(dims)):
            text += "}\n"
        else:
          # Normal, just do recursive _to_bytes
          text += "bytes_to_" + field_type + "(&(bytes[pos]), &(x->" + field + "));\n"
          text += "pos = pos + " + str(field_size) + "; // not sizeof()\n"
      
    elif VHDL.C_TYPES_ARE_INTEGERS([type_t]):
      width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(type_t)
      typeprefix = type_t.split("_t")[0]
      low_i = 0
      high_i = 7
      byte_i = 0
      text += "*x = 0;\n"
      while high_i < width:
        text += "*x |= (((" + type_t + ")bytes[" + str(byte_i) + "])<<"+ str(low_i) + ");\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        print("Non byte bit width in C?",width)
        print("Perfect Disguise - Modest Mouse")
        sys.exit(-1)
    elif type_t == "float":
      text += '''memcpy(x, bytes, 4);
'''
    elif C_TO_LOGIC.C_TYPE_IS_ENUM(type_t, parser_state):
      # How many bytes
      num_bytes = C_TO_LOGIC.C_TYPE_SIZE(type_t, parser_state)
      width = 8*num_bytes
      typeprefix = "uint" + str(width)
      int_type =  typeprefix + "_t"
      # Convert to uint like uint case
      text += int_type + " int_val;\n"
      low_i = 0
      high_i = 7
      byte_i = 0
      text += "int_val = 0;\n"
      while high_i < width:
        text += "int_val |= (((" + int_type + ")bytes[" + str(byte_i) + "])<<"+ str(low_i) + ");\n"
        low_i = low_i + 8
        high_i = high_i + 8
        byte_i = byte_i + 1
      if low_i < width:
        print("Non byte bit width enum from sw bytes??",width,type_t)
        sys.exit(-1)
      # Then convert to enum
      text += "*x = (" + type_t + ")int_val;\n"
    else:
      print("to type from sw bytes, type:", type_t)
      sys.exit(-1)

    text += '''
}
'''

    # Write file
    path = out_dir + "/" + type_t + "_bytes.h" #SW version doesnt have since dont need to deinfe byte type in SW?
    open(path,'w').write(text)
    
    
  return new_regenerate_files
    

def GEN_TYPE_ARRAY_N_HEADERS(preprocessed_c_text, regenerate_files):
  # Regex search c_text for <type>_array_<num>_t
  r="\w+_array_[0-9]+_t"
  array_types = FIND_REGEX_MATCHES(r, preprocessed_c_text)
  #print("preprocessed_c_text",preprocessed_c_text)
  #print("array_types",array_types)
  text_per_elem_t = dict()
  
  # Typedef each one
  for array_type in array_types:
    #print "array_type",array_type
    toks = array_type.split("_array_")
    elem_t = toks[0]
    if elem_t not in text_per_elem_t:
      text_per_elem_t[elem_t] = ""
    
    size_str = toks[1].replace("_t","")   
    text_per_elem_t[elem_t] += '''
typedef struct ''' + array_type + '''
{
  ''' + elem_t + ''' data[''' + size_str + '''];
} ''' + array_type + ''';'''

  # Write files per elem_t
  for elem_t in text_per_elem_t:
    text = text_per_elem_t[elem_t]    
    out_dir = SYN.SYN_OUTPUT_DIRECTORY + "/" + TYPE_ARRAY_N_T_HEADER + "/" + elem_t + "_array_N_t.h"
    if not os.path.exists(out_dir):
      os.makedirs(out_dir)    
    path = out_dir + "/" + elem_t + "_array_N_t.h"
    f = open(path,'w')
    f.write("#pragma once\n")
    f.write(text)
    
  # Does not introduce any more code gen
  return set()

# Auto generated functions are defined in bit manip or math
# Built in functions used in this generated code are not auto generated
def IS_AUTO_GENERATED(logic):
  #print "?? ",logic.func_name, "is built in:", logic.is_c_built_in
  
  rv = ( (   IS_BIT_MANIP(logic)  or
             IS_MEM(logic)       or
             IS_BIT_MATH(logic)         ) 
                and not logic.is_c_built_in )  # Built in functions used in bitmanip+math generated code are not auto generated
  
  
  #print "?? IS_AUTO_GENERATED",rv
      
  return rv          
           # and not logic.is_c_built_in ) or logic.func_name.startswith(
           
           
# Bit manip occurs in bit manip fiel and is not the built in generated code
def IS_BIT_MANIP(logic):
  rv = str(logic.c_ast_node.coord).split(":")[0].endswith(BIT_MANIP_HEADER_FILE) and not logic.is_c_built_in  
  return rv
  
def IS_MEM(logic):
  rv = str(logic.c_ast_node.coord).split(":")[0].endswith(MEM_HEADER_FILE) and not logic.is_c_built_in    
  return rv
  
def IS_BIT_MATH(logic):
  rv = str(logic.c_ast_node.coord).split(":")[0].endswith(BIT_MATH_HEADER_FILE) and not logic.is_c_built_in   
  return rv
  
def FUNC_NAME_INCLUDES_TYPES(logic):
  # Currently this is only needed for bitmanip and bit math
  rv = (
      IS_AUTO_GENERATED(logic) or # Excludes mem below
      logic.func_name.startswith(C_TO_LOGIC.VAR_REF_RD_FUNC_NAME_PREFIX) or 
      logic.func_name.startswith(C_TO_LOGIC.VAR_REF_ASSIGN_FUNC_NAME_PREFIX) or
      logic.func_name.startswith(C_TO_LOGIC.BIN_OP_LOGIC_NAME_PREFIX) or
      logic.func_name.startswith(C_TO_LOGIC.UNARY_OP_LOGIC_NAME_PREFIX) or
      logic.func_name.startswith(C_TO_LOGIC.MUX_LOGIC_NAME)
     )
  
  # Cant be MEM since MEM mem name doesnt include types
  rv = rv and not IS_MEM(logic)
  
  return rv

def GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(c_text, parser_state):
  #print("GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT\n",c_text)
  # DONT FORGET TO CHANGE IS_AUTO_GENERATED and FUNC_NAME_INCLUDES_TYPES??
  lookups = []
  
  # BIT manipulation is auto generated
  bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)
  lookups.append(bit_manip_func_name_logic_lookup)
  
  #print "bit_manip_func_name_logic_lookup",bit_manip_func_name_logic_lookup
  
  ###### THESE DEPEND ON BIT MANIP #TODO: Depedencies what?
  bit_math_func_name_logic_lookup = GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)
  lookups.append(bit_math_func_name_logic_lookup)
  
  #print "bit_math_func_name_logic_lookup",bit_math_func_name_logic_lookup
  
  # MEMORY
  # # TODO MOVE TO WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE?
  mem_func_name_logic_lookup = GET_MEM_H_LOGIC_LOOKUP(parser_state)
  lookups.append(mem_func_name_logic_lookup)
  
  
  # Combine lookups
  rv = dict()
  for func_name_logic_lookup in lookups:
    for func_name in func_name_logic_lookup:
      if not(func_name in rv):
        rv[func_name] = func_name_logic_lookup[func_name]
        #print "func_name (func_name_logic_lookup)",func_name
        #if len(func_name_logic_lookup[func_name].wire_drives) == 0:
        # print "BAD!"
        # sys.exit(-1)
      else:
        # For now allow if from bit manip
        #print "str(rv[func_name].c_ast_node.coord)",str(rv[func_name].c_ast_node.coord)
        if IS_BIT_MANIP(rv[func_name]):
          pass
        else:
          print("GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_CODE_TEXT func_name in multiple dicts?", func_name)
          print("bit_manip_func_name_logic_lookup",bit_manip_func_name_logic_lookup)
          print("===")
          print("bit_math_func_name_logic_lookup",bit_math_func_name_logic_lookup)
          sys.exit(-1)
  
  return rv

# Not including user types and dumb struct thing everywhere we internally run C parsser
# so just fake it # Pups To Dust - Modest Mouse
def C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(c_type, parser_state):
  return C_TO_LOGIC.C_TYPE_IS_USER_TYPE(c_type, parser_state) or C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state) 
  

# Any hardware resource that can described as unit of memory, number of those units, and logic on that memory
# Zero clock cycles just infers RAM primitives implemented in LUTS
# 1 clock means either input or output registers - should infer bram?
# 2 clocks means in and out regs - def BRAMable
# Build more complex multi cycle memory out of these basics - FutureJulian
# Ex. Start with RAM and per device resources fifo primitives, etc ....memory controllers? Next universe up Julian task
#   The Flaming Lips - Fight Test

  
# TODO MOVE TO WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE?
def GET_MEM_H_LOGIC_LOOKUP(parser_state):
  text = ""
  header_text = '''
#include "uintN_t.h"
#include "intN_t.h"
  '''

  # Use primitive mappings of funcs to func calls
  #parser_state.func_name_to_calls, parser_state.func_names_to_called_from
  # Need to indicate that these MEM functions have state registers globals/statics
  # HACK YHACK CHAKC
  func_name_to_state_reg_info = dict()
  func_name_was_global_def = dict()
  # _RAM_SP_RF
  # RAM_DP_RF_RF_2  MORE THAN ONE OUTPUT DATA NEEDS DUMB C STRUCT WRAPPER!!
  ram_types = [RAM_SP_RF+"_0", RAM_SP_RF+"_2", RAM_DP_RF+"_0", RAM_DP_RF+"_2"] # TODO 1clk in OR out regs
  for ram_type in ram_types:
    for calling_func_name,called_func_names in parser_state.func_name_to_calls.items():
      # Get local static var info for this func
      local_state_reg_info_dict = dict()     
      if calling_func_name in parser_state.func_to_local_state_regs:
        local_state_reg_info_dict = parser_state.func_to_local_state_regs[calling_func_name]
        #for local_state_reg_info in local_state_reg_infos_dict.values():
        #  local_state_reg_info_dict[local_state_reg_info.name] = local_state_reg_info
      for called_func_name in called_func_names:
        if called_func_name.endswith(ram_type):
          ram_func_name = called_func_name
          var_name = ram_func_name.replace("_"+ram_type,"")
          #print "var_name",var_name
          # Lookup type, should be global/static, and array
          c_type = None
          # Local scope first
          if var_name in local_state_reg_info_dict:
            c_type = local_state_reg_info_dict[var_name].type_name
            # BAAAHH locally typed/unique func name
            # Mangle name to include calling func if local?
            func_name = calling_func_name + "_" + var_name + "_" + ram_type
            func_name_to_state_reg_info[func_name] = local_state_reg_info_dict[var_name]
            func_name_was_global_def[func_name] = False
          elif var_name in parser_state.global_state_regs:
            c_type = parser_state.global_state_regs[var_name].type_name
            func_name = var_name + "_" + ram_type
            func_name_to_state_reg_info[func_name] = parser_state.global_state_regs[var_name]
            func_name_was_global_def[func_name] = True
          else:
            print("Unknown RAM prim var", var_name)
            sys.exit(-1)         
          
          
          if not C_TO_LOGIC.C_TYPE_IS_ARRAY(c_type):
            print("Ram function on non array?",ram_func_name)
            sys.exit(-1)
          elem_t, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
          # Multiple addresses now folks # Starfucker - Girls Just Want To Have
          #dim = dims[0]
          #addr_t = "uint" + str(int(math.ceil(math.log(dim,2)))) + "_t"            
          
          text += '''
    // ''' + ram_func_name + '''
    '''
          # In case type is actually user type - hacky
          if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(elem_t, parser_state):
            text += '''typedef uint8_t ''' + elem_t + ";\n"
          # Declare global var that matches user
          text += elem_t + ''' ''' + var_name
          for dim in dims:
             text += "[" + str(dim) + "]"
          text += ";\n"
          text += elem_t+ " " + func_name + "("
          if ram_type.startswith(RAM_SP_RF):
            for i in range(0,len(dims)):
              dim = dims[i]
              addr_t = "uint" + str(int(math.ceil(math.log(dim,2)))) + "_t"
              text += addr_t + " addr" + str(i) + ", "
          elif ram_type.startswith(RAM_DP_RF):
            for port_postfix in ["r","w"]:
              for i in range(0,len(dims)):
                dim = dims[i]
                addr_t = "uint" + str(int(math.ceil(math.log(dim,2)))) + "_t"
                text += addr_t + " addr_" + port_postfix + str(i) + ", "
          else:
            print("Unknown ram type:", ram_type)
            sys.exit(-1)
          # DONT ACTUALLY NEED/WANT IMPLEMENTATION FOR MEM SINCE 0 CLK IS BEST DONE/INFERRED AS RAW VHDL 
          text += elem_t + " wd, uint1_t we)" + '''
    {
      /* 
      // Need C code and VHDL equivalents, do VHDL as __vhdl__ literal?
      */
    }
    '''

  #print("MEM_HEADER_FILE")
  #print(text)   
  #sys.exit(-1)
      
  if text != "":
    # Ok had some code, include headers
    text = header_text + text
    outfile = MEM_HEADER_FILE
    parser_state_copy = copy.copy(parser_state) # was DEEPCOPY
    # Keep everything except logic stuff
    parser_state_copy.FuncLogicLookupTable=dict() #dict[func_name]=Logic() instance with just func info
    parser_state_copy.LogicInstLookupTable=dict() #dict[inst_name]=Logic() instance in full
    parser_state_copy.existing_logic = C_TO_LOGIC.Logic() # Temp working copy of logic ? idk it should work
    parse_body = False # MEM DOES NOT HAVE SW IMPLEMENTATION
    FuncLogicLookupTable = C_TO_LOGIC.GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, outfile, parser_state_copy, parse_body)
    
    # Apply hackyness
    for func_name in FuncLogicLookupTable:
      func_logic = FuncLogicLookupTable[func_name]
      state_reg_info = func_name_to_state_reg_info[func_name]
      if func_name_was_global_def[func_name]:
        # Add global for this logic
        #print "RAM GLOBAL:",global_name
        parser_state_copy.existing_logic = func_logic
        func_logic = C_TO_LOGIC.MAYBE_GLOBAL_DECL_TO_LOGIC(state_reg_info.name, parser_state_copy)
        FuncLogicLookupTable[func_name] = func_logic
      elif not func_name_was_global_def[func_name]:
        # Copy into local special here similar to MAYBE_GLOBAL^ above
        # And special removing needing too?
        # Copy info into existing_logic
        func_logic.state_regs[state_reg_info.name] = state_reg_info
        func_logic.wire_to_c_type[state_reg_info.name] = state_reg_info.type_name
        func_logic.variable_names.add(state_reg_info.name)      
        # Record using globals
        if not func_logic.state_regs[state_reg_info.name].is_volatile:
          func_logic.uses_nonvolatile_state_regs = True
          #print "rv.func_name",rv.func_name, rv.uses_nonvolatile_state_regs
        FuncLogicLookupTable[func_name] = func_logic      
      
    return FuncLogicLookupTable
    
  else:
    # No code, no funcs
    return dict()
    
def GET_MEM_NAME(logic):
  if logic.func_name.endswith("_" + RAM_SP_RF+"_0"):
    return RAM_SP_RF+"_0"
  elif logic.func_name.endswith("_" + RAM_SP_RF+"_2"):
    return RAM_SP_RF+"_2"
  elif logic.func_name.endswith("_" + RAM_DP_RF+"_2"):
    return RAM_DP_RF+"_2"
  else:
    print("GET_MEM_NAME for func", logic.func_name, "?")
    sys.exit(-1)
    
def GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_FUNC_NAMES(func_names, parser_state):
  #TODO dont do string search at all - do 'in' list checks?
  c_text = "(".join(func_names)+"(" # hacky af to keep regex matches minimal
  return GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)

def GET_BIT_MATH_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):
  text = ""
  header_text = '''
#include "uintN_t.h"
#include "intN_t.h"
  ''' 
  
  # Regex search c_text
  
  # Negate
  # Parse to list of width toks
  negate_func_names = []
  # uint24_negate(left_resized);
  for type_regex in ["uint[0-9]+_negate\s?\("]: #DO int,float negate?
    p = re.compile(type_regex)
    negate_func_names = p.findall(c_text)
    negate_func_names = list(set(negate_func_names))
    for negate_func_name in negate_func_names:
      negate_func_name = negate_func_name.strip("(").strip()
      toks = negate_func_name.split("_")
      in_prefix = toks[0]
      in_width = int(in_prefix.replace("uint",""))
      result_t = "int" + str(in_width+1) + "_t"
      result_uint_t = "uint" + str(in_width+1) + "_t"
      
      if type_regex == "float":
        print(" #DO int,float negate?")
        sys.exit(-1)
      else:
        in_t = in_prefix + "_t"
        
      func_name = in_prefix + "_negate"
      text += '''
// Negate
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
  // Twos comp
  
  ''' + result_uint_t + ''' x_wide;
  x_wide = x;
  
  ''' + result_uint_t + ''' x_wide_neg;
  x_wide_neg = !x_wide;
  
  ''' + result_uint_t + ''' x_neg_wide_plus1;
  x_neg_wide_plus1 = x_wide_neg + 1;
  
  ''' + result_t + ''' rv;
  rv = x_neg_wide_plus1;
  
  return rv;
}
'''

  # abs
  # Parse to list of width toks
  abs_func_names = []
  # int24_abs(left_resized);
  for type_regex in ["int[0-9]+_abs\s?\("]: # Float abs is bit manip func
    p = re.compile(type_regex)
    abs_func_names = p.findall(c_text)
    abs_func_names = list(set(abs_func_names))
    for abs_func_name in abs_func_names:
      abs_func_name = abs_func_name.strip("(").strip()
      toks = abs_func_name.split("_")
      in_prefix = toks[0]
      in_width = int(in_prefix.replace("int",""))
      sign_index = in_width-1
      result_t = "uint" + str(in_width) + "_t"
      if type_regex == "float":
        print(" #DO float abs?")
        sys.exit(-1)
      else:
        in_t = in_prefix + "_t"
        
      func_name = in_prefix + "_abs"
      text += '''
#include "bit_manip.h"
      
// abs
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
  // Reverse twos comp?
  // Sub one and invert bits
  // Fine with condition since other way is something like  (x + (x >> 31)) ^ (x >> 31)
  // Which is dumb to do in SW
  
  // Get sign
  uint1_t sign;
  sign = ''' + in_prefix + '''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(x);
  
  // Get unsigned x
  ''' + result_t + ''' x_uint;
  x_uint = x;
  
  // Minus 1
  ''' + result_t + ''' x_uint_minus1;
  x_uint_minus1 = x_uint - 1;
  
  // Negate
  ''' + result_t + ''' x_uint_minus1_neg;
  x_uint_minus1_neg = !x_uint_minus1;
  
  ''' + result_t + ''' rv;
  if(sign==1)
  {
    rv = x_uint_minus1_neg;
  }
  else
  {
    rv = x;
  }
  
  return rv;
}
'''






  # N MUX
  # Parse to list of width toks
  nmux_func_names = []
  # uint24_mux24(sel, in0, in1,...);
  #print "DO any type NMUX"
  for type_regex in ["\w+_mux[0-9]+\s?\("]:
    p = re.compile(type_regex)
    nmux_func_names = p.findall(c_text)
    nmux_func_names = list(set(nmux_func_names))
    for nmux_func_name in nmux_func_names:
      nmux_func_name = nmux_func_name.strip("(").strip()
      #print "nmux_func_name",nmux_func_name
      #print c_text
      new_toks = nmux_func_name.split("_mux")
      mux_name = "mux" + new_toks[1]
      n = int(mux_name.replace("mux",""))
      sel_width = int(math.ceil(math.log(n,2)))
      sel_t = "uint" + str(sel_width) + "_t"
      type_prefix = new_toks[0]
      
      # Ew TODO clean up naming - autogenerated funcs should always be <full_type_name>_funcname(
      # Change count0 to like lcount? rcount?
      # See if uint
      toks = type_prefix.split("int")
      if len(toks) == 2 and (toks[0] == "" or toks[0] == "u") and toks[1].isdigit():
        # uint special case, dumb
        type_name = type_prefix + "_t"
      else:
        type_name = type_prefix
      
      result_t = type_name
      in_t = type_name  
      func_name = type_prefix + "_" + mux_name
      var_2_type = dict()

      
      text += '''
#include "bit_manip.h"      
// ''' + str(nmux_func_name) + '''
// ''' + str(n) + ''' MUX\n'''
      if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(result_t, parser_state):
        text += '''
typedef uint8_t ''' + result_t + '''; // FUCK
'''
      text += result_t + " " + func_name+"("+ sel_t + ''' sel,'''
      # List each input
      for i in range(0, n):
        text += in_t + " in" + str(i) + ","
      # Remove last comma
      text = text.strip(",")
      text += ''')
{'''
      
      # Hierarchy of 2x1 muxes
      # Start with list of inputs
      layer = 0
      layer_nodes = [] 
      for i in range(0, n):
        layer_nodes.append("in" + str(i))
      
      # DO
      while True: 
        text += '''
  // Layer ''' + str(layer) + '''
    '''
        # Get sel bit
        sel_var = "sel"+ str(layer) 
        text += '''
  // Get sel bit
  uint1_t ''' + sel_var + ''';
  ''' + sel_var + ''' = uint''' + str(sel_width) + "_" + str(layer) + "_" + str(layer) + '''(sel);
'''
        node = 0
        new_layer_nodes = []
        # Write adds in pairs
        # While 2 args to add
        while(len(layer_nodes) >= 2):
          # Declare result of this mux
          out_var = "layer" + str(layer) + "_node" + str(node)
          text += '''
  ''' + result_t + ''' ''' + out_var + ''';
  '''
          # Do the if
          false_arg = layer_nodes.pop(0)
          true_arg = layer_nodes.pop(0)
          
          
          text +='''// Do regular mux
  if(''' + sel_var + ''')
  {
    ''' + out_var + ''' = ''' + true_arg + ''';
  }
  else
  {
    ''' + out_var + ''' = ''' + false_arg + ''';
  }
  '''
          
          # This out node is on next layer
          new_layer_nodes.append(out_var)
          node += 1
        
        # Out of while loop 
        # < 2 nodes left to sum in this node
        if len(layer_nodes) == 1:
          # One node left
          the_arg = layer_nodes.pop(0)
          # Declare result of this mux
          out_var = "layer" + str(layer) + "_node" + str(node)
          text += '''
  // Odd node in layer
  ''' + result_t + ''' ''' + out_var + ''';
  ''' + out_var + ''' = ''' + the_arg + ''';
  '''
          # This out node is on next layer
          new_layer_nodes.append(out_var)
          node += 1
          
        
        # WHILE
        if len(new_layer_nodes) >= 2:
          # Continue
          layer_nodes = new_layer_nodes
          layer += 1
        else:
          # DONE
          break;

  
  
  
      # Return last out var
      last_out_var = "layer" + str(layer) + "_node" + str(node-1)
      text += ''' 
  return ''' + last_out_var + ''';
}
'''

  #print "MUX"
  #print text

  
  # count0 s
  # Parse to list of width toks
  count0_func_names = []
  # count0s_uint24(left_resized) # Count from left, uint24_count0s counts from right
  for type_regex in ["count0s_uint[0-9]+\s?\("]:
    p = re.compile(type_regex)
    count0_func_names = p.findall(c_text)
    count0_func_names = list(set(count0_func_names))
    for count0_func_name in count0_func_names:
      count0_func_name = count0_func_name.strip("(").strip()
      toks = count0_func_name.split("_")
      in_prefix = toks[1]
      in_t = in_prefix + "_t"
      in_width = int(in_prefix.replace("uint",""))
      # Result width depends on width of input
      # DONT COUNT all zeros since shift after this wont change
      # Only need to count to in_width-1
      result_width = int(math.ceil(math.log(in_width,2)))
      result_prefix = "uint" + str(result_width)
      result_t = result_prefix + "_t"
      func_name = count0_func_name
      
#include "bit_manip.h"
      text += '''
      
// count0s from left
''' + result_t + " " + func_name+"("+ in_t + ''' x)
{
  // First do all the compares in parallel
  // All zeros has has many zeros as width
  uint1_t leading''' + str(in_width) + ''' = (x==0);
  '''
      for leading_zeros in range(1, in_width):
        text += '''
  uint1_t leading''' + str(leading_zeros) + ''';
  leading''' + str(leading_zeros) + ''' = ''' + in_prefix + '''_''' + str(in_width-1) + '''_'''+ str(in_width-1-leading_zeros) + '''(x) == 1;
  
  
  // Mux each one hot into a constant
  // This cant be optimal but better than before for sure
  // Cant I just be happy for a little? maybe later?'''
      # SKIP SUM0 SINCE IS BY DEF 0
      var_2_type = dict()
      for leading_zeros in range(1, in_width+1):
        sum_width = int(math.ceil(math.log(leading_zeros+1,2)))
        sum_prefix = "uint" + str(sum_width)
        sum_t = sum_prefix + "_t"
        var = "sum"+ str(leading_zeros)
        var_2_type[var] = sum_t
        text += '''
  ''' + sum_t + ''' ''' + var + ''';
  if(leading''' + str(leading_zeros) + ''')
  {
    ''' + var + ''' = ''' + str(leading_zeros) + ''';
  }
  else
  {
    ''' + var + ''' = 0;
  }
  '''
  
      # This binary tree thing is weird?
      # Now do binary tree ORing all these single only one will be set
      # Fuck jsut copy from binary tree for mult
      text += '''
  // Binary tree OR of "sums", can sine only one will be set
'''
      layer_nodes = []
      for p in range(1,in_width+1):
        layer_nodes.append("sum" + str(p))
        
      layer=0
      node=0
 
  
      # DO
      while True: 
        text += '''
  // Layer ''' + str(layer) + '''
'''
        node = 0
        new_layer_nodes = []
        # Write adds in pairs
        # While 2 args to add
        while(len(layer_nodes) >= 2):
          left_arg = layer_nodes.pop(0)
          right_arg = layer_nodes.pop(0)
          left_t = var_2_type[left_arg]
          right_t = var_2_type[right_arg]
          # Sum type is max width
          left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
          right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
          max_width = max(left_width,right_width)
          or_width = max_width
          
          sum_t = "uint" + str(or_width) + "_t"
          sum_var = "sum_layer" + str(layer) + "_node" + str(node)
          var_2_type[sum_var] = sum_t
          text += ''' ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + left_arg + " | " + right_arg + ''';
'''
          # This sum node is on next layer
          new_layer_nodes.append(sum_var)
          node += 1
        
        # Out of while loop 
        # < 2 nodes left to sum in this node
        if len(layer_nodes) == 1:
          # One node left
          the_arg = layer_nodes.pop(0)
          the_t = var_2_type[the_arg]
          sum_t = the_t     
          sum_var = "sum_layer" + str(layer) + "_node" + str(node)
          var_2_type[sum_var] = sum_t
          text += ''' // Odd node in layer
  ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + the_arg + ''';
'''
          # This sum node is on next layer
          new_layer_nodes.append(sum_var)
          node += 1
          
        
        # WHILE
        if len(new_layer_nodes) >= 2:
          # Continue
          layer_nodes = new_layer_nodes
          layer += 1
        else:
          # DONE
          break;
      
      # Done with outer layer while loop
        
      # Do return
      return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
      return_t = var_2_type[return_var]
      text += '''
  ''' + "// Return" + '''
  ''' + return_t + ''' rv;
  rv = ''' + return_var + ''';
  return rv;
}
'''



  
  
  
  
  
  
  
  
  
  # N Binary OP (sum, or, and, etc)
  # Also can work with arrays
  # Parse to list of width toks
  n_bin_op_func_names = []
  # uint24_sum24(left_resized);
  # TODO better regexs
  # TODO make full type _t in name not just uintN
  for type_regex in ["int[0-9]+","int[0-9]+_array", "uint[0-9]+","uint[0-9]+_array","float","float_array"]:
    for op_regex in ["sum", "or", "and"]:
      regex = type_regex + "_" + op_regex + "[0-9]+\s?\("
      p = re.compile(regex)
      n_bin_op_func_names_w_paren = p.findall(c_text)
      n_bin_op_func_names_w_paren = list(set(n_bin_op_func_names_w_paren))
      for n_bin_op_func_name_w_paren in n_bin_op_func_names_w_paren:
        n_bin_op_func_name = n_bin_op_func_name_w_paren.strip("(").strip()
        # For now type strings dont include "_"
        # Get toks by splitting on "_"        
        toks = n_bin_op_func_name.split("_")
        # Get type and array info
        in_elem_t_str = toks[0]
        is_array = False
        if len(toks) == 2:
          # Not array
          op_name = toks[1]
        else:
          is_array = True
          op_name = toks[2]
          
        # Get actual elem_t
        # Special case uint, dumb
        if in_elem_t_str == "float":
          in_elem_t = "float"
        else:
          # Assume u/int
          in_elem_t = in_elem_t_str + "_t"
        
        # how many elements?        
        n_elem = int(op_name.replace(op_regex,""))
        #print "n_sum",n_sum
        
        # Result type?
        if in_elem_t == "float":
          result_t = "float"
        else:
          # Assume u/int
          # Depends on op
          if op_regex == "sum":
            type_width = int(in_elem_t_str.replace("uint","").replace("int",""))
            # Sum 2 would be bit width increase of 1
            if in_elem_t.startswith("u"):
              max_in_val = (math.pow(2,type_width)-1)
            else:
              max_in_val = (math.pow(2,type_width-1))
            max_sum = max_in_val * n_elem
            result_width = int(math.ceil(math.log(max_sum+1,2)))
            if in_elem_t.startswith("u"):
              result_t = "uint" + str(result_width) + "_t"
            else:
              result_t = "int" + str(result_width+1) + "_t"
          elif op_regex == "or" or op_regex == "and":
            # Result is same width as input
            result_t = in_elem_t
          else:
            print("Whats32@#%?@#?todo bit widths for array op")
            sys.exit(-1)
        
        # Keep track of variable type so 
        # result type can be determined if needed
        var_2_type = dict()
        
        # Start the code
        text += '''
  #include "bit_manip.h"      
        
  // N binary op
  ''' + result_t + " " + n_bin_op_func_name+"("
        # Input is either single array or many individual elements        
        if is_array:
          # Dont need to store array type in var_2_type
          text += in_elem_t + " x" + "[" + str(n_elem) + "]"
        else: 
          # List each input elements
          for i in range(0, n_elem):
            text += in_elem_t + " x" + str(i) + ","
            var_2_type["x" + str(i)]=in_elem_t
          # Remove last comma
          text = text.strip(",")
          
        # Finish def
        text += ''')
  {'''

        # Do layers of simultaneous operations
        layer_nodes = []
        # Start with inputs
        if is_array:
          for n in range(0,n_elem):
            # Can use const ref string as "variable name"
            var = "x[" + str(n) + "]"
            layer_nodes.append(var)
            var_2_type[var] = in_elem_t
        else:
          for n in range(0,n_elem):
            layer_nodes.append("x" + str(n))
        
        text += '''
        // Binary tree
      '''
            
        # Done as while loop
        layer=0
        node=0

        # DO
        while True: 
          text += '''
        // Layer + ''' + str(layer) + '''
      '''
          node = 0
          new_layer_nodes = []
          # Write ops in pairs
          # While 2 args to do op to
          while(len(layer_nodes) >= 2):
            left_arg = layer_nodes.pop(0)
            right_arg = layer_nodes.pop(0)
            left_t = var_2_type[left_arg]
            right_t = var_2_type[right_arg]
            # What is result of this op?
            # Depends on type
            if in_elem_t == "float":
              op_result_t = "float"
            else:
              # Assume uint
              # Depends on op
              if op_regex == "sum":
                # Sum type is max width+1
                left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
                right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
                max_width = max(left_width,right_width)
                sum_width = max_width+1
                op_result_t = "uint" + str(sum_width) + "_t"
              elif op_regex == "or" or op_regex == "and":
                # Result is same width as input
                op_result_t = in_elem_t
              else:
                print("Whats32?")
                sys.exit(-1)           
            
            op_var = "layer" + str(layer) + "_node" + str(node)
            var_2_type[op_var] = op_result_t
            # Determine C operator
            op_char = None
            if op_regex == "sum":
              op_char = "+"
            elif op_regex == "and":
              op_char = "&"
            elif op_regex == "or":
              op_char = "|"
            else:
              print(0/0)
            
            text += ''' ''' + op_result_t + ''' ''' + op_var + ''';
        ''' + op_var + ''' = ''' + left_arg + " " + op_char + " " + right_arg + ''';
      '''
            # This op node is on next layer
            new_layer_nodes.append(op_var)
            node += 1
          
          # Out of while loop 
          # < 2 nodes left to operate on in this node
          if len(layer_nodes) == 1:
            # One node left
            the_arg = layer_nodes.pop(0)
            the_t = var_2_type[the_arg]
            op_result_t = the_t     
            op_var = "layer" + str(layer) + "_node" + str(node)
            var_2_type[op_var] = op_result_t
            text += ''' // Odd node in layer
        ''' + op_result_t + ''' ''' + op_var + ''';
        ''' + op_var + ''' = ''' + the_arg + ''';
        '''
            # This sum node is on next layer
            new_layer_nodes.append(op_var)
            node += 1
            
          
          # WHILE
          if len(new_layer_nodes) >= 2:
            # Continue
            layer_nodes = new_layer_nodes
            layer += 1
          else:
            # DONE
            break;
        
        # Done with outer layer while loop
          
        # Do return
        return_var = "layer" + str(layer) + "_node" + str(node-1)
        return_t = var_2_type[return_var]
        text += '''
        ''' + "// Return" + '''
        ''' + return_t + ''' rv;
        rv = ''' + return_var + ''';
        return rv;
      }
      '''
      
      
      
      
      
      
      
      
      
      
  #print("BIT_MATH_HEADER_FILE")
  #print(text)
      
      
  if text != "":
    # Ok had some code, include headers
    text = header_text + text
    
    
    outfile = BIT_MATH_HEADER_FILE
    parser_state_copy = copy.copy(parser_state) # was DEEPCOPY()
    # Keep everything except logic stuff
    parser_state_copy.FuncLogicLookupTable=dict() #dict[func_name]=Logic() instance with just func info
    parser_state_copy.LogicInstLookupTable=dict() #dict[inst_name]=Logic() instance in full
    parser_state_copy.existing_logic = C_TO_LOGIC.Logic() # Temp working copy of logic ? idk it should work
    
    ## NEED MANIP in MATH
    
    ''' SWITCH OVER TO ONCE NOT DOING REG EX SEARCH
    # FUNC NAME BASED
    preprocessed_text = C_TO_LOGIC.preprocess_text(text)
    c_file_ast = C_TO_LOGIC.GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(preprocessed_text, "auto_gen_bit_math_fake_filename.c")
    func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_file_ast, c_ast.FuncCall)
    # get list of function names
    func_names = set()
    for func_call_node in func_call_nodes:
      func_name = str(func_call_node.name.name)
      func_names.add(func_name)
    bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_FUNC_NAMES(func_names,parser_state)
    parser_state_copy.FuncLogicLookupTable = bit_manip_func_name_logic_lookup # dict() 
    '''
    
    # C TEXT NAME BASED
    bit_manip_func_name_logic_lookup = GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(text,parser_state)  # DEPENDS ON BIT MANIP # TODO: How to handle dependencies
    parser_state_copy.FuncLogicLookupTable = bit_manip_func_name_logic_lookup # dict() 
    
    
    # Try to get all built in? not just manip? Recursive is nice?
    #print("preprocessed_text",preprocessed_text)
    #parser_state_copy.FuncLogicLookupTable = GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(preprocessed_text, parser_state_copy) #parser_state??
    
    parse_body = True # BIT MATH IS SW IMPLEMENTATION
    FuncLogicLookupTable = C_TO_LOGIC.GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, outfile, parser_state_copy, parse_body)
    
    for func_name in FuncLogicLookupTable:
      func_logic = FuncLogicLookupTable[func_name]
      if len(func_logic.wire_drives) == 0 and str(func_logic.c_ast_node.coord).split(":")[0].endswith(BIT_MATH_HEADER_FILE):
        print("BIT_MATH_HEADER_FILE")
        print(text)
        print("Bad parsing of BIT MATH",func_name)
        sys.exit(-1)
    
    return FuncLogicLookupTable
    
  else:
    # No code, no funcs
    return dict()

def GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_FUNC_NAMES(func_names, parser_state):
  #TODO dont do string search at all - do 'in' list checks?
  c_text = "(".join(func_names)+"(" # hacky af to keep regex matches minimal
  #print("manip func_names",func_names, flush=True)
  return GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state)
  
def GET_BIT_MANIP_H_LOGIC_LOOKUP_FROM_CODE_TEXT(c_text, parser_state):

  # TODO: Do bit select and bit dup as "const int"?
  
  text = ""
  header_text = '''
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
  ''' 
  
  # Regex search c_text
  # Bit select
  # Parse to list of width toks
  bit_sel_func_names = []
  # uint64_39_39(input);
  for type_regex in ["uint[0-9]+","int[0-9]+","float", "float_[0-9]+_[0-9]+_t"]:
    p = re.compile(type_regex + '_[0-9]+_[0-9]+\s?\(')
    bit_sel_func_names = p.findall(c_text)
    bit_sel_func_names = list(set(bit_sel_func_names))
    # Need bit concat and bit select
    # BIT SELECT
    # uint16_t uintX_15_0(uintX_t)
    for bit_sel_func_name in bit_sel_func_names:
      bit_sel_func_name = bit_sel_func_name.strip("(").strip()
      toks = bit_sel_func_name.split("_")
      
      if len(toks) == 3:
        high = int(toks[1])
        low = int(toks[2])
        in_prefix = toks[0]
        if type_regex == "float":
          in_t = "float"
        else:
          in_t = in_prefix + "_t"
        func_name = in_prefix + "_"+str(high)+"_"+str(low)
        # Catch reverse
        if high < low:
          temp = low
          low = high
          high = temp
        result_width = high - low + 1
        result_t = "uint" + str(result_width) + "_t"
      else:
        # New float_e_m_t_#_#
        high = int(toks[4])
        low = int(toks[5])
        in_t = "_".join(toks[0:4])
        result_width = high - low + 1
        result_t = "uint" + str(result_width) + "_t"
      
      
      text += '''
// BIT SELECT
''' + result_t + " " + bit_sel_func_name+"("+ in_t + ''' x)
{
  //TODO
}
'''
  
  # BIT CONCAT
  # Parse to list of width toks
  bit_concat_func_names = []
  # uint64_uint15
  p = re.compile('u?int[0-9]+_u?int[0-9]+\s?\(')
  bit_concat_func_names = p.findall(c_text)
  bit_concat_func_names = list(set(bit_concat_func_names))
  #uint5_t uint2_uint3(uint2 x, uint3 y) 
  for bit_concat_func_name in bit_concat_func_names:
    bit_concat_func_name = bit_concat_func_name.strip("(").strip()
    toks = bit_concat_func_name.split("_")
    first_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
    second_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
    result_width = first_bit_width + second_bit_width
    result_t = "uint" + str(result_width) + "_t"
    first_in_prefix = toks[0]
    first_in_t = first_in_prefix + "_t"
    second_in_prefix = toks[1]
    second_in_t = second_in_prefix + "_t"
    func_name = first_in_prefix+"_"+second_in_prefix
    text += '''
// BIT CONCAT
''' + result_t + " " + func_name + "(" + first_in_t + " x, " + second_in_t + ''' y)
{
  //TODO
}
'''
  
  # BITS DUP
  # Parse to list of width toks
  bit_dup_func_names = []
  # uint64_5
  p = re.compile('[^_][u?]int[0-9]+_[0-9]+\s?\(')
  bit_dup_func_names = p.findall(c_text)
  bit_dup_func_names = list(set(bit_dup_func_names))
  # Questionable seems OK naming convention?
  # uint(X*15)_t uintX_15(uintX_t)
  # hacky dont match bit bit_sel_func_names
  for bit_dup_func_name in bit_dup_func_names:
    #if not(bit_dup_func_name in bit_sel_func_names):
    bit_dup_func_name = bit_dup_func_name.strip("(").strip()
    toks = bit_dup_func_name.split("_")
    input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
    mult = int(toks[1])
    if mult==0:
      continue
    result_width = input_bit_width * mult     
    result_t = "uint" + str(result_width) + "_t"
    in_prefix = toks[0]
    in_t = in_prefix + "_t"
    func_name = in_prefix + "_"+str(mult)
    text += '''
// BIT DUP
''' + result_t + " " + in_prefix + "_"+str(mult)+"("+ in_t + ''' x)
{
  //TODO
}
'''


  # Rotate left
  # Parse to list of width toks
  rotl_func_names = []
  p = re.compile('[^_]rotl[0-9]+_[0-9]+\s?\(')
  rotl_func_names = p.findall(c_text)
  rotl_func_names = list(set(rotl_func_names))
  for rotl_func_name in rotl_func_names:
    rotl_func_name = rotl_func_name.strip("(").strip()
    #print("rotl_func_name",rotl_func_name)
    toks = rotl_func_name.split("_")
    in_prefix = "uint" + toks[0].replace("rotl","")
    in_t = in_prefix + "_t"
    input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_t)
    rot_amount = int(toks[1])
    result_width = input_bit_width     
    result_t = "uint" + str(result_width) + "_t"
    func_name = "rotl" + str(input_bit_width) + "_" + str(rot_amount)
    text += '''
// BIT ROTL
''' + result_t + " " + func_name +"("+ in_t + ''' x)
{
  //TODO
}
'''

  # Rotate right
  # Parse to list of width toks
  rotr_func_names = []
  p = re.compile('[^_]rotr[0-9]+_[0-9]+\s?\(')
  rotr_func_names = p.findall(c_text)
  rotr_func_names = list(set(rotr_func_names))
  for rotr_func_name in rotr_func_names:
    rotr_func_name = rotr_func_name.strip("(").strip()
    #print("rotr_func_name",rotr_func_name)
    toks = rotr_func_name.split("_")
    in_prefix = "uint" + toks[0].replace("rotr","")
    in_t = in_prefix + "_t"
    input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, in_t)
    rot_amount = int(toks[1])
    result_width = input_bit_width     
    result_t = "uint" + str(result_width) + "_t"
    func_name = "rotr" + str(input_bit_width) + "_" + str(rot_amount)
    text += '''
// BIT ROTR
''' + result_t + " " + func_name +"("+ in_t + ''' x)
{
  //TODO
}
'''

  # Constant index assignment with N bits
  # Otherwise large slv is like ram lookup
  # Parse to list of width toks
  bit_ass_func_names = []
  # uint64_uint15_2(uint64_t in, uint15_t x)  // out = in; out(16 downto 2) = x
  p = re.compile('u?int[0-9]+_uint[0-9]+_[0-9]+\s?\(')
  bit_ass_func_names = p.findall(c_text)
  bit_ass_func_names = list(set(bit_ass_func_names))
  for bit_ass_func_name in bit_ass_func_names:
    bit_ass_func_name = bit_ass_func_name.strip("(").strip()
    toks = bit_ass_func_name.split("_")
    input_bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[0] + "_t")
    assign_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, toks[1] + "_t")
    low_index = int(toks[2])
    high_index = low_index + assign_width - 1
    result_width = input_bit_width    
    in_prefix = toks[0]
    in_t = in_prefix + "_t"
    result_t = in_t
    x_prefix = toks[1]
    x_t = x_prefix + "_t"
    func_name = bit_ass_func_name
    text += '''
// CONST BIT ASSIGNMENT
''' + result_t + " " + func_name +"("+ in_t + ''' inp, ''' + x_t + ''' x)
{
  //TODO
}
'''


  # Float SEM construction
  # Regex search c_text
  # Parse to list of width toks
  float_const_func_names = []
  # float_1_8_23(left_resized);
  for type_regex in ["float"]:
    p = re.compile(type_regex + '_uint[0-9]+_uint[0-9]+\s?\(')
    float_const_func_names = p.findall(c_text)
    float_const_func_names = list(set(float_const_func_names))
    for float_const_func_name in float_const_func_names:
      float_const_func_name = float_const_func_name.strip("(").strip()
      toks = float_const_func_name.split("_")
      s_prefix = "uint1"
      s_t = s_prefix + "_t"
      e_prefix = toks[1]
      e_t = e_prefix + "_t"
      m_prefix = toks[2]
      m_t = m_prefix + "_t"
      result_t = "float_" + str(e_prefix.replace("uint","")) + "_" + str(m_prefix.replace("uint","")) + "_t"
      func_name = float_const_func_name
      text += '''
// FLOAT SEM CONSTRUCT
''' + result_t + " " + float_const_func_name+"("+ s_t + ''' sign, ''' + e_t + ''' exponent, ''' + m_t + ''' mantissa)
{
  //TODO
}
'''

  # Float UINT32 construction ... bleh ... implement unions?
  # Regex search c_text
  # Parse to list of width toks
  float_const_func_names = []
  # float_uint32(in);
  for type_regex in ["float", "float_[0-9]+_[0-9]+_t"]:
    p = re.compile(type_regex + '_uint[0-9]+\s?\(')
    float_const_func_names = p.findall(c_text)
    float_const_func_names = list(set(float_const_func_names))
    for float_const_func_name in float_const_func_names:
      float_const_func_name = float_const_func_name.strip("(").strip()
      toks = float_const_func_name.split("_")
      if len(toks)==2:
        in_prefix = toks[1]
        in_t = in_prefix + "_t"
        result_t = type_regex
      else:
        in_prefix = toks[4]
        in_t = in_prefix + "_t"
        result_t = "float_"+toks[1]+"_"+toks[2]+"_t"
        
      text += '''
// FLOAT UINT32
''' + result_t + " " + float_const_func_name+"("+ in_t + ''' x)
{
  //TODOs
}
'''

  # Float abs, just clear sign bit
  # Regex search c_text
  # Parse to list of width toks
  float_const_func_names = []
  # float_abs(in);
  for type_regex in ["float", "float_[0-9]+_[0-9]+_t"]:
    p = re.compile(type_regex + '_abs\s?\(')
    float_const_func_names = p.findall(c_text)
    float_const_func_names = list(set(float_const_func_names))
    for float_const_func_name in float_const_func_names:
      float_const_func_name = float_const_func_name.strip("(").strip()
      toks = float_const_func_name.split("_")
      if len(toks)==2:
        # float
        in_t = type_regex
        result_t = in_t
      else:
        # float_e_m_t
        in_t = "float_"+toks[1]+"_"+toks[2]+"_t"
        result_t = in_t
        
      text += '''
// FLOAT ABS
''' + result_t + " " + float_const_func_name+"("+ in_t + ''' x)
{
  //TODO
}
'''

  # Float sign, just return sign bit
  # Regex search c_text
  float_const_func_names = []
  # float_sign(in);
  for type_regex in ["float", "float_[0-9]+_[0-9]+_t"]:
    p = re.compile(type_regex + '_sign\s?\(')
    float_const_func_names = p.findall(c_text)
    float_const_func_names = list(set(float_const_func_names))
    for float_const_func_name in float_const_func_names:
      float_const_func_name = float_const_func_name.strip("(").strip()
      toks = float_const_func_name.split("_")
      if len(toks)==2:
        # float
        in_t = type_regex
      else:
        # float_e_m_t
        in_t = "float_"+toks[1]+"_"+toks[2]+"_t"
        
      text += '''
// FLOAT SIGN
''' + "uint1_t" + " " + float_const_func_name+"("+ in_t + ''' x)
{
  //TODO
}
'''


  # Byte swap, with same name as real C func
  # Parse to list of width toks
  bswap_func_names = []
  p = re.compile('bswap_[0-9]+\s?\(')
  bswap_func_names = p.findall(c_text)
  bswap_func_names = list(set(bswap_func_names))
  for bswap_func_name in bswap_func_names:
    bswap_func_name = bswap_func_name.strip("(").strip()
    toks = bswap_func_name.split("_")
    input_bit_width = int(toks[1])
    result_width = input_bit_width    
    result_t = "uint" + str(result_width) + "_t"
    in_prefix = "uint" + str(input_bit_width)
    in_t = in_prefix + "_t"
    func_name = bswap_func_name
    text += '''
// BYTE SWAP
''' + result_t + " " + func_name + "("+ in_t + ''' x)
{
  //TODO
}
'''


  # Array to unsigned
  #uint1024_t uint8_array128_be/le(uint8_t x[128])
  # Need big and little endian
  # Dont do casting since endianess makes everyone sad
  # C doesnt support casting like that anyway
  array_to_unsigned_func_names = []
  p = re.compile('uint[0-9]+_array[0-9]+_(?:be|le)\s?\(')
  array_to_unsigned_func_names = p.findall(c_text)
  array_to_unsigned_func_names = list(set(array_to_unsigned_func_names))
  #print "array_to_unsigned_func_names",array_to_unsigned_func_names
  #if len(array_to_unsigned_func_names) > 0:
  # print "c_text"
  for array_to_unsigned_func_name in array_to_unsigned_func_names:
    array_to_unsigned_func_name = array_to_unsigned_func_name.strip("(").strip()
    toks = array_to_unsigned_func_name.split("_")
    elem_width = int(toks[0].replace("uint",""))
    elem_t = toks[0] + "_t"
    dim = int(toks[1].replace("array",""))
    result_width = elem_width * dim   
    result_t = "uint" + str(result_width) + "_t"
    func_name = array_to_unsigned_func_name
    text += '''
// ARRAY TO UNSIGNED
''' + result_t + " " + func_name + "("+ elem_t + ''' x[''' + str(dim) + '''])
{
  //TODO
}
'''   
  
  # unsigned to array
  # uint8_t[128] be/le_uint8_array128(uint1024_t 
  # Dont do for now since not needed yet and involves dumb return of array in struct
  # Want uint8*4_t[N/4] = uint8_arrayN_by_4_le(uint8_t x[N]) but can be done with unsigned to/from array 
  # ITS TIME TO BE SHITTY?
  

  if text != "":
    # Ok had some code, include headers
    text = header_text + text

    #print("BIT_MANIP_HEADER_FILE")
    #print(text,flush=True)
    
    #Just bit manip for now
    outfile = BIT_MANIP_HEADER_FILE
    # "GET_SW_FUNC_NAME_LOGIC_LOOKUP outfile",outfile
    
    # Parse the c doe to logic lookup
    parser_state_copy = copy.copy(parser_state)  # was DEEPCOPY
    # Keep everything except logic stuff
    parser_state_copy.FuncLogicLookupTable=dict() #dict[func_name]=Logic() instance with just func info
    parser_state_copy.LogicInstLookupTable=dict() #dict[inst_name]=Logic() instance in full
    parser_state_copy.existing_logic = C_TO_LOGIC.Logic() # Temp working copy of logic ? idk it should work
    parse_body = False # SINCE BIT MANIP IGNORES SW IMPLEMENTATION
    FuncLogicLookupTable = C_TO_LOGIC.GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, outfile, parser_state_copy, parse_body)
    
    # All of these funcs are vhdl funcs
    for func_name in FuncLogicLookupTable:
      FuncLogicLookupTable[func_name].is_vhdl_func = True   
    
    return FuncLogicLookupTable
  else:
    # No code, no funcs
    return dict()


def GENERATE_INT_N_HEADERS(max_bit_width=2048):
  # Do signed and unsigned two files
  for u in ["","u"]:
    text = "#pragma once\n"
    text += "#include <stdint.h>\n"
    min_width = 1
    #if u=="":
    # min_width = 2
    for bitwidth in range(min_width,max_bit_width+1):
      standard_type = u + "int8_t"
      if bitwidth > 8:
        standard_type = u + "int16_t"
      if bitwidth > 16:
        standard_type = u + "int32_t"
      if bitwidth > 32:
        standard_type = u + "int64_t"
        
      the_type = u + "int" + str(bitwidth) + "_t"
      
      # Comment out standard types
      if the_type == standard_type:
        text += "//"
      
      text += "typedef " + standard_type + " " + the_type + ";\n"
  
    #print "GENERATE_INT_N_HEADERS"
    #print text
  
    filename = u + "intN_t.h"
    f=open(filename,"w")
    f.write(text)
    f.close()
    
def GET_CAST_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state):
  input_wire = partially_complete_logic.inputs[0]
  in_t = partially_complete_logic.wire_to_c_type[input_wire]
  output_wire = partially_complete_logic.outputs[0]
  out_t = partially_complete_logic.wire_to_c_type[output_wire]
  if C_TO_LOGIC.C_TYPE_IS_FLOAT_TYPE(in_t) and VHDL.C_TYPE_IS_INT_N(out_t):
    return GET_CAST_FLOAT_TO_INT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state)
  elif VHDL.C_TYPES_ARE_INTEGERS([in_t]) and C_TO_LOGIC.C_TYPE_IS_FLOAT_TYPE(out_t):
    return GET_CAST_INT_UINT_TO_FLOAT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state)
  else:
    print("Implement more casting: Easy/Lucky/Free Bright Eyes")
    print(in_t, out_t,partially_complete_logic.c_ast_node.coord)
    sys.exit(-1)
  
def GET_UNARY_OP_NEGATE_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state):
  input_wire = partially_complete_logic.inputs[0]
  in_t = partially_complete_logic.wire_to_c_type[input_wire]
  if VHDL.C_TYPES_ARE_INTEGERS([in_t]):
    return GET_UNARY_OP_NEGATE_INT_UINT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state)
  else:
    print("Implement more negate: ABBA - Dancing Queen")
    print(in_t, out_t,partially_complete_logic.c_ast_node.coord)
    sys.exit(-1)
  
  
def GET_UNARY_OP_NEGATE_INT_UINT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state):
  input_wire = partially_complete_logic.inputs[0]
  in_t = partially_complete_logic.wire_to_c_type[input_wire]
  in_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(in_t)
  is_int = VHDL.C_TYPE_IS_INT_N(in_t) 
  result_t = "int" + str(in_width+1) + "_t"
  result_uint_t = "uint" + str(in_width+1) + "_t"

  text = ""
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
// Negate
''' + result_t + " " + partially_complete_logic.func_name+"("+ in_t + ''' expr)
{
  // Twos comp
  
  ''' + result_uint_t + ''' x_wide;
  x_wide = expr;
  
  ''' + result_uint_t + ''' x_wide_neg;
  x_wide_neg = !x_wide;
  
  ''' + result_uint_t + ''' x_neg_wide_plus1;
  x_neg_wide_plus1 = x_wide_neg + 1;
  
  ''' + result_t + ''' rv;
  rv = x_neg_wide_plus1;
  
  return rv;
}
'''

  return text
  
  
def GET_CAST_INT_UINT_TO_FLOAT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state):
  # Int to float
  input_wire = partially_complete_logic.inputs[0]
  in_t = partially_complete_logic.wire_to_c_type[input_wire]
  input_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(in_t)
  is_int = VHDL.C_TYPE_IS_INT_N(in_t) 
  output_wire = partially_complete_logic.outputs[0]
  out_t = partially_complete_logic.wire_to_c_type[output_wire]
  fp_t = out_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  text = ""
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MATH_HEADER_FILE + '''"
#include "float_e_m_t.h"

// CAST
''' + out_t + " " + partially_complete_logic.func_name+"("+ in_t + ''' rhs)
{
  // Building SEM to return
  ''' + mantissa_t + ''' mantissa;
  ''' + exponent_t + ''' biased_exponent;
  ''' + sign_t + ''' sign;
  
  // Special case zero
  ''' + out_t + ''' rv;
  if(rhs==0)
  {
    rv = float_''' + exponent_t_prefix + "_" + mantissa_t_prefix + '''(0,0,0);
  }
  else
  {
  '''
  
  unsigned_t = "uint" + str(input_width) + "_t"
  if is_int:
    # Integer
    text += ''' 
    // Record sign
    sign = int''' + str(input_width) + "_" + str(input_width-1) + "_" + str(input_width-1) + '''(rhs);
    // Take abs value
  ''' + unsigned_t + ''' unsigned_rhs;
    unsigned_rhs = int''' + str(input_width) + '''_abs(rhs);\n'''
  else:
    # Unsigned
    text += ''' 
    // Record sign
    sign = 0;
    // Abs value is just rhs
    ''' + unsigned_t + ''' unsigned_rhs;
    unsigned_rhs = rhs;\n'''
  
  
  # Count leading zeros
  num_zeros_bits = int(math.ceil(math.log(input_width+1,2)))
  num_zeros_t = "uint" + str(num_zeros_bits) + "_t"
  text += '''
    // Count leading zeros
    ''' + num_zeros_t + ''' num_zeros;
    num_zeros = count0s''' + "_uint" + str(input_width) + '''(unsigned_rhs);'''
  
  
  # Shift all the way left plus 1 to drop upper most bit
  shift_t = "uint" + str(num_zeros_bits+1) + "_t"
  text += '''
    // Shift all the way left plus 1 to drop upper most bit
    ''' + shift_t + ''' shift;
    shift = num_zeros + 1;
    ''' + unsigned_t + ''' shifted_unsigned_rhs;
    shifted_unsigned_rhs = unsigned_rhs << shift;'''
  
  
  # Might need to append zeros to right if rhs is smaller than mantissa
  if input_width < mantissa_width:
    # Increase width
    maybe_resized_width = mantissa_width
    maybe_resized_rhs_t = "uint" + str(maybe_resized_width) + "_t"
    # Pad right with zeros
    pad_size = mantissa_width - input_width
    text += '''
      // Pad right with zeros
      ''' + maybe_resized_rhs_t + ''' maybe_resized_rhs;
      maybe_resized_rhs = uint''' + str(input_width) + "_uint" + str(pad_size) + '''(shifted_unsigned_rhs, 0);'''
  else:
    # No resize
    maybe_resized_width = input_width
    maybe_resized_rhs_t = "uint" + str(maybe_resized_width) + "_t"
    text += '''
      // No resize
      ''' + maybe_resized_rhs_t + ''' maybe_resized_rhs;
      maybe_resized_rhs = shifted_unsigned_rhs;'''
    
  # Take mantissa from upper bits
  top_index = maybe_resized_width - 1
  bottom_index = top_index - mantissa_width + 1
  text += '''
    // Take mantissa from upper bits
    mantissa = uint''' + str(maybe_resized_width) + "_" + str(top_index) + "_" + str(bottom_index) + '''(maybe_resized_rhs);'''
  
  # Exponent depends on position of leading zero in original number
  # Use that to calculate bit width needed
  text += '''
    // Exponent depends on shift
    // All zeros = leading zeros = width, shift=width+1
    if(shift == ''' + str(input_width+1) +''')
    {
      biased_exponent = 0;
    }
    else
    {
      // Normal non zero case
      ''' + exponent_t + ''' exponent;
      exponent = ''' + str(input_width) + ''' - shift;
      // Add bias
      biased_exponent = exponent + ''' + str(exponent_bias) + ''';
    }'''
  
  # Construct float to return
  text += '''
    rv = float_''' + exponent_t_prefix + "_" + mantissa_t_prefix + '''(sign, biased_exponent, mantissa);
  }
  
  return rv;
}'''

  #print(text)
  return text
  
  
  
  
def GET_CAST_FLOAT_TO_INT_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state):
  func_name = partially_complete_logic.func_name
  
  # Float to int
  input_wire = partially_complete_logic.inputs[0]
  in_t = partially_complete_logic.wire_to_c_type[input_wire]
  output_wire = partially_complete_logic.outputs[0]
  out_t = partially_complete_logic.wire_to_c_type[output_wire]    
  fp_t = in_t  
  # I HATE TWOS COMPLEMENT   # A Day In The Life - The Beatles
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  text = ""
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MATH_HEADER_FILE + '''"
#include "float_e_m_t.h"

// CAST
''' + out_t + " " + func_name+"("+ in_t + ''' rhs)
{
  // Break into SEM
  ''' + mantissa_t + ''' mantissa;
  mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(rhs);
  ''' + exponent_t + ''' biased_exponent;
  biased_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(rhs);
  ''' + sign_t + ''' sign;
  sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(rhs);
  
  ''' + out_t + ''' rv;
  // Special case zero
  if((mantissa==0) & (biased_exponent==0))
  {
    rv = 0;
  }
  else
  {
  '''
  
  # Get real unbiased exponent
  signed_exponent_t = "int" + str(exponent_width_plus1) + "_t"
  unbiased_exponent_t = "int" + str(exponent_width) + "_t"
  text += '''
    ''' + signed_exponent_t + ''' signed_biased_exponent;
    signed_biased_exponent = biased_exponent;
    ''' + unbiased_exponent_t + ''' unbiased_exponent;
    unbiased_exponent = signed_biased_exponent - ''' + str(exponent_bias) + ''';'''
  
  # Append the 1 in front of the manitissa
  mantissa_width_plus_1 = mantissa_width+1
  mantissa_normalized_t = "uint" + str(mantissa_width_plus_1) + "_t"
  text += '''
    ''' + mantissa_normalized_t + ''' mantissa_normalized;
    mantissa_normalized = uint1_''' + mantissa_t_prefix + '''(1, mantissa);'''
  
  # 24th bit is 1 so need to include that when shifting
  # Output width of cast limits how far we should bother shifting before overflowing into undefined output
  # Casting to int so actual unsigned width is less
  out_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(out_t)
  unsigned_width = out_width - 1
  total_shift_max = unsigned_width
  shift_bit_size = int(math.ceil(math.log(total_shift_max+1,2.0)))
  shift_t = "uint" + str(shift_bit_size) + "_t"
  interm_size = mantissa_width_plus_1 + unsigned_width
  interm_prefix = "uint" + str(interm_size)
  interm_t = interm_prefix + "_t"
  # Extend mantissa with zeros
  text += '''
    ''' + interm_t + ''' interm;
    interm = mantissa_normalized;'''
  # Shift mantissa with hidden bit if greater or equal to 0 and up a limit
  text += '''
    if( (unbiased_exponent >= 0) & (unbiased_exponent <= ''' + str(total_shift_max) + ''') )
    {
      ''' + shift_t + ''' shift;
      shift = unbiased_exponent;
      interm = interm << shift;
    }else if(unbiased_exponent < 0) // Round to zero?
    {
      interm = 0;
    }'''
  
  # Take result from top of shifted interm mantissa
  top_index = interm_size - 1
  bottom_index = mantissa_width
  unsigned_result_prefix = "uint" + str(unsigned_width)
  unsigned_result_t = unsigned_result_prefix  + "_t"
  text += '''
    ''' + unsigned_result_t + ''' unsigned_result;
    unsigned_result = ''' + interm_prefix + "_" + str(top_index) + "_" + str(bottom_index) + '''(interm);'''
  
  # Negate if necessary
  text += '''
  
    rv = unsigned_result;
    if(sign)
    {
      rv = ''' + unsigned_result_prefix + '''_negate(unsigned_result);
    }
  
  }
  
  return rv;
}
'''

  return text
  
  
    
### Ahh fuck taking the easy way 
# Copying implemetnation from     GET_VAR_REF_ASSIGN_C_CODE
# Might actually be worth it
def GET_VAR_REF_RD_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, containing_func_logic, out_dir, parser_state):
  #@@@@ Need to solve can't reutnr arry and any type NMUX name problem (struct_t_muxN name?)
  ## Fuck need to put array in struct
  # Then need to allow cast from struct wray to array type in VHDL?


  ref_toks = containing_func_logic.ref_submodule_instance_to_ref_toks[partially_complete_logic_local_inst_name]
  orig_var_name = ref_toks[0]
  
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  
  func_c_name = partially_complete_logic.func_name
  
  
  # First need to assign ref tokens into type matching BASE
  # Get base var name + type from any of the inputs 

  #base_c_type = containing_func_logic.wire_to_c_type[orig_var_name_inst_name]
  base_c_type = containing_func_logic.wire_to_c_type[orig_var_name]
  base_vhdl_type = VHDL.C_TYPE_STR_TO_VHDL_TYPE_STR(base_c_type,parser_state) # Structs handled and have same name as C types 
  
  
  text = ""

  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MATH_HEADER_FILE + '''"
'''
  # Do type defs for input structs and output array (if output is array)
  # And base type too
  for input_wire in partially_complete_logic.inputs:
    input_t = partially_complete_logic.wire_to_c_type[input_wire]
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(input_t, parser_state):
      text += '''typedef uint8_t ''' + input_t + "; // FUCK\n"
  if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(output_t, parser_state):
    text += '''typedef uint8_t ''' + output_t + "; // FUCK\n"
  if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(base_c_type, parser_state):
    text += '''typedef uint8_t ''' + base_c_type + "; // FUCK\n"

  text += '''

// Var ref read
'''

  text += output_t + ''' ''' + func_c_name + '''('''
  
  # Inputs
  for input_wire in partially_complete_logic.inputs:
    input_c_name = input_wire 
    input_t = partially_complete_logic.wire_to_c_type[input_wire]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(input_t):
      # Dimensions go after variable name
      elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_t)
      text += elem_type + " " + input_c_name
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ", "      
    else:
      # Regular non array
      text += input_t + " " + input_c_name + ", "
  
  
  # Remove last ","
  text = text.rstrip(", ")
  # End line
  text += ''')
{
  '''
  
  # Assign ref toks into base type
  if C_TO_LOGIC.C_TYPE_IS_ARRAY(base_c_type):
    # Dimensions go after variable name
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(base_c_type)
    text += elem_type + " base"
    for dim in dims:
      text += "[" + str(dim) + "]"
    text += ";\n"     
  else:
    # Regular non array
    text += base_c_type + " base;\n"
  
  
  text += " // Assign ref toks to base\n"
  # Do ref toks
  ref_toks_i = 0
  #print "containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks"
  #print containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks
  driven_ref_toks_list = containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks[partially_complete_logic_local_inst_name]
  for input_wire in partially_complete_logic.inputs: 
    if "var_dim_" not in input_wire:
      input_c_name = input_wire 
      # Assign to base      
      # Remove base variable
      
      # ref toks not from port name
      driven_ref_toks = driven_ref_toks_list[ref_toks_i]
      ref_toks_i += 1
      
      # Expand to constant refs
      expanded_ref_tok_list = C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS(driven_ref_toks, partially_complete_logic.c_ast_node, parser_state)
      for expanded_ref_toks in expanded_ref_tok_list:
        # Make str
        lhs = "base"
        for expanded_ref_tok in expanded_ref_toks[1:]: # Skip base var name
          if type(expanded_ref_tok) == int:
            lhs += "[" + str(expanded_ref_tok) + "]"
          elif type(expanded_ref_tok) == str:
            lhs += "." + expanded_ref_tok
          else:
            print("WTF var ref input wire as input ref tok to var ref??", expanded_ref_tok)
            sys.exit(-1)
        

        # Do assingment
        text += " " + lhs + " = " + input_c_name + ";\n"
      
  # Then make a bunch of constant references  
  # one for each possible i,j,k variable dimension
  # Get var dimension types
  ## BBAAAH parser_state.existing_logic needs to be containing logic
  parser_state_as_container = copy.copy(parser_state)
  parser_state_as_container.existing_logic = containing_func_logic
  var_dim_ref_tok_indices, var_dims, var_dim_types = C_TO_LOGIC.GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container)
  var_dim_input_wires = []
  for input_wire in partially_complete_logic.inputs: 
    if "var_dim_" in input_wire:
      var_dim_input_wires.append(input_wire)
  
  
  # Make multiple constant references into base
  text += " // Make multiple constant references into base\n"
  const_refs = ["ref"]
  # Build variables
  #print "var_dim_input_wires",var_dim_input_wires
  for var_dim_i in range(0, len(var_dim_input_wires)):
    c_type = var_dim_types[var_dim_i]
    var_dim_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
    var_dim_size = var_dims[var_dim_i]
    #print "var_dim_width",var_dim_width
    #print "var_dim_size",var_dim_size
    new_const_refs = []
    for const_ref in const_refs:
      for dim_val in range(0,var_dim_size):
        new_const_ref = const_ref + "_" + str(dim_val)
        new_const_refs.append(new_const_ref)
    # Next iter
    const_refs = new_const_refs[:]
  # Assign them   
  for const_ref in const_refs:
    # Declare and begin assignment
    text += " " + output_t + " " + const_ref + ";\n"
    if C_TYPE_IS_ARRAY_STRUCT(output_t, parser_state):
      text += " " + const_ref + ".data = base"
    else:
      text += " " + const_ref + " = base"
    
    # Write out full ref toks
    toks = const_ref.split("_")
    indices = toks[1:]
    
    # Loop over ref toks and insert variable ref values
    var_dim_i = 0
    for ref_tok in ref_toks[1:]:# Skip base var name
      if isinstance(ref_tok, c_ast.Node):
        text += "[" + str(indices[var_dim_i]) + "]"
        var_dim_i += 1
      elif type(ref_tok) == int:
        text += "[" + str(ref_tok) + "]"
      elif type(ref_tok) == str:
        text += "." + ref_tok
      else:
        print("Why ref tok?", ref_tok)
        sys.exit(-1)
    
    text += ";\n"
  
  
  # Is making simple sel = [i][j][k] overkill?
  # Even an N mux per dimension still has muxes for extra bits...
  # Can't avoid ???
  # Easy for now??
  # Sel width is sum of var dims
  sel_width = 0
  var_dim_input_widths = []
  for var_dim_input_wire in var_dim_input_wires:
    var_dim_c_type = partially_complete_logic.wire_to_c_type[var_dim_input_wire]
    var_dim_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, var_dim_c_type)
    sel_width += var_dim_width
    var_dim_input_widths.append(var_dim_width)
  sel_prefix = "uint" + str(sel_width)
  sel_t = sel_prefix + "_t"
  sel_size = int(pow(2,sel_width))
  
  
  # Loop to concat sel
  text += " // Form select value\n"
  
  # Initial copy of first dim
  input_wire = var_dim_input_wires[0]
  text += " " + sel_t + " sel;\n"
  
  # Need initial value or pipelinemap get fuckled
  text += " " + "sel = 0;\n"  
  
  # Assign into sel
  index = 0
  for var_dim_i in range(len(var_dim_input_wires)-1, -1, -1):
    c_type = var_dim_types[var_dim_i]
    prefix = c_type.strip("_t")
    var_dim_input_wire = var_dim_input_wires[var_dim_i]
    input_width = var_dim_input_widths[var_dim_i]
    input_c_name = var_dim_input_wire
    text += " sel = " + sel_prefix + "_" + prefix + "_" + str(index) + "( sel, " + input_c_name + ");\n"
    index += input_width
  
  
  # Loop over each const ref
  # Call nmux
  text += " // Do nmux\n"  #$BLEGH TODO make generic mux functions use full type name
  output_prefix = output_t
  # Dumb check for uint
  toks = output_t.strip("_t").split("int")
  if len(toks) == 2 and (toks[0] == "" or toks[0] == "u") and toks[1].isdigit():
    output_prefix = output_t.replace("_t","")
    
  text += " " + output_t + " rv;\n"
  text += " rv = " +  output_prefix + "_mux" + str(sel_size) + "("
  # Sel
  text += "sel,\n"
  # Inputs
  for sel_val in range(0, sel_size):
    var_dim_values = []
    index = 0
    for var_dim_i in range(0, len(var_dim_input_wires)):
      input_width = var_dim_input_widths[var_dim_i]
      end_index = index + input_width - 1
      #print "index",index
      #print "end_index",end_index
      
      # get number bit range sel[end:start]
      #dim_val = int(bin(sel_val).replace("0b","").zfill(sel_width)[::-1][index:end_index+1][::-1],2)
      dim_val = int(bin(sel_val).replace("0b","").zfill(sel_width)[index:end_index+1],2)
      var_dim_values.append(dim_val)
      index += input_width
      #print "sel_val",sel_val
      #print "dim_val",dim_val
      #
    
    # Use ref variable if all var dims are within correct size, otherwise 0
    valid_dims = True
    for var_dim_i in range(0, len(var_dim_input_wires)):
      var_dim_value = var_dim_values[var_dim_i]
      actual_dim_size = var_dims[var_dim_i]
      if var_dim_value >= actual_dim_size:
        valid_dims = False
    if valid_dims:
      # Build ref var str
      ref_sel = "ref"
      #for var_dim_value in reversed(var_dim_values):
      for var_dim_value in var_dim_values:
        ref_sel += "_" + str(var_dim_value)
    else:
      # Hacky allow unfilled to be filled in w/ prev ref? 
      #ref_sel = "0"
      pass
      
    # Use this ref_sel in nmux
    text += "     " + ref_sel + ",\n"
    
  # Remove last comma
  text = text.strip(",\n");
  
  text += "\n );\n"
  
  
  text += '''
  return rv;
}'''


  #print("GET_VAR_REF_RD_C_CODE text")
  #print(text)
  #sys.exit(-1)
  
  return text

def GET_VAR_REF_ASSIGN_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, containing_func_logic, out_dir, parser_state):
  # Each element gets a single mux comapring == sel
  # Old code was bloated in muxing multiple copies of huge array

  # Input ref toks can be base value so need to start with base type
  lhs_ref_toks = containing_func_logic.ref_submodule_instance_to_ref_toks[partially_complete_logic_local_inst_name]
  orig_var_name = lhs_ref_toks[0]
  base_c_type = containing_func_logic.wire_to_c_type[orig_var_name]
  
  
  #print lhs_ref_toks
  #print orig_var_name, "base_c_type",base_c_type
  #sys.exit(-1)
  


  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  #output_t_c_name = output_t.replace("[","_").replace("]","_").replace("__","_")
  func_c_name = partially_complete_logic.func_name #.replace("[","_").replace("]","_").replace("__","_")
  
  text = ""
  
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MATH_HEADER_FILE + '''"
'''
  # Do type defs for input structs and output array (if output is array)
  # And base type too
  for input_wire in partially_complete_logic.inputs:
    input_t = partially_complete_logic.wire_to_c_type[input_wire]
    if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(input_t, parser_state):
      text += '''typedef uint8_t ''' + input_t + "; // FUCK\n"
  if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(output_t, parser_state):
    text += '''typedef uint8_t ''' + output_t + "; // FUCK\n"
  if C_TYPE_NEEDS_INTERNAL_FAKE_TYPEDEF(base_c_type, parser_state):
    text += '''typedef uint8_t ''' + base_c_type + "; // FUCK\n"

  text += '''
// Var ref assignment\n'''

  # FUNC DEF
  text += output_t + ''' ''' + func_c_name + '''('''
  
  # Inputs
  for input_wire in partially_complete_logic.inputs:
    input_c_name = input_wire 
    input_t = partially_complete_logic.wire_to_c_type[input_wire]
    if C_TO_LOGIC.C_TYPE_IS_ARRAY(input_t):
      # Dimensions go after variable name
      elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_t)
      text += elem_type + " " + input_c_name
      for dim in dims:
        text += "[" + str(dim) + "]"
      text += ", "      
    else:
      # Regular non array
      text += input_t + " " + input_c_name + ", "
  
  
  # Remove last ","
  text = text.rstrip(", ")
  # End line
  text += ''')
{
  '''
  
  # First need to assign ref tokens into type matching return
  # Assign ref toks into base type
  if C_TO_LOGIC.C_TYPE_IS_ARRAY(base_c_type):
    # Dimensions go after variable name
    elem_type, dims = C_TO_LOGIC.C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(base_c_type)
    text += elem_type + " base"
    for dim in dims:
      text += "[" + str(dim) + "]"
    text += ";\n"     
  else:
    # Regular non array
    text += base_c_type + " base;\n"
  
  
  text += " // Assign ref toks to base\n"
  # Do ref toks
  driven_ref_toks_list = containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks[partially_complete_logic_local_inst_name]
  ref_toks_i = 0
  for input_wire in partially_complete_logic.inputs[1:]: 
    if "var_dim_" not in input_wire:
      input_c_name = input_wire 
      
      # ref toks not from port name
      driven_ref_toks = driven_ref_toks_list[ref_toks_i]
      ref_toks_i += 1
      
      # Expand to constant refs
      expanded_ref_tok_list = C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS(driven_ref_toks, partially_complete_logic.c_ast_node, parser_state)
      for expanded_ref_toks in expanded_ref_tok_list:
        # Make str
        lhs = "base"
        for expanded_ref_tok in expanded_ref_toks[1:]: # Skip base var name:
          if type(expanded_ref_tok) == int:
            lhs += "[" + str(expanded_ref_tok) + "]"
          elif type(expanded_ref_tok) == str:
            lhs += "." + expanded_ref_tok
          else:
            print("WTF var ref input wire as input ref tok to var ref??", expanded_ref_tok)
            sys.exit(-1)
        
        # Do assignment
        text += " " + lhs + " = " + input_c_name + ";\n"
      
  # Then make a bunch of copies of rv, one for each possible i,j,k variable dimension
  # Get var dimension types
  var_dim_types = []
  var_dim_input_wires = []
  for input_wire in partially_complete_logic.inputs[1:]: 
    if "var_dim_" in input_wire:
      c_type = partially_complete_logic.wire_to_c_type[input_wire]
      var_dim_types.append(c_type)
      var_dim_input_wires.append(input_wire)
  
  
  text += " // Copy base into rv\n"
  text += " " + output_t + " rv;\n"
  ## BBAAAH parser_state.existing_logic needs to be containing logic
  # Copy parser state since not intending to change existing logic in this func
  parser_state_as_container = copy.copy(parser_state)
  parser_state_as_container.existing_logic = containing_func_logic
  # Need to assign base into rv output
  # Output type is just N dimension array of the element type 
  # N dims are variable ref toks
  # Loop over all the variable dimensions
  # Do so with expanded ref toks
  var_dim_ref_tok_indices, var_dims, var_dim_iter_types = C_TO_LOGIC.GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(lhs_ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container)
  expanded_ref_tok_list = C_TO_LOGIC.EXPAND_REF_TOKS_OR_STRS(lhs_ref_toks, partially_complete_logic.c_ast_node, parser_state_as_container)
  for expanded_ref_toks in expanded_ref_tok_list:
    # LHS is just variable ref dims
    lhs = "rv.data"
    for index in var_dim_ref_tok_indices:
      lhs += "[" + str(expanded_ref_toks[index]) + "]"
    
    # RHS is full ref toks
    rhs = "base"
    for expanded_ref_tok in expanded_ref_toks[1:]: # Skip base var name
      if type(expanded_ref_tok) == int:
        rhs += "[" + str(expanded_ref_tok) + "]"
      elif type(expanded_ref_tok) == str:
        rhs += "." + expanded_ref_tok
      else:
        print("WTF var ref input wire as input ref tok to var ref?? rhs", expanded_ref_tok)
        sys.exit(-1)
        
    text += " " + lhs + " = " + rhs + ";\n" 
    
    
    
  # Do a mux for each element
  text += " // Do mux for each element\n"
  for expanded_ref_toks in expanded_ref_tok_list:
    text += " " + "if(\n"
    # Do each var dim
    for var_dim_i in range(0, len(var_dim_ref_tok_indices)):
      index = var_dim_ref_tok_indices[var_dim_i]
      text += "   (" + "var_dim_" + str(var_dim_i) + " == " + str(expanded_ref_toks[index]) + ") &\n"
    # Remove last and
    text = text[:-len("&\n")]
    # End if ()
    text += "\n )\n"
    text += " {\n"
    
    # Build lhs   
    # LHS is just variable ref dims
    lhs = "rv.data"
    for var_dim_i in range(0, len(var_dim_ref_tok_indices)):
      index = var_dim_ref_tok_indices[var_dim_i]
      lhs += "[" + str(expanded_ref_toks[index]) + "]"
    
    # Assign elem to it
    text += "   " + lhs + " = elem_val;\n"
    text += " }\n"
    
  
  
  text += '''
  return rv;
}'''


  #print "GET_VAR_REF_ASSIGN_C_CODE text"
  #print text
  #sys.exit(-1)
  
  return text

def GET_BIN_OP_SR_FLOAT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,output_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,output_t]):
    print('''"left_t != "float" or  output_t != "float" for sr ''')
    sys.exit(-1)
  fp_t = left_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  text = ""
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float shift right div pow2
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // LEFT
  uint''' + str(mantissa_width) + '''_t left_mantissa;  
  left_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  uint''' + str(exponent_width) + '''_t left_exponent;
  left_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  uint1_t left_sign;
  left_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  
  // Declare the output portions
  uint''' + str(mantissa_width) + '''_t z_mantissa;
  uint''' + str(exponent_width) + '''_t z_exponent;
  uint1_t z_sign;
  z_sign = left_sign;
  z_exponent = 0;
  // Div by pow2 with sub to exponent
  if(left_exponent != 0) // Zero divided by anything still zero
  {
    z_exponent = left_exponent - right;
  }
  z_mantissa = left_mantissa;
  // Assemble output  
  return float_uint'''+str(exponent_width) + "_uint" + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

  #print "C CODE"
  #print text

  return text  

def GET_BIN_OP_SL_FLOAT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,output_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,output_t]):
    print('''"left_t != "float" or  output_t != "float" for sl ''')
    sys.exit(-1)
  fp_t = left_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  text = ""
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float shift left mult pow2
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // LEFT
  uint''' + str(mantissa_width) + '''_t left_mantissa;  
  left_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  uint''' + str(exponent_width) + '''_t left_exponent;
  left_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  uint1_t left_sign;
  left_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  
  // Declare the output portions
  uint''' + str(mantissa_width) + '''_t z_mantissa;
  uint''' + str(exponent_width) + '''_t z_exponent;
  uint1_t z_sign;
  z_sign = left_sign;
  z_exponent = 0;
  // mult by pow2 with add to exponent
  if(left_exponent != 0) // Zero times anything stays zero
  {
    z_exponent = left_exponent + right; 
  }
  z_mantissa = left_mantissa;
  // Assemble output  
  return float_uint'''+str(exponent_width) + "_uint" + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

  #print "C CODE"
  #print text

  return text
  
    
def GET_BIN_OP_SR_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  
  # THIS CODE ASSUMES NON CONST/ is dumb to use as const
  left_input_wire = partially_complete_logic_local_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[0]
  right_input_wire = partially_complete_logic_local_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[1]
  left_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(left_input_wire, containing_func_logic)
  right_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(right_input_wire, containing_func_logic)
  
  if VHDL.WIRES_ARE_INT_N([partially_complete_logic.inputs[0]], partially_complete_logic) or VHDL.WIRES_ARE_UINT_N([partially_complete_logic.inputs[0]], partially_complete_logic):
    if not(right_const_driving_wire is None):
      print("SW defined constant shift right?",partially_complete_logic.c_ast_node.coord)
      sys.exit(-1)
    return GET_BIN_OP_SR_INT_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
  elif C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t]):
    return GET_BIN_OP_SR_FLOAT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
  else:
    print("GET_BIN_OP_SR_C_CODE what types!?",partially_complete_logic.c_ast_node.coord)
    sys.exit(-1)
    
def GET_BIN_OP_SL_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  
  # THIS CODE ASSUMES NON CONST/ is dumb to use as const
  left_input_wire = partially_complete_logic_local_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[0]
  right_input_wire = partially_complete_logic_local_inst_name + C_TO_LOGIC.SUBMODULE_MARKER + partially_complete_logic.inputs[1]
  left_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(left_input_wire, containing_func_logic)
  right_const_driving_wire = C_TO_LOGIC.FIND_CONST_DRIVING_WIRE(right_input_wire, containing_func_logic)
  
  if VHDL.WIRES_ARE_INT_N([partially_complete_logic.inputs[0]], partially_complete_logic) or VHDL.WIRES_ARE_UINT_N([partially_complete_logic.inputs[0]], partially_complete_logic):
    if not(right_const_driving_wire is None):
      print("SW defined constant shift left?",partially_complete_logic.c_ast_node.coord)
      sys.exit(-1)
    return GET_BIN_OP_SL_INT_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
  elif C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t]):
    return GET_BIN_OP_SL_FLOAT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state)
  else:
    print("GET_BIN_OP_SL_C_CODE what types!?",partially_complete_logic.c_ast_node.coord)
    sys.exit(-1)
      
def GET_BIN_OP_PLUS_C_CODE(partially_complete_logic, out_dir):
  # If one of inputs is signed int then other input will be bit extended to include positive sign bit
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
  else:
    print("GET_BIN_OP_PLUS_C_CODE Only plus between float for now!")
    sys.exit(-1)

def GET_BIN_OP_MINUS_C_CODE(partially_complete_logic, out_dir):
  # If one of inputs is signed int then other input will be bit extended to include positive sign bit
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir)
  else:
    print("GET_BIN_OP_MINUS_C_CODE Only sub between float for now!")
    sys.exit(-1)

def GET_BIN_OP_MOD_C_CODE(partially_complete_logic, out_dir):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  #if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
  # return GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir)
  #el
  if C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_MOD_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
  else:
    print("GET_BIN_OP_MOD_C_CODE Only mod between float for now!")
    sys.exit(-1)
  
def GET_BIN_OP_DIV_C_CODE(partially_complete_logic, out_dir, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
    return GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state)
  elif VHDL.WIRES_ARE_INT_N(partially_complete_logic.inputs, partially_complete_logic):
    return GET_BIN_OP_DIV_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state)
  elif C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
  else:
    print("GET_BIN_OP_DIV_C_CODE Only div between uint and float for now!")
    sys.exit(-1)
    
    
def GET_BIN_OP_MULT_C_CODE(partially_complete_logic, out_dir, parser_state):
  # If one of inputs is signed int then other input will be bit extended to include positive sign bit
  # TODO signed mult
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if VHDL.WIRES_ARE_UINT_N(partially_complete_logic.inputs, partially_complete_logic):
    return GET_BIN_OP_MULT_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state)
  elif C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir)
  elif VHDL.WIRES_ARE_INT_N(partially_complete_logic.inputs, partially_complete_logic):
    return GET_BIN_OP_MULT_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state)
  else:
    print("GET_BIN_OP_MULT_C_CODE Only mult between uint and float for now!")
    sys.exit(-1)
    
def GET_BIN_OP_PLUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_exp_width, left_mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(left_t)
  right_exp_width, right_mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(left_t)
  left_width = 1 + left_exp_width + left_mantissa_width
  right_width = 1 + right_exp_width + right_mantissa_width
  
  if not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t,output_t]) or not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t,output_t]):
    print('''"left_t != "float" or  right_t != "float" output_t too  for plus''',left_t,right_t)
    sys.exit(-1)
  fp_t = output_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  # Could pad up to make diff in exponents/max shifting amount = 255?
  # Software 32b implementations pad with 6 zeros
  pad = 6
  
  mantissa_w_hidden_bit_width = mantissa_width + 1 # 24
  mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1 #25
  sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1 + pad #26
  leading_zeros_width = int(math.ceil(math.log(mantissa_width+1,2.0)))
  
  

  text = ''''''
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
//#include "bit_manip.h"
//#include "bit_math.h"

// Float add
// Adds are complicated
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Get exponent for left and right
  uint''' + str(exponent_width) + '''_t left_exponent;
  left_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  uint''' + str(exponent_width) + '''_t right_exponent;
  right_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
    
  '''+fp_t+''' x;
  '''+fp_t+''' y;
  // Step 1: Copy inputs so that left's exponent >= than right's.
  //    Is this only needed for shift operation that takes unsigned only?
  //    ALLOW SHIFT BY NEGATIVE?????
  if ( right_exponent > left_exponent ) // Lazy switch to GT
  {
     x = right;  
     y = left;
  }
  else
  { 
     x = left;
     y = right;
  }
  
  // Step 2: Break apart into S E M
  // X
  uint''' + str(mantissa_width) + '''_t x_mantissa; 
  x_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(x);
  uint''' + str(exponent_width) + '''_t x_exponent;
  x_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(x);
  uint1_t x_sign;
  x_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(x);
  // Y
  uint''' + str(mantissa_width) + '''_t y_mantissa;
  y_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(y);
  uint''' + str(exponent_width) + '''_t y_exponent;
  y_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(y);
  uint1_t y_sign;
  y_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(y);
  
  // Mantissa needs +3b wider
  //  [sign][overflow][hidden][23 bit mantissa]
  // Put 0's in overflow bit and sign bit
  // Put a 1 hidden bit if exponent is non-zero.
  // X
  // Determine hidden bit
  uint1_t x_hidden_bit;
  if(x_exponent == 0) // lazy swith to ==
  {
    x_hidden_bit = 0;
  }
  else
  {
    x_hidden_bit = 1;
  }
  // Apply hidden bit
  uint''' + str(mantissa_w_hidden_bit_width) + '''_t x_mantissa_w_hidden_bit; 
  x_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(x_hidden_bit, x_mantissa);
  // Y
  // Determine hidden bit
  uint1_t y_hidden_bit;
  if(y_exponent == 0) // lazy swith to ==
  {
    y_hidden_bit = 0;
  }
  else
  {
    y_hidden_bit = 1;
  }
  // Apply hidden bit
  uint''' + str(mantissa_w_hidden_bit_width) + '''_t y_mantissa_w_hidden_bit; 
  y_mantissa_w_hidden_bit = uint1_uint''' + str(mantissa_width) + '''(y_hidden_bit, y_mantissa);

  // Step 4: If necessary, negate mantissas (twos comp) such that add makes sense
  // STEP 2.B moved here
  // Make wider for twos comp/sign
  int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t x_mantissa_w_hidden_bit_sign_adj;
  int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''_t y_mantissa_w_hidden_bit_sign_adj;
  if(x_sign) //if(x_sign == 1)
  {
    x_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(x_mantissa_w_hidden_bit); //Returns +1 wider signed, int''' + str(mantissa_w_hidden_bit_sign_adj_width) + '''t
  }
  else
  {
    x_mantissa_w_hidden_bit_sign_adj = x_mantissa_w_hidden_bit;
  }
  if(y_sign) // if(y_sign == 1)
  {
    y_mantissa_w_hidden_bit_sign_adj = uint''' + str(mantissa_w_hidden_bit_width) + '''_negate(y_mantissa_w_hidden_bit);
  }
  else
  {
    y_mantissa_w_hidden_bit_sign_adj = y_mantissa_w_hidden_bit;
  }
  
  // Padd both x and y on right with zeros (shift left) such that 
  // when y is shifted to the right it doesnt drop mantissa lsbs (as much)
  int''' + str(mantissa_w_hidden_bit_sign_adj_width+pad) + '''_t x_mantissa_w_hidden_bit_sign_adj_rpad = int'''+str(mantissa_w_hidden_bit_sign_adj_width)+'''_uint'''+str(pad)+'''(x_mantissa_w_hidden_bit_sign_adj, 0);
  int''' + str(mantissa_w_hidden_bit_sign_adj_width+pad) + '''_t y_mantissa_w_hidden_bit_sign_adj_rpad = int'''+str(mantissa_w_hidden_bit_sign_adj_width)+'''_uint'''+str(pad)+'''(y_mantissa_w_hidden_bit_sign_adj, 0);

  // Step 3: Un-normalize Y (including hidden bit) so that xexp == yexp.
  // Already swapped left/right based on exponent
  // diff will be >= 0
  uint''' + str(exponent_width) + '''_t diff;
  diff = x_exponent - y_exponent;
  // Shift y by diff (bit manip pipelined function)
  int''' + str(mantissa_w_hidden_bit_sign_adj_width+pad) + '''_t y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;
  y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized = y_mantissa_w_hidden_bit_sign_adj_rpad >> diff;
  
  // Step 5: Compute sum 
  int''' + str(sum_mantissa_width) + '''_t sum_mantissa;
  sum_mantissa = x_mantissa_w_hidden_bit_sign_adj_rpad + y_mantissa_w_hidden_bit_sign_adj_rpad_unnormalized;

  // Step 6: Save sign flag and take absolute value of sum.
  uint1_t sum_sign;
  sum_sign = int''' + str(sum_mantissa_width) + '''_''' + str(sum_mantissa_width-1) + '''_''' + str(sum_mantissa_width-1) + '''(sum_mantissa);
  uint''' + str(sum_mantissa_width-1) + '''_t sum_mantissa_unsigned;
  sum_mantissa_unsigned = int''' + str(sum_mantissa_width) + '''_abs(sum_mantissa);

  // Step 7: Normalize sum and exponent. (Three cases.)
  uint1_t sum_overflow;
  sum_overflow = uint''' + str(sum_mantissa_width-1) + '''_''' + str(sum_mantissa_width-2) + '''_''' + str(sum_mantissa_width-2) + '''(sum_mantissa_unsigned);
  uint''' + str(exponent_width) + '''_t sum_exponent_normalized;
  uint''' + str(mantissa_width) + '''_t sum_mantissa_unsigned_normalized;
  if (sum_overflow) //if ( sum_overflow == 1 )
  {
     // Case 1: Sum overflow.
     //         Right shift significand by 1 and increment exponent.
     sum_exponent_normalized = x_exponent + 1;
     sum_mantissa_unsigned_normalized = uint''' + str(sum_mantissa_width-1) + '''_''' + str(sum_mantissa_width-3) + '''_''' + str(sum_mantissa_width-mantissa_width-2) + '''(sum_mantissa_unsigned);
  }
  else if(sum_mantissa_unsigned == 0) // laxy switch to ==
  {
     //
     // Case 3: Sum is zero.
     sum_exponent_normalized = 0;
     sum_mantissa_unsigned_normalized = 0;
  }
  else
  {
     // Case 2: Sum is nonzero and did not overflow.
     // Dont waste zeros at start of mantissa
     // Find position of first non-zero digit from left
     // Know bit25(sign) and bit24(overflow) are not set
     // Hidden bit is [23], can narrow down to 24b wide including hidden bit 
     uint''' + str(sum_mantissa_width-2) + '''_t sum_mantissa_unsigned_narrow;
     sum_mantissa_unsigned_narrow = sum_mantissa_unsigned;
     uint''' + str(leading_zeros_width) + '''_t leading_zeros; // width = ceil(log2(len(sumsig)))
     leading_zeros = count0s_uint''' + str(sum_mantissa_width-2) + '''(sum_mantissa_unsigned_narrow); // Count from left/msbs downto, uintX_count0s counts from right
     // NOT CHECKING xexp < adj
     // Case 2b: Adjust significand and exponent.
     sum_exponent_normalized = x_exponent - leading_zeros;
     uint''' + str(sum_mantissa_width-2) + '''_t sum_mantissa_unsigned_normalized_rpad = sum_mantissa_unsigned_narrow << leading_zeros;
     sum_mantissa_unsigned_normalized = uint''' + str(sum_mantissa_width-2) + '''_''' + str(sum_mantissa_width-4) + '''_''' + str(sum_mantissa_width-mantissa_width-3) + '''(sum_mantissa_unsigned_normalized_rpad);
  }
  
  // Declare the output portions
  uint''' + str(mantissa_width) + '''_t z_mantissa;
  uint''' + str(exponent_width) + '''_t z_exponent;
  uint1_t z_sign;
  z_sign = sum_sign;
  z_exponent = sum_exponent_normalized;
  z_mantissa = sum_mantissa_unsigned_normalized;
  // Assemble output  
  return float_uint'''+str(exponent_width) + "_uint" + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

  #print("C CODE")
  #print(text)

  return text
  
def GET_BIN_OP_LT_LTE_C_CODE(partially_complete_logic, out_dir, op_str):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_LT_LTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str)
  else:
    print("GET_BIN_OP_LT_LTE_C_CODE Only between float for now!")
    sys.exit(-1)
    
def GET_BIN_OP_LT_LTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  
  # Inputs must be float
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    print('''"left_t != "float" or  right_t != "float" for <= ''')
    sys.exit(-1)
    
  # Output must be bool
  if output_t != "uint1_t":
    print("GET_BIN_OP_LT_LTE_FLOAT_C_CODE output_t != uint1_t")
    sys.exit(-1)
  
  fp_t = left_t  
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  abs_val_width = exponent_width + mantissa_width
  abs_val_prefix = "uint" + str(abs_val_width)
  abs_val_t = abs_val_prefix + "_t"
  

  text = ''''''
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float LT/LTE std_logic_vector in C silly
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // LEFT
  uint''' + str(mantissa_width) + '''_t left_mantissa;  
  left_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  uint''' + str(exponent_width) + '''_t left_exponent;
  left_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  uint1_t left_sign;
  left_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  // RIGHT
  uint''' + str(mantissa_width) + '''_t right_mantissa;
  right_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
  uint''' + str(exponent_width) + '''_t right_exponent;
  right_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
  uint1_t right_sign;
  right_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
  
  // Do abs value compare by using exponent as msbs
  //  (-1)^s    * m  *   2^(e - 127)
  ''' + abs_val_t + ''' left_abs;
  left_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(left_exponent, left_mantissa);
  ''' + abs_val_t + ''' right_abs;
  right_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(right_exponent, right_mantissa);'''
  
  # Prepare the reversed operation for if both operands are negative
  # ~~~ because youre a lazy bitch, I think
  # if both neg then 
  # Switches LT->GT(=flip args LTE), LTE->GTE(flipped args GT)
  if op_str == "<":
    flipped_op_str = "<="
  else:
    # op str <=
    flipped_op_str = "<"
  
  text += '''
  // Adjust for sign
  uint1_t rv;
  uint1_t same_sign;
  same_sign = left_sign == right_sign;
  uint1_t pos_signs;
  uint1_t neg_signs;
  neg_signs = left_sign; // Only used if same sign
  pos_signs = !left_sign; // Only used if same sign
  if(same_sign & pos_signs)
  {
    rv = left_abs ''' + op_str + ''' right_abs;
  }
  else if(same_sign & neg_signs)
  {
    // Switches LT->GT(=flip args LTE), LTE->GTE(flipped args LT)
    rv = right_abs ''' + flipped_op_str + ''' left_abs;
  }
  else
  {
    // NOT SAME SIGN so can never equal ( but op is LT or LTE so LT is important part)
    // left must be neg to be LT (neg) right 
    rv = left_sign; // left_sign=1, right_sign=0, left is neg, can never LT left so true
  }

  return rv;
}'''

  #print "C CODE"
  #print text

  return text
  
  
  
  
def GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]] 
  if C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    return GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str)
  else:
    print("GET_BIN_OP_GT_GTE_C_CODE Only between float for now!")
    sys.exit(-1)
  
# GT/GTE
def GET_BIN_OP_GT_GTE_FLOAT_C_CODE(partially_complete_logic, out_dir, op_str):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t]):
    print('''"left_t != "float" or  right_t != "float" for >= ''')
    sys.exit(-1)
  fp_t = left_t
  # Output must be bool
  if output_t != "uint1_t":
    print("GET_BIN_OP_GT_GTE_FLOAT_C_CODE output_t != uint1_t")
    sys.exit(-1)
  
  fp_t = left_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  abs_val_width = exponent_width + mantissa_width
  abs_val_prefix = "uint" + str(abs_val_width)
  abs_val_t = abs_val_prefix + "_t"
  

  text = ''''''
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "float_e_m_t.h"

// Float GT/GTE std_logic_vector in C silly
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // LEFT
  uint''' + str(mantissa_width) + '''_t left_mantissa;  
  left_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  uint''' + str(exponent_width) + '''_t left_exponent;
  left_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  uint1_t left_sign;
  left_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  // RIGHT
  uint''' + str(mantissa_width) + '''_t right_mantissa;
  right_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
  uint''' + str(exponent_width) + '''_t right_exponent;
  right_exponent = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
  uint1_t right_sign;
  right_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
  
  // Do abs value compare by using exponent as msbs
  //  (-1)^s    * m  *   2^(e - 127)
  ''' + abs_val_t + ''' left_abs;
  left_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(left_exponent, left_mantissa);
  ''' + abs_val_t + ''' right_abs;
  right_abs = uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(right_exponent, right_mantissa);'''
  
  # if both neg then 
  # Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
  if op_str == ">":
    flipped_op_str = ">="
  else:
    # op str >=
    flipped_op_str = ">"
  
  text += '''
  // Adjust for sign
  uint1_t rv;
  uint1_t same_sign;
  same_sign = left_sign == right_sign;
  uint1_t pos_signs;
  uint1_t neg_signs;
  neg_signs = left_sign; // Only used if same sign
  pos_signs = !left_sign; // Only used if same sign
  if(same_sign & pos_signs)
  {
    rv = left_abs ''' + op_str + ''' right_abs;
  }
  else if(same_sign & neg_signs)
  {
    // Switches GT->LT(=flip args GTE), GTE->LTE(flipped args GT)
    rv = right_abs ''' + flipped_op_str + ''' left_abs;
  }
  else
  {
    // NOT SAME SIGN so can never equal ( but op is GT or GTE so GT is important part)
    // left must be pos to be GT (neg)right 
    rv = right_sign; // left_sign=0, right_sign=1, right is neg, can never GT left so true
  }

  return rv;
}'''

  #print "C CODE"
  #print text

  return text
  
  
def GET_BIN_OP_MINUS_FLOAT_C_CODE(partially_complete_logic, out_dir):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t,output_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t,output_t]):
    print('''"left_t != "float" or  right_t != "float" output_t too  for minus''')
    sys.exit(-1)
  fp_t = output_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  mantissa_w_hidden_bit_width = mantissa_width + 1 # 24
  mantissa_w_hidden_bit_sign_adj_width = mantissa_w_hidden_bit_width + 1 #25
  sum_mantissa_width = mantissa_w_hidden_bit_sign_adj_width + 1 #26
  leading_zeros_width = int(math.ceil(math.log(mantissa_width+1,2.0)))

  text = ""
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "bit_manip.h"
#include "bit_math.h"
#include "float_e_m_t.h"

// Float minus std_logic_vector in VHDL
// Minus is as complicated as add - yeah, so just use add
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  uint1_t right_sign;
  right_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
  uint'''+str(fp_t_width-1)+'''_t right_everythingelse = '''+fp_t+'''_''' + str(sign_index-1) + '''_0(right);
  uint'''+str(fp_t_width)+'''_t negated_right_unsigned = uint1_uint'''+str(fp_t_width-1) + '''(!right_sign, right_everythingelse);
  '''+fp_t+''' negated_right = '''+fp_t+'''_uint'''+str(fp_t_width)+'''(negated_right_unsigned);
  return left + negated_right;
}'''

  #print "C CODE"
  #print text

  return text 
  
def GET_BIN_OP_MOD_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
  # So there was this guy here trying to figure out the floating point implementation for modulo
  # Then the internet (of all people) chimes in and says modulo for floating point isn't actually part of standard C?
  # And that there are various fmod implementations for math.h
  # So me embracing the piece of shit (that I am) will implement mod in C too
  
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if left_t!=right_t or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t,output_t]):
    print(left_t, right_t, output_t)
    print('''"left_t != "float" or  right_t != "float" output_t mod''')
    sys.exit(-1)
  fp_t = output_t
    
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width

  text = ""
  
  text += '''
#include "uintN_t.h"
#include "intN_t.h"
#include "float_e_m_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// Float div std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Quotient
  '''+fp_t+''' q;
  q = left / right;
  
  // Convert to int (floor?)
  // float max value = 3.402823466*10^38
  // log2(3.402823466*10^38) ~ 128 , int129
  int129_t q_int;
  q_int = q;
  
  // Partial quotient
  '''+fp_t+''' partial;
  partial = ('''+fp_t+''')q_int * right;
  
  '''+fp_t+''' remainder;
  remainder = left - partial;
  
  return remainder;
}
'''

  return text


def GET_BIN_OP_DIV_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
  # Taking this directly from the 1 clock version VHDL from
  '''
  -- Company: Instituto Superior Tecnico
  -- Prof: Paulo Alexandre Crisostomo Lopes
  -- paulo.lopes@inesc-id.pt
  '''
  # Can improve in future
  # Thanks man
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t,output_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t,output_t]):
    print(left_t, right_t, output_t)
    print('''"left_t != "float" or  right_t != "float" output_t too div/mod''')
    sys.exit(-1)
  fp_t = output_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  a_width = mantissa_width + 3
  a_prefix = "uint" + str(a_width)
  a_t = a_prefix + "_t"
  
  remainder_width = mantissa_width + 2
  remainder_prefix = "uint" + str(remainder_width)
  remainder_t = remainder_prefix + "_t"
  
  tmp_remainder_width = mantissa_width + 2
  tmp_remainder_prefix = "uint" + str(tmp_remainder_width)
  tmp_remainder_t = tmp_remainder_prefix + "_t"
  
  exponent_aux_width = exponent_width + 1
  exponent_aux_t_prefix = "uint" + str(exponent_aux_width)
  exponent_aux_t = exponent_aux_t_prefix + "_t"
  
  mantissa_w_extra_bit_width = mantissa_width + 2
  mantissa_w_extra_bit_prefix = "uint" + str(mantissa_w_extra_bit_width)
  mantissa_w_extra_bit_t = mantissa_w_extra_bit_prefix + "_t"
  
  
  text = ""
  
  text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"
#include "float_e_m_t.h"

// Float div std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  ''' + mantissa_t + ''' x_mantissa;
  x_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  ''' + exponent_wide_t + ''' x_exponent_wide;
  x_exponent_wide = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  ''' + sign_t + ''' x_sign;
  x_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  // RIGHT
  ''' + mantissa_t + ''' y_mantissa;
  y_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
  ''' + exponent_wide_t + ''' y_exponent_wide;
  y_exponent_wide = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
  ''' + sign_t + ''' y_sign;
  y_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
  
  // Delcare intermediates
  ''' + a_t + ''' a;
  a = 0;
  ''' + remainder_t + ''' partial_remainder;
  partial_remainder = 0;
  ''' + remainder_t + ''' tmp_remainder;
  tmp_remainder = 0;
  ''' + exponent_aux_t + ''' exponent_aux;
  exponent_aux = 0;
  ''' + mantissa_w_extra_bit_t + ''' x_mantissa_w_extra_bit;
  x_mantissa_w_extra_bit = 0;
  ''' + mantissa_w_extra_bit_t + ''' y_mantissa_w_extra_bit;
  y_mantissa_w_extra_bit = 0;
  uint1_t a_i;
  a_i = 0;
  
  // Mantissas with extra bit
  x_mantissa_w_extra_bit = uint2_''' + mantissa_t_prefix + '''(1,x_mantissa);
  y_mantissa_w_extra_bit = uint2_''' + mantissa_t_prefix + '''(1,y_mantissa);
  
  // BIAS CONST
  ''' + exponent_bias_t + ''' BIAS;
  BIAS = ''' + str(exponent_bias) + ''';
  
  // Declare the output portions
  ''' + mantissa_t + ''' z_mantissa;
  ''' + exponent_t + ''' z_exponent;
  ''' + sign_t + ''' z_sign;
  
  // Sign
  z_sign = x_sign ^ y_sign;
  
  // Initial exponent sub and add bias
  exponent_aux = x_exponent_wide - y_exponent_wide;
  exponent_aux = exponent_aux + BIAS;
  
  // Divide unrolled since isnt simple unsigned div of mantissa
  partial_remainder = x_mantissa_w_extra_bit;'''
  for i in range(a_width-1, -1, -1):
    text += '''
  // Bit ''' + str(i) + '''
  /*
      tmp_remainder := partial_remainder - y_mantissa_w_extra_bit;
    if ( tmp_remainder(24)='0' ) then 
      -- result is non negative: partial_remainder >= y_mantissa_w_extra_bit
      -- note that tmp_remainder < 2 so bit 24 should be zero
      a(i):='1';
      partial_remainder := tmp_remainder;
    else
      a(i):='0'
    end if;
    partial_remainder := partial_remainder(23 downto 0) & '0'; -- sll
  */
  tmp_remainder = partial_remainder - y_mantissa_w_extra_bit;
  if(''' + remainder_prefix + '''_''' + str(remainder_width-1) + '''_''' + str(remainder_width-1) + '''(tmp_remainder) == 0 )
  {
    // result is non negative: partial_remainder >= y_mantissa_w_extra_bit
    // note that tmp_remainder < 2 so bit 24 should be zero
    a_i = 1;
    partial_remainder = tmp_remainder;
  }
  else
  {
    a_i = 0;
    partial_remainder = partial_remainder; // No change
  }
  partial_remainder = ''' + remainder_prefix + '''_uint1(partial_remainder, 0); // sll
  
  // Assign a(i)
  a = ''' + a_prefix + '''_uint1_'''+str(i)+'''(a,a_i);
  '''
  
  ###### DIV
  text += ''' 
  /////////////////////
  // END OF DIV LOOP FOR DIV
  //////////////////////
  
  // NO ROUND
  if(''' + a_prefix + '''_''' + str(a_width-1) + '''_''' + str(a_width-1) + '''(a)) //== 1)
  {
    z_mantissa = ''' + a_prefix + '''_''' + str(a_width-2) + '''_2(a);
    exponent_aux = exponent_aux; // No change
  }
  else
  {
    z_mantissa = ''' + a_prefix + '''_''' + str(a_width-3) + '''_1(a);
    exponent_aux = exponent_aux - 1;
  }'''
  
  
  text += ''' 
  z_exponent = ''' + exponent_aux_t_prefix + '''_''' + str(exponent_width-1) + '''_0(exponent_aux); 
  
  // Assemble output
  return float''' + '''_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

  #print "C CODE"
  #print text

  return text
  
def GET_BIN_OP_MULT_FLOAT_N_C_CODE(partially_complete_logic, out_dir):
  # Taking this directly from the 1 clock version VHDL from
  '''
  -- Company: Instituto Superior Tecnico
  -- Prof: Paulo Alexandre Crisostomo Lopes
  -- paulo.lopes@inesc-id.pt
  '''
  # Can improve in future
  # Thanks man
  
  
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  if not C_TO_LOGIC.C_FLOAT_TYPES_ARE_EQUAL([left_t,right_t,output_t]) or not C_TO_LOGIC.C_TYPES_ARE_FLOAT_TYPES([left_t,right_t,output_t]):
    print(left_t, right_t, output_t)
    print('''"left_t != "float" or  right_t != "float" output_t too''')
    sys.exit(-1)
  fp_t = output_t
  
  ######## ARB WIDTH FLOATS
  exponent_width,mantissa_width = C_TO_LOGIC.C_FLOAT_E_M_TYPE_TO_E_M(fp_t)
  mantissa_range = [mantissa_width-1,0]
  mantissa_t_prefix = "uint" + str(mantissa_width)
  mantissa_t = mantissa_t_prefix + "_t"
  exponent_range = [mantissa_width+exponent_width-1,mantissa_width]
  exponent_t_prefix = "uint" + str(exponent_width)
  exponent_t = exponent_t_prefix + "_t"
  exponent_width_plus1 = exponent_width + 1
  exponent_wide_t_prefix = "uint" + str(exponent_width_plus1)
  exponent_wide_t = exponent_wide_t_prefix + "_t"
  exponent_max = int(math.pow(2,exponent_width) - 1)
  exponent_bias = int(math.pow(2,exponent_width-1) - 1)
  exponent_bias_t = "uint" + str(exponent_width-1) + "_t"
  sign_index = mantissa_width+exponent_width
  sign_width = 1
  sign_t_prefix = "uint" + str(sign_width)
  sign_t = sign_t_prefix + "_t"
  fp_t_width = 1+exponent_width+mantissa_width
  
  
  aux_width = 1
  aux_t_prefix = "uint" + str(aux_width)
  aux_t = aux_t_prefix + "_t"
  aux2_width = (mantissa_width+1)*2 # 48 for fp32
  aux2_t_prefix = "uint" + str(aux2_width)
  aux2_t = aux2_t_prefix + "_t"
  aux2_in_width = (mantissa_width+1)
  aux2_in_t_prefix = "uint" + str(aux2_in_width)
  aux2_in_t = aux2_in_t_prefix + "_t"
  exponent_sum_width = exponent_width + 1
  exponent_sum_t_prefix = "uint" + str(exponent_sum_width)
  exponent_sum_t = exponent_sum_t_prefix + "_t"
  '''
  e_m_width = exponent_width + mantissa_width
  e_m_t_prefix = "uint" + str(e_m_width)
  e_m_t = e_m_t_prefix + "_t"
  s_e_m_width = sign_width + e_m_width
  s_e_m_t_prefix = "uint" + str(s_e_m_width)
  s_e_m_t = s_e_m_t_prefix + "_t"
  '''
  
  
  text = ""
  
  text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"
#include "float_e_m_t.h"

// Float mult std_logic_vector in VHDL
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Get mantissa exponent and sign for both
  // LEFT
  ''' + mantissa_t + ''' x_mantissa;
  x_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(left);
  ''' + exponent_wide_t + ''' x_exponent_wide;
  x_exponent_wide = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(left);
  ''' + sign_t + ''' x_sign;
  x_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(left);
  // RIGHT
  ''' + mantissa_t + ''' y_mantissa;
  y_mantissa = '''+fp_t+'''_''' + str(mantissa_range[0]) + '''_''' + str(mantissa_range[1]) + '''(right);
  ''' + exponent_wide_t + ''' y_exponent_wide;
  y_exponent_wide = '''+fp_t+'''_''' + str(exponent_range[0]) + '''_''' + str(exponent_range[1]) + '''(right);
  ''' + sign_t + ''' y_sign;
  y_sign = '''+fp_t+'''_''' + str(sign_index) + '''_''' + str(sign_index) + '''(right);
  
  // Declare the output portions
  ''' + mantissa_t + ''' z_mantissa;
  ''' + exponent_t + ''' z_exponent;
  ''' + sign_t + ''' z_sign;
  
  // Sign
  z_sign = x_sign ^ y_sign;
  
  // Multiplication with infinity = inf
  if((x_exponent_wide==''' + str(exponent_max) + ''') | (y_exponent_wide==''' + str(exponent_max) + '''))
  {
    z_exponent = ''' + str(exponent_max) + ''';
    z_mantissa = 0;
  }
  // Multiplication with zero = zero
  else if((x_exponent_wide==0) | (y_exponent_wide==0))
  {
    z_exponent = 0;
    z_mantissa = 0;
    z_sign = 0;
  }
  // Normal non zero|inf mult
  else
  {
    // Delcare intermediates
    ''' + aux_t + ''' aux;
    ''' + aux2_in_t + ''' aux2_x;
    ''' + aux2_in_t + ''' aux2_y;
    ''' + aux2_t + ''' aux2;
    ''' + exponent_bias_t + ''' BIAS;
    BIAS = ''' + str(exponent_bias) + ''';
    
    aux2_x = uint1_''' + mantissa_t_prefix + '''(1, x_mantissa);
    aux2_y = uint1_''' + mantissa_t_prefix + '''(1, y_mantissa);
    aux2 =  aux2_x * aux2_y;
    // args in Q23 result in Q46
    aux = ''' + aux2_t_prefix + '''_''' + str(aux2_width-1) + '''_''' + str(aux2_width-1) + '''(aux2);
    if(aux) //if(aux == 1)
    { 
      // >=2, shift left and add one to exponent
      // HACKY NO ROUNDING + aux2(23); // with round18
      z_mantissa = ''' + aux2_t_prefix + '''_''' + str(aux2_width-2) + '''_''' + str(aux2_width - mantissa_width -1) + '''(aux2); 
    }
    else
    { 
      // HACKY NO ROUNDING + aux2(22); // with rounding
      z_mantissa = ''' + aux2_t_prefix + '''_''' + str(aux2_width-3) + '''_''' + str(aux2_width - mantissa_width -2) + '''(aux2); 
    }
    
    // calculate exponent in parts 
    // do sequential unsigned adds and subs to avoid signed numbers for now
    // X and Y exponent are already 1 bit wider than needed
    // (0 & x_exponent) + (0 & y_exponent);
    ''' + exponent_sum_t + ''' exponent_sum = x_exponent_wide + y_exponent_wide;
    exponent_sum = exponent_sum + aux;
    exponent_sum = exponent_sum - BIAS;
    
    // HACKY NOT CHECKING
    // if (exponent_sum(8)='1') then
    z_exponent = ''' + exponent_sum_t_prefix + '''_''' + str(exponent_width-1) + '''_0(exponent_sum);
  }
  
  
  // Assemble output
  return float''' + '''_uint''' + str(exponent_width) + '''_uint''' + str(mantissa_width) + '''(z_sign, z_exponent, z_mantissa);
}'''

  #print("C CODE")
  #print(text)

  return text
  
  
def GET_BIN_OP_SR_INT_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  left_prefix = left_t.replace("_t","")
  is_signed = VHDL.C_TYPE_IS_INT_N(left_t)
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  if VHDL.C_TYPE_IS_INT_N(right_t):
    right_max_val = pow(2,right_width-1)-1
    right_unsigned_width = right_width-1
  else:
    right_max_val = pow(2,right_width)-1
    right_unsigned_width = right_width
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = output_t.replace("_t","")
  
  # TODO: FIX THIS
  # SHIFT WIDTH IS TRUNCATED TO 2^log2(math.ceil(math.log(max_shift+1,2))) -1
  # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  
  
  # TODO: Remove 1 LL
  # return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
  
  # Shift size is limited by width of left input
  max_shift = left_width-1
  shift_bit_width = min(max_shift.bit_length(), right_unsigned_width)
  needs_resize = right_max_val > (pow(2,shift_bit_width)-1)
  # Shift amount is resized
  resized_prefix = "uint" + str(shift_bit_width)
  resized_t = resized_prefix + "_t"
  
  text = ""
  
  text += '''
#include "intN_t.h"  
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''shifted right by maximum ''' + str(max_shift) + '''b
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Resize the shift amount (right)
  ''' + resized_t + ''' resized_shift_amount;
  resized_shift_amount = right;
  
  // Output
  ''' + output_t + ''' rv;
'''
  if needs_resize:
    text += '''
  // Check for oversized
  if(right > ''' + str(max_shift) + ''')
  {
    // Append sign bits on left and select rv from MSBs
    uint1_t sign;
'''
    if is_signed:
      text += '''    sign = ''' + left_prefix + '''_''' + str(left_width-1) + '''_''' + str(left_width-1) + '''(left);
'''
    else:
      text += '''    sign = 0;
'''
    text += "    // Big shift all sign bits\n"
    text += "    rv = uint1_"+str(output_width)+"(sign);\n"
    text += '''
  }
  else
  {
'''
  text += '''
    // Otherwise use Victor's muxes
    ''' + output_t + ''' v0 = left;
'''
  for b in range(0, shift_bit_width):
    text += "    " + output_t + " v"+str(b+1) + " = " + output_prefix + "_" + str(b) + "_" + str(b) + "(resized_shift_amount)" + " ? (v" + str(b) + " >> " + str(pow(2,b)) + ") : v" + str(b) + ";\n"
    
  text += "    rv = v" + str(shift_bit_width) + ";\n"
  
  if needs_resize:
    text += '''
  }
'''
  text += '''
  return rv;
}'''

  #if is_signed:
  #print("GET_BIN_OP_SR_UINT_C_CODE text")
  #print(text)
  #  sys.exit(-1)
  return text
  

#// 64B  First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
#// 32B also 4 LLs?
#// 128B 8 LLs
def GET_BIN_OP_SL_INT_UINT_C_CODE(partially_complete_logic, out_dir, containing_func_logic, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  #is_signed = VHDL.C_TYPE_IS_INT_N(left_t)
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  if VHDL.C_TYPE_IS_INT_N(right_t):
    right_max_val = pow(2,right_width-1)-1
    right_unsigned_width = right_width-1
  else:
    right_max_val = pow(2,right_width)-1
    right_unsigned_width = right_width
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = output_t.replace("_t","") 
  
  # TODO: Remove 1 LL
  # return x0 << x1;  // First try 4 LLs  // write_pipe.return_output := write_pipe.left sll  to_integer(right(7 downto 0)); was 3 LLs
  
  # Shift size is limited by width of left input
  max_shift = left_width-1
  shift_bit_width = min(max_shift.bit_length(), right_unsigned_width)
  needs_resize = right_max_val > (pow(2,shift_bit_width)-1)
  # Shift amount is resized up if needed
  
  resized_prefix = "uint" + str(shift_bit_width)
  resized_t = resized_prefix + "_t"
  
  text = ""
  
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''shifted left by maximum ''' + str(max_shift) + '''b
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Resize the shift amount (right)
  ''' + resized_t + ''' resized_shift_amount;
  resized_shift_amount = right;
'''
  text += '''
  // Output
  ''' + output_t + ''' rv;
'''
  if needs_resize:
    text += '''
  // Check for oversized
  if(right > ''' + str(max_shift) + ''')
  {
    // Big shift, all zeros
    rv = 0;
  }
  else
  {'''
  text += '''
    // Otherwise use Victor's muxes
    ''' + output_t + ''' v0 = left;
'''
  for b in range(0, shift_bit_width):
    text += "    " + output_t + " v"+str(b+1) + " = " + output_prefix + "_" + str(b) + "_" + str(b) + "(resized_shift_amount)" + " ? (v" + str(b) + " << " + str(pow(2,b)) + ") : v" + str(b) + ";\n"
    
  text += "    rv = v" + str(shift_bit_width) + ";\n"
   
  if needs_resize:
    text += '''
  }
'''

  text += '''
  return rv;
}'''


  #print("GET_BIN_OP_SL text")
  #print(text)
  
  return text
  
  

  
def GET_BIN_OP_MULT_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  max_input_width = max(left_width,right_width)
  resized_prefix = "uint" + str(max_input_width)
  resized_t = resized_prefix + "_t"
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = "uint" + str(output_width)
  
  # Temp try to reduce bit width?
  # Output width is max =  left_width+right_width
  # Actual max internal width is min out output width and max of input widths
  # Does not include output width because of sign for signed mult???
  # TODO: Check if can limit like UINT including output width
  max_intermidate_bit_width = left_width+right_width
  
  
  text = ""
  
  # Generate abs path to uint headers
  #top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
  #uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
  #int_h ='''#include "''' + top_dir + '''/intN_t.h"'''
  
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b x ''' + str(right_width) + '''b mult
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Resize
  ''' + resized_t + ''' left_resized;
  left_resized = left;
  ''' + resized_t + ''' right_resized;
  right_resized = right;
  
  // Left repeated bit unsigneds
'''
  for rb in range(0,max_input_width):
    text += ''' // BIT''' + str(rb) + ''' REPEATED
  // Select bit
  uint1_t left''' + str(rb) + '''_x1;
  left''' + str(rb) + '''_x1 = ''' + resized_prefix + '''_''' + str(rb) + '''_''' + str(rb) + '''(left_resized);
  // Dup
  uint''' + str(max_input_width) + '''_t  left''' + str(rb) + '''_x''' + str(max_input_width) + ''';
  left''' + str(rb) + '''_x''' + str(max_input_width) + ''' = uint1_''' + str(max_input_width) + '''(left''' + str(rb) + '''_x1);
'''
  
  text += '''
  // Partial sums
'''
  for rb in range(0,max_input_width):
    text += " " + resized_t + ''' p''' + str(rb) + ''';
  p''' + str(rb) + ''' = left''' + str(rb) + '''_x''' + str(max_input_width) + ''' & right_resized;
'''

  # Save types of shifted partial sum vars for ease later
  var_2_type = dict()
  
  text += '''
  // Shifted partial sums
  ''' + resized_t + ''' p0_shifted;
  p0_shifted = p0;
'''
  var_2_type["p0_shifted"] = resized_t
  p_width = max_input_width
  for p in range(1,max_input_width):
    uintp_prefix = "uint" + str(p)
    uintp_t =  uintp_prefix + "_t"
    #p_width_minus1 = p_width - 1
    p_t_prefix = "uint" + str(p_width)
    p_shifted_t = "uint" + str(p_width + p) + "_t"
    p_shifted = '''p''' + str(p) + '''_shifted'''
    var_2_type[p_shifted] = p_shifted_t
    text += ''' ''' + uintp_t + ''' zero_x''' + str(p) + ''';
  zero_x''' + str(p) + ''' = 0;
  ''' + p_shifted_t + ''' p''' + str(p) + '''_shifted;
  p''' + str(p) + '''_shifted = ''' + p_t_prefix + '''_''' + uintp_prefix + '''(p''' + str(p) + ''' ,zero_x''' + str(p) + ''');
'''
  
  
  
  # Cap shifted partiual sums to max intermediate width
  max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
  max_intermidate_t = max_intermidate_prefix + "_t"
  
  # Do Signed trick with inverted bits, already have shifted version in 'pN_shifted'
  '''
                                                    1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
                                                ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
                                         ~p2[7] +p2[6] +p2[5] +p2[4] +p2[3] +p2[2] +p2[1] +p2[0]   0      0
                                  ~p3[7] +p3[6] +p3[5] +p3[4] +p3[3] +p3[2] +p3[1] +p3[0]   0      0      0
                           ~p4[7] +p4[6] +p4[5] +p4[4] +p4[3] +p4[2] +p4[1] +p4[0]   0      0      0      0
                    ~p5[7] +p5[6] +p5[5] +p5[4] +p5[3] +p5[2] +p5[1] +p5[0]   0      0      0      0      0
             ~p6[7] +p6[6] +p6[5] +p6[4] +p6[3] +p6[2] +p6[1] +p6[0]   0      0      0      0      0      0
   1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
 ------------------------------------------------------------------------------------------------------------
P[15]  P[14]  P[13]  P[12]  P[11]  P[10]   P[9]   P[8]   P[7]   P[6]   P[5]   P[4]   P[3]   P[2]   P[1]  P[0]
  '''

  msb_prefix = "uint1"
  msb_t = msb_prefix + "_t"
  for p in range(0,max_input_width):
    # Shifted p
    p_shifted_width = p_width + p
    p_shifted_prefix = "uint" + str(p_shifted_width)
    p_shifted_t = "uint" + str(p_shifted_width) + "_t"
    p_shifted = '''p''' + str(p) + '''_shifted'''
    
    # Get msb
    p_shifted_msb = p_shifted + "_msb"
    text += '''
    
  // P ''' + str(p) + ''' adjusted
  ''' + msb_t + ''' ''' + p_shifted_msb + ''';
  ''' + p_shifted_msb + ''' = ''' + p_shifted_prefix + '''_''' + str(p_shifted_width-1) + '''_''' + str(p_shifted_width-1) + '''(''' + p_shifted + ''');'''
    
    
    # First is special case
    if p == 0:
      # Get lower bits of shfited
      lsbs_width = p_shifted_width - 1
      lsbs_prefix = "uint" + str(lsbs_width)
      lsbs_t = lsbs_prefix + "_t"
      p_shifted_lsbs = p_shifted + "_lsbs"
      text += '''
  // First is special case
  ''' + lsbs_t + ''' ''' + p_shifted_lsbs + ''';
  ''' + p_shifted_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(lsbs_width-1) + '''_0(''' + p_shifted + ''');'''
      
      # Invert msb
      p_shifted_msb_neg = p_shifted_msb + "_neg"
      text += '''
  ''' + msb_t + ''' ''' + p_shifted_msb_neg + ''';
  ''' + p_shifted_msb_neg + ''' = !''' + p_shifted_msb + ''';'''
      
      # Concat negated msb and lsbs
      p_shifted_neg_msb_and_lsbs_prefix_width = lsbs_width + 1
      p_shifted_neg_msb_and_lsbs_prefix = "uint" + str(p_shifted_neg_msb_and_lsbs_prefix_width)
      p_shifted_neg_msb_and_lsbs_t = p_shifted_neg_msb_and_lsbs_prefix + "_t"
      p_shifted_neg_msb_and_lsbs = p_shifted + "_neg_msb_and_lsbs"
      text += '''
  ''' + p_shifted_neg_msb_and_lsbs_t + ''' ''' + p_shifted_neg_msb_and_lsbs + ''';
  ''' + p_shifted_neg_msb_and_lsbs + ''' = ''' + msb_prefix + '''_''' + lsbs_prefix + '''(''' + p_shifted_msb_neg + ''',''' + p_shifted_lsbs + ''');'''
      
      # Adjusted result has 1 added as MSB
      # 1  ~p0[7]  p0[6]  p0[5]  p0[4]  p0[3]  p0[2]  p0[1]  p0[0]
      adj_width = p_shifted_width + 1
      # Cap shifted partiual sums to max intermediate width
      if adj_width > max_intermidate_bit_width:
        adj_width = max_intermidate_bit_width
      adj_width_prefix = "uint" + str(adj_width)
      adj_t = adj_width_prefix+ "_t"
      p_shifted_adj = p_shifted + "_adj"
      text += '''
  ''' + adj_t + ''' ''' + p_shifted_adj + ''';
  ''' + p_shifted_adj + ''' = uint1_''' + p_shifted_neg_msb_and_lsbs_prefix + '''(1, ''' + p_shifted_neg_msb_and_lsbs + ''');'''
      var_2_type[p_shifted_adj] = adj_t
      
    # End is special case
    elif p == (max_input_width-1):
      
      #1  +p7[7] ~p7[6] ~p7[5] ~p7[4] ~p7[3] ~p7[2] ~p7[1] ~p7[0]   0      0      0      0      0      0      0
      # Get zeros
      p_shifted_zeros_width = p
      p_shifted_zeros_prefix = "uint" + str(p_shifted_zeros_width)
      p_shifted_zeros_t = p_shifted_zeros_prefix + "_t"
      p_shifted_zeros = p_shifted + "_zeros"
      text += '''
  // End special case
  ''' + p_shifted_zeros_t + ''' ''' + p_shifted_zeros + ''';
  ''' + p_shifted_zeros + ''' = ''' + p_shifted_prefix + '''_''' + str(p_shifted_zeros_width-1) + '''_0(''' + p_shifted + ''');'''
  
      # Get upper lsbs that arent zero
      # DOES NOT INCLUDE MSB
      p_shifted_upper_lsbs_width = p_width - 1
      p_shifted_upper_lsbs_prefix = "uint" + str(p_shifted_upper_lsbs_width)
      p_shifted_upper_lsbs_t = p_shifted_upper_lsbs_prefix + "_t"
      p_shifted_upper_lsbs = p_shifted + "_upper_lsbs"
      low = p_shifted_zeros_width
      high = p_shifted_width - 2 # SKIP MSB
      text += '''
  ''' + p_shifted_upper_lsbs_t + ''' ''' + p_shifted_upper_lsbs + ''';
  ''' + p_shifted_upper_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(high) + '''_''' + str(low) + '''(''' + p_shifted + ''');'''
  
      # Invert upper lsbs 
      p_shifted_upper_lsbs_neg = p_shifted_upper_lsbs + "_neg"
      text += '''
  ''' + p_shifted_upper_lsbs_t + ''' ''' + p_shifted_upper_lsbs_neg + ''';
  ''' + p_shifted_upper_lsbs_neg + ''' = !''' + p_shifted_upper_lsbs + ''';'''
      
      # Concat zeros and negated upper lsbs
      p_shifted_upper_lsbs_neg_and_zeros_width = p_shifted_upper_lsbs_width + p_shifted_zeros_width
      p_shifted_upper_lsbs_neg_and_zeros_prefix = "uint" + str(p_shifted_upper_lsbs_neg_and_zeros_width)
      p_shifted_upper_lsbs_neg_and_zeros_t = p_shifted_upper_lsbs_neg_and_zeros_prefix + "_t"
      p_shifted_upper_lsbs_neg_and_zeros = p_shifted_upper_lsbs_neg + "_and_zeros"
      text += '''
  ''' + p_shifted_upper_lsbs_neg_and_zeros_t + ''' ''' + p_shifted_upper_lsbs_neg_and_zeros + ''';
  ''' + p_shifted_upper_lsbs_neg_and_zeros + ''' = ''' + p_shifted_upper_lsbs_prefix + '''_''' + p_shifted_zeros_prefix + '''(''' + p_shifted_upper_lsbs_neg + ''', ''' + p_shifted_zeros + ''');'''
      
      # Concat msb
      p_shifted_upper_lsbs_neg_and_zeros_w_msb_width = p_shifted_upper_lsbs_neg_and_zeros_width + 1
      p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix = "uint" + str(p_shifted_upper_lsbs_neg_and_zeros_w_msb_width)
      p_shifted_upper_lsbs_neg_and_zeros_w_msb_t = p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix + "_t"
      p_shifted_upper_lsbs_neg_and_zeros_w_msb = p_shifted_upper_lsbs_neg_and_zeros + "_w_msb"
      text += '''
  ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb_t + ''' ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''';
  ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''' = uint1_''' + p_shifted_upper_lsbs_neg_and_zeros_prefix + '''(''' +  p_shifted_msb + ''', ''' + p_shifted_upper_lsbs_neg_and_zeros + ''');'''
      
      
      # Concat 1 as MSB for adjusted result
      adj_width = p_shifted_upper_lsbs_neg_and_zeros_w_msb_width + 1
      # Cap shifted partiual sums to max intermediate width
      if adj_width > max_intermidate_bit_width:
        adj_width = max_intermidate_bit_width
      adj_width_prefix = "uint" + str(adj_width)
      adj_t = adj_width_prefix+ "_t"
      p_shifted_adj = p_shifted + "_adj"
      text += '''
  ''' + adj_t + ''' ''' + p_shifted_adj + ''';
  ''' + p_shifted_adj + ''' = uint1_''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb_prefix + '''(1, ''' + p_shifted_upper_lsbs_neg_and_zeros_w_msb + ''');'''
      var_2_type[p_shifted_adj] = adj_t
      
    # Mid is normal case (very similar to p==0)
    else:
      # Get lower bits of shfited
      lsbs_width = p_shifted_width - 1
      lsbs_prefix = "uint" + str(lsbs_width)
      lsbs_t = lsbs_prefix + "_t"
      p_shifted_lsbs = p_shifted + "_lsbs"
      text += '''
  // Mid is normal case   
  ''' + lsbs_t + ''' ''' + p_shifted_lsbs + ''';
  ''' + p_shifted_lsbs + ''' = ''' + p_shifted_prefix + '''_''' + str(lsbs_width-1) + '''_0(''' + p_shifted + ''');'''
      
      # Invert msb
      p_shifted_msb_neg = p_shifted_msb + "_neg"
      text += '''
  ''' + msb_t + ''' ''' + p_shifted_msb_neg + ''';
  ''' + p_shifted_msb_neg + ''' = !''' + p_shifted_msb + ''';'''
      
      # Adjusted result has Concat negated msb and lsbs
      adj_width = p_shifted_width
      # Cap shifted partiual sums to max intermediate width
      if adj_width > max_intermidate_bit_width:
        adj_width = max_intermidate_bit_width
      adj_width_prefix = "uint" + str(adj_width)
      adj_t = adj_width_prefix+ "_t"
      p_shifted_adj = p_shifted + "_adj"
      # ~p1[7] +p1[6] +p1[5] +p1[4] +p1[3] +p1[2] +p1[1] +p1[0]   0
      text += '''
  ''' + adj_t + ''' ''' + p_shifted_adj + ''';
  ''' + p_shifted_adj + ''' = ''' + msb_prefix + '''_''' + lsbs_prefix + '''(''' + p_shifted_msb_neg + ''',''' + p_shifted_lsbs + ''');'''
      var_2_type[p_shifted_adj] = adj_t
  
  
  
  
  # BINARY TREE SUM
  layer_nodes = []
  for p in range(0,max_input_width):
    layer_nodes.append("p" + str(p) + "_shifted_adj")
    
  layer=0
  node=0
  
  text += '''
  // Binary summation of partial sums
'''
 
  
  # DO
  while True: 
    text += '''
  // Layer + ''' + str(layer) + '''
'''
    node = 0
    new_layer_nodes = []
    # Write adds in pairs
    # While 2 args to add
    while(len(layer_nodes) >= 2):
      left_arg = layer_nodes.pop(0)
      right_arg = layer_nodes.pop(0)
      left_t = var_2_type[left_arg]
      right_t = var_2_type[right_arg]
      # Sum type is max width
      left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
      right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
      max_width = max(left_width,right_width)
      sum_width = max_width+1
      
      # Reduce sum width to max intermediate width
      if sum_width > max_intermidate_bit_width:
        sum_width = max_intermidate_bit_width
      
      sum_t = "uint" + str(sum_width) + "_t"
      sum_var = "sum_layer" + str(layer) + "_node" + str(node)
      var_2_type[sum_var] = sum_t
      text += ''' ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + left_arg + " + " + right_arg + ''';
'''
      # This sum node is on next layer
      new_layer_nodes.append(sum_var)
      node += 1
    
    # Out of while loop 
    # < 2 nodes left to sum in this node
    if len(layer_nodes) == 1:
      # One node left
      the_arg = layer_nodes.pop(0)
      the_t = var_2_type[the_arg]
      sum_t = the_t     
      sum_var = "sum_layer" + str(layer) + "_node" + str(node)
      var_2_type[sum_var] = sum_t
      text += ''' // Odd node in layer
  ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + the_arg + ''';
  '''
      # This sum node is on next layer
      new_layer_nodes.append(sum_var)
      node += 1
      
    
    # WHILE
    if len(new_layer_nodes) >= 2:
      # Continue
      layer_nodes = new_layer_nodes
      layer += 1
    else:
      # DONE
      break;
  
  # Done with outer layer while loop
    
  # Do return
  return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
  return_t = var_2_type[return_var]
  text += '''
  ''' + "// Return" + '''
  ''' + return_t + ''' rv;
  rv = ''' + return_var + ''';
  return rv;
}
'''
  
  
  return text 
  #print text
  #sys.exit(-1)


    
def GET_BIN_OP_MULT_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):
  '''
 p0[7:0] = a[0] x b[7:0] = {8{a[0]}} & b[7:0]
 p1[7:0] = a[1] x b[7:0] = {8{a[1]}} & b[7:0]
 p2[7:0] = a[2] x b[7:0] = {8{a[2]}} & b[7:0]
 p3[7:0] = a[3] x b[7:0] = {8{a[3]}} & b[7:0]
 p4[7:0] = a[4] x b[7:0] = {8{a[4]}} & b[7:0] 
 
 
 p5[7:0] = a[5] x b[7:0] = {8{a[5]}} & b[7:0]
 p6[7:0] = a[6] x b[7:0] = {8{a[6]}} & b[7:0]
 p7[7:0] = a[7] x b[7:0] = {8{a[7]}} & b[7:0]
where {8{a[0]}} means repeating a[0] (the 0th bit of a) 8 times (Verilog notation).

To produce our product, we then need to add up all eight of our partial products, as shown here:

                                                p0[7] p0[6] p0[5] p0[4] p0[3] p0[2] p0[1] p0[0]
                                        + p1[7] p1[6] p1[5] p1[4] p1[3] p1[2] p1[1] p1[0] 0
                                  + p2[7] p2[6] p2[5] p2[4] p2[3] p2[2] p2[1] p2[0] 0     0
                            + p3[7] p3[6] p3[5] p3[4] p3[3] p3[2] p3[1] p3[0] 0     0     0
                      + p4[7] p4[6] p4[5] p4[4] p4[3] p4[2] p4[1] p4[0] 0     0     0     0
                + p5[7] p5[6] p5[5] p5[4] p5[3] p5[2] p5[1] p5[0] 0     0     0     0     0
          + p6[7] p6[6] p6[5] p6[4] p6[3] p6[2] p6[1] p6[0] 0     0     0     0     0     0
    + p7[7] p7[6] p7[5] p7[4] p7[3] p7[2] p7[1] p7[0] 0     0     0     0     0     0     0
-------------------------------------------------------------------------------------------
P[15] P[14] P[13] P[12] P[11] P[10]  P[9]  P[8]  P[7]  P[6]  P[5]  P[4]  P[3]  P[2]  P[1]  P[0]
  '''
  # Need bit select
  # Need bit concat
  # Need bitwise AND
  # Have sum already


  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  max_input_width = max(left_width,right_width)
  resized_prefix = "uint" + str(max_input_width)
  resized_t = resized_prefix + "_t"
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = "uint" + str(output_width)
  
  # Temp try to reduce bit width?
  # Output width is max =  left_width+right_width
  # Actual max internal width is min out output width and ma xof input widths
  max_intermidate_bit_width = min(output_width, left_width+right_width)
  
  
  text = ""
  
  # Generate abs path to uint headers
  #top_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
  #uint_h ='''#include "''' + top_dir + '''/uintN_t.h"'''
  #int_h ='''#include "''' + top_dir + '''/intN_t.h"'''
  
  text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b x ''' + str(right_width) + '''b mult
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Resize
  ''' + resized_t + ''' left_resized;
  left_resized = left;
  ''' + resized_t + ''' right_resized;
  right_resized = right;
  
  // Left repeated bit unsigneds
'''
  for rb in range(0,max_input_width):
    text += ''' // BIT''' + str(rb) + ''' REPEATED
  // Select bit
  uint1_t left''' + str(rb) + '''_x1;
  left''' + str(rb) + '''_x1 = ''' + resized_prefix + '''_''' + str(rb) + '''_''' + str(rb) + '''(left_resized);
  // Dup
  uint''' + str(max_input_width) + '''_t  left''' + str(rb) + '''_x''' + str(max_input_width) + ''';
  left''' + str(rb) + '''_x''' + str(max_input_width) + ''' = uint1_''' + str(max_input_width) + '''(left''' + str(rb) + '''_x1);
'''
  
  
  
  text += '''
  // Partial sums
'''
  for rb in range(0,max_input_width):
    text += " " + resized_t + ''' p''' + str(rb) + ''';
  p''' + str(rb) + ''' = left''' + str(rb) + '''_x''' + str(max_input_width) + ''' & right_resized;
'''
  # Save types of vars for ease later
  var_2_type = dict()
  
  # Cap shifted partiual sums to max intermediate width
  max_intermidate_prefix = "uint" + str(max_intermidate_bit_width)
  max_intermidate_t = max_intermidate_prefix + "_t"
  
  text += '''
  // Shifted partial sums
  ''' + resized_t + ''' p0_shifted;
  p0_shifted = p0;
'''
  var_2_type["p0_shifted"] = resized_t
  for p in range(1,max_input_width):
    uintp_prefix = "uint" + str(p)
    uintp_t =  uintp_prefix + "_t"
    p_width = max_input_width
    #p_width_minus1 = p_width - 1
    p_t_prefix = "uint" + str(p_width)
    
    p_shifted_width = p_width + p
    # Cap shifted partiual sums to max intermediate width
    if p_shifted_width > max_intermidate_bit_width:
      p_shifted_width = max_intermidate_bit_width
    p_shifted_t = "uint" + str(p_shifted_width) + "_t"
        
    p_shifted = '''p''' + str(p) + '''_shifted'''
    var_2_type[p_shifted] = p_shifted_t
    
    text += ''' ''' + uintp_t + ''' zero_x''' + str(p) + ''';
  zero_x''' + str(p) + ''' = 0;
  ''' + p_shifted_t + ''' p''' + str(p) + '''_shifted;
  p''' + str(p) + '''_shifted = ''' + p_t_prefix + '''_''' + uintp_prefix + '''(p''' + str(p) + ''' ,zero_x''' + str(p) + ''');
'''
  
  layer_nodes = []
  for p in range(0,max_input_width):
    layer_nodes.append("p" + str(p) + "_shifted")
    
  layer=0
  node=0
  
  text += '''
  // Binary summation of partial sums
'''
 
  
  # DO
  while True: 
    text += '''
  // Layer + ''' + str(layer) + '''
'''
    node = 0
    new_layer_nodes = []
    # Write adds in pairs
    # While 2 args to add
    while(len(layer_nodes) >= 2):
      left_arg = layer_nodes.pop(0)
      right_arg = layer_nodes.pop(0)
      left_t = var_2_type[left_arg]
      right_t = var_2_type[right_arg]
      # Sum type is max width
      left_width = int(left_t.replace("uint","").replace("int","").replace("_t",""))
      right_width = int(right_t.replace("uint","").replace("int","").replace("_t",""))
      max_width = max(left_width,right_width)
      sum_width = max_width+1
      
      # Reduce sum width to max intermediate width
      if sum_width > max_intermidate_bit_width:
        sum_width = max_intermidate_bit_width
      
      sum_t = "uint" + str(sum_width) + "_t"
      sum_var = "sum_layer" + str(layer) + "_node" + str(node)
      var_2_type[sum_var] = sum_t
      text += ''' ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + left_arg + " + " + right_arg + ''';
'''
      # This sum node is on next layer
      new_layer_nodes.append(sum_var)
      node += 1
    
    # Out of while loop 
    # < 2 nodes left to sum in this node
    if len(layer_nodes) == 1:
      # One node left
      the_arg = layer_nodes.pop(0)
      the_t = var_2_type[the_arg]
      sum_t = the_t     
      sum_var = "sum_layer" + str(layer) + "_node" + str(node)
      var_2_type[sum_var] = sum_t
      text += ''' // Odd node in layer
  ''' + sum_t + ''' ''' + sum_var + ''';
  ''' + sum_var + ''' = ''' + the_arg + ''';
  '''
      # This sum node is on next layer
      new_layer_nodes.append(sum_var)
      node += 1
      
    
    # WHILE
    if len(new_layer_nodes) >= 2:
      # Continue
      layer_nodes = new_layer_nodes
      layer += 1
    else:
      # DONE
      break;
  
  # Done with outer layer while loop
    
  # Do return
  return_var = "sum_layer" + str(layer) + "_node" + str(node-1)
  return_t = var_2_type[return_var]
  text += '''
  ''' + "// Return" + '''
  ''' + return_t + ''' rv;
  rv = ''' + return_var + ''';
  return rv;
}
'''
  
  
  return text 
  #print text
  #sys.exit(-1)    
  
  
  
# 128 LLs in own code
# 192 lls as VHDL
# TODO: Is this bad/broken? test edge cases
def GET_BIN_OP_DIV_UINT_N_C_CODE(partially_complete_logic, out_dir, parser_state):  
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  max_input_width = max(left_width,right_width)
  resized_prefix = "uint" + str(max_input_width)
  resized_t = resized_prefix + "_t"
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = "uint" + str(output_width)
  
  text = ""
  
  text += '''
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b / ''' + str(right_width) + '''b div
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  // Resize
  ''' + resized_t + ''' left_resized;
  left_resized = left;
  ''' + resized_t + ''' right_resized;
  right_resized = right;
  
  // Output
  ''' + resized_t + ''' output;
  output = 0;
  // Remainder
  ''' + resized_t + ''' remainder;
  remainder = 0;
  uint1_t new_remainder0; 
  

  /*
  UNROLL THIS
  remainder := 0
  -- Where n is number of bits in left           
  for i := n - 1 .. 0 do     
    -- Left-shift remainder by 1 bit     
    remainder := remainder << 1
    -- Set the least-significant bit of remainder
    -- equal to bit i of the numerator
    remainder(0) := left(i)       
    if remainder >= right then
      remainder := remainder - right
      output(i) := 1
    end
  end 
  */
  '''
  
  for i in range(max_input_width-1, -1,-1):
    text += '''
  // Bit ''' + str(i) + '''
  new_remainder0 = ''' + resized_prefix + '''_''' + str(i) + '''_''' + str(i) + '''(left);
  remainder = ''' + resized_prefix + '''_uint1(remainder, new_remainder0);       
  if(remainder >= right)
  {
    remainder = remainder - right;
    // Set output(i)=1
    output = ''' + output_prefix + '''_uint1_''' + str(i) + '''(output, 1);
  }'''

  text += '''
  return output;
}'''
  
  #print(text)
  #sys.exit(-1)
  
  return text 
    
# TODO do something better than absolute value uint division and sign correction
def GET_BIN_OP_DIV_INT_N_C_CODE(partially_complete_logic, out_dir, parser_state):  
  left_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[0]]
  right_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.inputs[1]]
  output_t = partially_complete_logic.wire_to_c_type[partially_complete_logic.outputs[0]]
  left_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, left_t)
  right_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, right_t)
  max_input_width = max(left_width,right_width)
  resized_prefix = "int" + str(max_input_width)
  unsigned_resized_prefix = "u"+resized_prefix #"uint" + str(max_input_width-1)
  resized_t = resized_prefix + "_t"
  unsigned_resized_t = unsigned_resized_prefix + "_t"
  output_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, output_t) 
  output_prefix = "int" + str(output_width)
  
  text = ""
  
  text += '''
#include "intN_t.h"
#include "uintN_t.h"
#include "''' + BIT_MANIP_HEADER_FILE + '''"

// ''' + str(left_width) + '''b / ''' + str(right_width) + '''b div
''' + output_t + ''' ''' + partially_complete_logic.func_name + '''(''' + left_t + ''' left, ''' + right_t + ''' right)
{
  
  // Record sign bits
  uint1_t l_signed = '''+resized_prefix+"_"+str(left_width-1)+'''_'''+str(left_width-1)+'''(left);
  uint1_t r_signed = '''+resized_prefix+"_"+str(right_width-1)+'''_'''+str(right_width-1)+'''(right);

  // Resize to unsigned values of same width 
  ''' + unsigned_resized_t + ''' left_resized = '''+resized_prefix+'''_abs(left);
  ''' + unsigned_resized_t + ''' right_resized = '''+resized_prefix+'''_abs(right);

  // Do div on uints
  ''' + unsigned_resized_t + ''' unsigned_result = left_resized / right_resized;

  // Adjust sign
  ''' + output_t + ''' output = unsigned_result;
  if(l_signed ^ r_signed)
  {
    output = -unsigned_result;
  }

  return output;
}'''
  
  #print(text)
  #sys.exit(-1)
  
  return text
  
