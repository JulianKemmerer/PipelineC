#!/usr/bin/env python
import sys
import os
from pycparser import c_parser, c_ast, c_generator
import copy
import pickle
import math
import hashlib
import shlex
import subprocess
import signal
from subprocess import Popen, PIPE
from collections import OrderedDict

import VHDL
import SW_LIB
import SYN

TRIM_COLLAPSE_LOGIC = True # Flag to reduce duplicate wires, unused modules, False for debug

RETURN_WIRE_NAME = "return_output"
SUBMODULE_MARKER = "____" # Hacky, need to be something unlikely as wire name
CONST_PREFIX="CONST_"
CLOCK_ENABLE_NAME="CLOCK_ENABLE"
MUX_LOGIC_NAME="MUX"
UNARY_OP_LOGIC_NAME_PREFIX="UNARY_OP"
BIN_OP_LOGIC_NAME_PREFIX="BIN_OP"
CONST_REF_RD_FUNC_NAME_PREFIX = "CONST_REF_RD"
VAR_REF_ASSIGN_FUNC_NAME_PREFIX="VAR_REF_ASSIGN"
VAR_REF_RD_FUNC_NAME_PREFIX = "VAR_REF_RD"
CAST_FUNC_NAME_PREFIX = "CAST"
BOOL_C_TYPE = "uint1_t"
VHDL_FUNC_NAME = "__vhdl__"

# Unary Operators
UNARY_OP_NOT_NAME = "NOT"

# Binary operators
BIN_OP_GT_NAME = "GT"
BIN_OP_GTE_NAME = "GTE"
BIN_OP_LT_NAME = "LT"
BIN_OP_LTE_NAME = "LTE"
BIN_OP_PLUS_NAME = "PLUS"
BIN_OP_MINUS_NAME = "MINUS"
BIN_OP_NEQ_NAME = "NEQ"
BIN_OP_EQ_NAME = "EQ"
BIN_OP_AND_NAME = "AND" # Ampersand? Nah, look like we got pointers round here?
BIN_OP_OR_NAME="OR"
BIN_OP_XOR_NAME = "XOR"
BIN_OP_SL_NAME = "SL"
BIN_OP_SR_NAME = "SR"
BIN_OP_MOD_NAME = "MOD"
BIN_OP_MULT_NAME = "MULT"
BIN_OP_DIV_NAME = "DIV"

# TAKEN FROM https://github.com/eliben/pycparser/blob/c5463bd43adef3206c79520812745b368cd6ab21/pycparser/__init__.py
def preprocess_file(filename, cpp_path='cpp', cpp_args=''):
  """ Preprocess a file using cpp.
  filename:
  Name of the file you want to preprocess.
  cpp_path:
  cpp_args:
  Refer to the documentation of parse_file for the meaning of these
  arguments.
  When successful, returns the preprocessed file's contents.
  Errors from cpp will be printed out.
  """
  path_list = [cpp_path]
  if isinstance(cpp_args, list):
    path_list += cpp_args
  elif cpp_args != '':
    path_list += [cpp_args]

  # Include output directory, and other generated output dir
  if os.path.isdir(SYN.SYN_OUTPUT_DIRECTORY):    
    path_list += ["-I" + SYN.SYN_OUTPUT_DIRECTORY]
  for header_dir in SW_LIB.GENERATED_HEADER_DIRS:
    # Include the header dir - maybe future wanted idk?
    path_str = SYN.SYN_OUTPUT_DIRECTORY + "/" + header_dir
    path_list += ["-I" + path_str]
    if os.path.exists(path_str):
      # But also anything else? idk hacky
      for thing in os.listdir(path_str):
        #os.isdir wasnt working?
        thing_path = path_str + "/" + thing
        isdir = True
        try:
          os.listdir(thing_path)
        except:
          isdir = False
        if isdir:
          path_list += ["-I" + thing_path]
  # Also include src files in git root dir
  dir_path = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
  path_list += ["-I" + dir_path+"/../"]        
  
  #print(path_list)
    
  # Finally the file
  path_list += [filename]

  try:
    # Note the use of universal_newlines to treat all newlines
    # as \n for Python's purpose
    #
    pipe = Popen(   path_list,
    stdout=PIPE,
    universal_newlines=True)
    text = pipe.communicate()[0]
  except OSError as e:
    raise RuntimeError("Unable to invoke 'cpp'.  " +
    'Make sure its path was passed correctly\n' +
    ('Original error: %s' % e))
  except Exception as e:
    print("Something went wrong preprocessing:")
    print("File:",filename)
    raise e

  return text
    

def preprocess_text(text, cpp_path='cpp'):
  """ Preprocess a file using cpp.
        filename:
            Name of the file you want to preprocess.
        cpp_path:
        cpp_args:
            Refer to the documentation of parse_file for the meaning of these
            arguments.
        When successful, returns the preprocessed file's contents.
        Errors from cpp will be printed out.
  """
    
  path_list = [cpp_path]
  
  # Include output directory, and other generated output dir
  if os.path.isdir(SYN.SYN_OUTPUT_DIRECTORY):    
    path_list += ["-I" + SYN.SYN_OUTPUT_DIRECTORY]
  for header_dir in SW_LIB.GENERATED_HEADER_DIRS:
    path_list += ["-I" + SYN.SYN_OUTPUT_DIRECTORY + "/" + header_dir]
  
  # Finally read from std in
  path_list += ["-"] # TO read from std in

  try:
    # Note the use of universal_newlines to treat all newlines
    # as \n for Python's purpose
    #
    #print path_list
    pipe = Popen(   path_list,
            stdout=PIPE,
            stdin=PIPE,
                        universal_newlines=True)
        # Send in C text and get output
    #print "cpping..."
    #print "TEXT:",text
    text = pipe.communicate(input=text)[0]
  except OSError as e:
    raise RuntimeError("Unable to invoke 'cpp'.  " +
      'Make sure its path was passed correctly\n' +
      ('Original error: %s' % e))

  return text

def GET_SHELL_CMD_OUTPUT(cmd_str,cwd="."):
  # Kill pid after 
  process = subprocess.Popen(cmd_str, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd)
  output_text = str(process.stdout.read().decode(encoding="utf-8",errors="replace"))
  # For some reason vivado likes to stay alive? Be sure to kill?
  os.kill(process.pid, signal.SIGTERM)
  process.wait()
  if process.returncode != 0:
    print("Command failed:",cmd_str)
    print(cmd_str)
    print(output_text)
    sys.exit(-1)

  return output_text
  
# gcc -fpreprocessed -dD -E main.c
def READ_FILE_REMOVE_COMMENTS(c_filename):
  cmd = "gcc -E -fpreprocessed -dD " + c_filename
  return GET_SHELL_CMD_OUTPUT(cmd)
 
# Use cpp -MM -MG to parse the #include tree and get all files
# that need to be code gen'd again
# DOES NOT INCLUDE to-be-generated missing files
def GET_INCLUDED_FILES(c_filename):
  cmd = "cpp -MM -MG " + c_filename
  include_str = GET_SHELL_CMD_OUTPUT(cmd)
  include_str = include_str.replace("\\\n"," ")
  
  '''
main.o: main.c examples/aws-fpga-dma/aws_fpga_dma.c \
 examples/aws-fpga-dma/../../axi.h examples/aws-fpga-dma/../../uintN_t.h \
 examples/aws-fpga-dma/dma_msg_hw.c examples/aws-fpga-dma/dma_msg.h \
 examples/aws-fpga-dma/work_hw.c examples/aws-fpga-dma/work.h \
 in_msg_clock_crossing.h out_msg_clock_crossing.h
  '''
  # shlex.split('-o 1 --long "Some long string"')
  # ['-o', '1', '--long', 'Some long string']
  toks = shlex.split(include_str)
  #print toks[1:]
  files = toks[1:]
  existing_files = []
  for f in files:
    if os.path.exists(f):
      existing_files.append(f)

  #sys.exit(-1)
  return existing_files  
    

def casthelp(arg):
  try:
    print(arg)
  except:
    pass;
  
  try:
    arg.show()
  except:
    pass;
  
  try:  
    print(dir(arg))
  except:
    pass; 
    
def LIST_UNION(self_a,b):
  # Ummm?
  if self_a == b:
    return self_a
  
  #return list( set().union(*[a,b]) )
  # uhh faster?
  self_a.extend(b)
  return list(set(self_a))
  
def C_AST_VAL_UNIQUE_KEY_DICT_MERGE(self_d1,d2):
  # uh?
  if self_d1 == d2:
    return self_d1
  
  for key in d2:
    if key in self_d1:
      v1 = self_d1[key]
      v2 = d2[key]
      if C_AST_NODE_COORD_STR(v1) != C_AST_NODE_COORD_STR(v2):
        print("C_AST_VAL_UNIQUE_KEY_DICT_MERGE Dicts aren't unique:",self_d1,d2)
        print("key", key)
        print("v1",C_AST_NODE_COORD_STR(v1))
        print("v2",C_AST_NODE_COORD_STR(v2))
        print(0/0)
        sys.exit(-1)
  
  # Do merge with dict methods
  rv = self_d1
  rv.update(d2)
  
  return rv
  
  
def LIST_VAL_UNIQUE_KEY_DICT_MERGE(self_d1,d2):
  # Uhhh?
  if self_d1 == d2:
    return self_d1
  
  for key in d2:
    if key in self_d1:
      v1 = self_d1[key]
      v2 = d2[key]
      if str(v1) != str(v2):
        print("List val dicts aren't unique:",self_d1,d2)
        print("key", key)
        print("v1",v1)
        print("v2",v2)
        print(0/0)
        sys.exit(-1)
        
        
  # Do merge with dict methods
  rv = self_d1

  rv.update(d2)
  
  return rv


def UNIQUE_KEY_DICT_MERGE(self_d1,d2):
  # Uhh?
  if self_d1 == d2:
    return self_d1
  
  # Check that are unique
  for key in d2:
    if key in self_d1:
      v1 = self_d1[key]
      v2 = d2[key]
      if v1 != v2:
        print("Dicts aren't unique:",self_d1,d2)
        print("key", key)
        print("v1",v1)
        print("v2",v2)
        print(0/0)
        sys.exit(-1)
    #except:
    # pass
        
  # Do merge with dict methods
  rv = self_d1
  
  rv.update(d2)
  
  return rv
  
def DICT_SET_VALUE_MERGE(self_d1,d2):
  rv = self_d1
  for key in d2:
    if key in self_d1:
      # Result is union of two sets
      rv[key] = self_d1[key]|d2[key]
    else:
      rv[key] = d2[key]
      
  return rv   


class Logic:
  def __init__(self):
    
    ####### MODIFY DEEP COPY + MERGES TOO
    #
    #~
    #     ~~~~~
    #~~~~~~~~~~~~~
    #~~~~  Zero plus zero is the lord's work ^^^^^^
    # ``            `````````
    # of Montreal - St. Sebastian    
    
    # FOR LOGIC IMPLEMENTED IN C THE STRINGS MUST BE C SAFE
    # (inst name adjust is after all the parsing so dont count SUBMODULE_MARKER)    
    self.func_name = None # Function name
    # My containing func names (could be used in multiple places
    self.containing_funcs = set()
    self.variable_names=set() # Unordered set original variable names  
    self.wires=set()  # Unordered set ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
    self.clock_enable_wires = [] # Over time, nesting ifs create more entries in list
    self.feedback_vars = set() # Vars pragmad to be combinatorial feedback wires
    self.inputs=[] # Ordered list of inputs ["a","b"] 
    self.outputs=[] # Ordered list of outputs ["return"]
    self.state_regs = dict() # name -> state reg info
    self.uses_nonvolatile_state_regs = False
    self.submodule_instances = dict() # instance name -> logic func_name
    self.c_ast_node = None
    # Is this logic a c built in C function?
    self.is_c_built_in = False
    # Is this logic implemented as a VHDL function (non-pipelineable 0 clk logic, probably 0LLs)
    self.is_vhdl_func = False
    # Is this logic implemented as a VHDL expression (also 0 clk)
    self.is_vhdl_expr = False
    # Is this logic completely replaced with vhdl module text? (non-pipelineable global func like)
    self.is_vhdl_text_module = False
    
    # Mostly for c built in C functions
    self.submodule_instance_to_c_ast_node = dict()
    self.submodule_instance_to_input_port_names = dict()
    self.ref_submodule_instance_to_input_port_driven_ref_toks = dict()
    self.ref_submodule_instance_to_ref_toks = dict()
    
    # Python graph example was dict() of strings so this
    # string based wire naming makes Pythonic sense.
    # I think pointers would work better - constant strings are the pointer?
    # Wire names with a dot means sub module connection
    # func0.a  is a port on the func0 instance
    # Connections are given as two lists "drives" and "driven by"
    self.wire_drives = dict() # wire_name -> set([driven,wire,names])
    self.wire_driven_by = dict() # wire_name -> driving wire
    
    # To keep track of C execution over time in logic graph,
    # each assignment assigns to a renamed variable, renamed
    # variables keep execution order
    # Need to keep dicts for variable names
    self.wire_aliases_over_time = dict() # orig var name -> [list,of,renamed,wire,names] # Further in list is further in time
    self.alias_to_orig_var_name = dict() # alias -> orig var name
    self.alias_to_driven_ref_toks = dict() # alias -> [ref,toks]
    
    # Need to look up types by wire name
    # wire_to_c_type[wire_name] -> c_type_str
    self.wire_to_c_type = dict()
    
    # For timing, delay integer units (tenths of nanosec probably)
    # this is populated by vendor tool
    self.delay = None
    
    # Save C code text for later
    self.c_code_text = None
    
    # Init constant clock enable stuff
    self.wires.add(CLOCK_ENABLE_NAME)
    self.clock_enable_wires.append(CLOCK_ENABLE_NAME)
    self.wire_to_c_type[CLOCK_ENABLE_NAME] = BOOL_C_TYPE
  
  
  # Help!
  def DEEPCOPY(self):
    rv = Logic()
    rv.func_name = self.func_name
    rv.variable_names = set(self.variable_names)
    rv.wires = set(self.wires)  # ["a","b","return"] wire names (renamed variable regs), includes inputs+outputs
    rv.inputs = self.inputs[:] #["a","b"]
    rv.outputs = self.outputs[:] #["return"]
    rv.state_regs = dict(self.state_regs) #self.DEEPCOPY_DICT_COPY(self.state_regs)
    rv.feedback_vars = set(self.feedback_vars)
    rv.uses_nonvolatile_state_regs = self.uses_nonvolatile_state_regs
    rv.submodule_instances = dict(self.submodule_instances) # instance name -> logic func_name all IMMUTABLE types?
    rv.c_ast_node = copy.copy(self.c_ast_node)
    rv.is_c_built_in = self.is_c_built_in
    rv.is_vhdl_func = self.is_vhdl_func
    rv.is_vhdl_expr = self.is_vhdl_expr
    rv.is_vhdl_text_module = self.is_vhdl_text_module
    rv.submodule_instance_to_c_ast_node = self.DEEPCOPY_DICT_COPY(self.submodule_instance_to_c_ast_node)  # dict(self.submodule_instance_to_c_ast_node) # IMMUTABLE types / dont care
    rv.submodule_instance_to_input_port_names = self.DEEPCOPY_DICT_LIST(self.submodule_instance_to_input_port_names)
    rv.wire_drives = self.DEEPCOPY_DICT_SET(self.wire_drives)
    rv.wire_driven_by = dict(self.wire_driven_by) # wire_name -> driving wire #IMMUTABLE
    rv.wire_aliases_over_time = self.DEEPCOPY_DICT_LIST(self.wire_aliases_over_time)
    rv.alias_to_orig_var_name = dict(self.alias_to_orig_var_name) #IMMUTABLE
    rv.alias_to_driven_ref_toks = self.DEEPCOPY_DICT_LIST(self.alias_to_driven_ref_toks) # alias -> [ref,toks]
    rv.wire_to_c_type = dict(self.wire_to_c_type) #IMMUTABLE
    rv.delay = self.delay
    rv.c_code_text = self.c_code_text
    rv.containing_funcs = set(self.containing_funcs)
    rv.ref_submodule_instance_to_input_port_driven_ref_toks = self.DEEPCOPY_DICT_LIST(self.ref_submodule_instance_to_input_port_driven_ref_toks)
    rv.ref_submodule_instance_to_ref_toks = self.DEEPCOPY_DICT_LIST(self.ref_submodule_instance_to_ref_toks)
    rv.clock_enable_wires = self.clock_enable_wires[:]
    
    return rv
    
  # Really, help! # Replace with deep copy?
  def DEEPCOPY_DICT_LIST(self, d):
    rv = dict()
    for key in d:
      rv[key] = d[key][:]
    return rv
    
  def DEEPCOPY_DICT_SET(self, d):
    rv = dict()
    for key in d:
      rv[key] = set(d[key])
    return rv
    
  def DEEPCOPY_DICT_COPY(self, d):
    rv = dict()
    for key in d:
      rv[key] = copy.copy(d[key])
    return rv
    
  # Merges logic_b into self
  # Returns none intentionally
  def MERGE_COMB_LOGIC(self,logic_b):     
    # Um...?
    if self == logic_b:
      return None
    
    # Func name must match if set
    if (self.func_name is not None) and (logic_b.func_name is not None):
      if self.func_name != logic_b.func_name:
        print("Cannot merge comb logic with mismatching func names!")
        print(self.func_name)
        print(logic_b.func_name)
      else:
        self.func_name = self.func_name
    # Otherwise use whichever is set
    elif self.func_name is not None:
      self.func_name = self.func_name
    else:
      self.func_name = logic_b.func_name
    
      
    # C built in status must match if set
    if (self.is_c_built_in is not None) and (logic_b.is_c_built_in is not None):
      if self.is_c_built_in != logic_b.is_c_built_in:
        print("Cannot merge comb logic with mismatching is_c_built_in !")
        print(self.func_name, self.is_c_built_in)
        print(logic_b.func_name, logic_b.is_c_built_in)
        sys.exit(-1)
      else:
        self.is_c_built_in = self.is_c_built_in
    # Otherwise use whichever is set
    elif self.is_c_built_in is not None:
      self.is_c_built_in = self.is_c_built_in
    else:
      self.is_c_built_in = logic_b.is_c_built_in
      
    # VHDL func status must match if set
    if (self.is_vhdl_func is not None) and (logic_b.is_vhdl_func is not None):
      if self.is_vhdl_func != logic_b.is_vhdl_func:
        print("Cannot merge comb logic with mismatching is_vhdl_func !")
        print(self.func_name, self.is_vhdl_func)
        print(logic_b.func_name, logic_b.is_vhdl_func)
        sys.exit(-1)
      else:
        self.is_vhdl_func = self.is_vhdl_func
    # Otherwise use whichever is set
    elif self.is_vhdl_func is not None:
      self.is_vhdl_func = self.is_vhdl_func
    else:
      self.is_vhdl_func = logic_b.is_vhdl_func
      
    # VHDL expression status must match if set
    if (self.is_vhdl_expr is not None) and (logic_b.is_vhdl_expr is not None):
      if self.is_vhdl_expr != logic_b.is_vhdl_expr:
        print("Cannot merge comb logic with mismatching is_vhdl_expr !")
        print(self.func_name, self.is_vhdl_expr)
        print(logic_b.func_name, logic_b.is_vhdl_expr)
        sys.exit(-1)
      else:
        self.is_vhdl_expr = self.is_vhdl_expr
    # Otherwise use whichever is set
    elif self.is_vhdl_expr is not None:
      self.is_vhdl_expr = self.is_vhdl_expr
    else:
      self.is_vhdl_expr = logic_b.is_vhdl_expr
      
    # VHDL text module status must match if set
    if (self.is_vhdl_text_module is not None) and (logic_b.is_vhdl_text_module is not None):
      if self.is_vhdl_text_module != logic_b.is_vhdl_text_module:
        print("Cannot merge comb logic with mismatching is_vhdl_text_module !")
        print(self.func_name, self.is_vhdl_text_module)
        print(logic_b.func_name, logic_b.is_vhdl_text_module)
        sys.exit(-1)
      else:
        self.is_vhdl_text_module = self.is_vhdl_text_module
    # Otherwise use whichever is set
    elif self.is_vhdl_text_module is not None:
      self.is_vhdl_text_module = self.is_vhdl_text_module
    else:
      self.is_vhdl_text_module = logic_b.is_vhdl_text_module
      
    # TODO refactor all the above copypasta
      
    # Absorb true values of using globals
    self.uses_nonvolatile_state_regs = self.uses_nonvolatile_state_regs or logic_b.uses_nonvolatile_state_regs
    
    # Merge sets
    self.wires = self.wires | logic_b.wires
    self.state_regs = UNIQUE_KEY_DICT_MERGE(self.state_regs, logic_b.state_regs)
    self.variable_names = self.variable_names | logic_b.variable_names
    self.feedback_vars = self.feedback_vars | logic_b.feedback_vars
    
    # I/O order matters - check that
    # If one is empty then thats fine
    if len(self.inputs) > 0 and len(logic_b.inputs) > 0:
      # Check for equal
      if self.inputs != logic_b.inputs:
        print("Cannot merge comb logic with mismatching inputs !")
        print(self.func_name, self.inputs)
        print(logic_b.func_name, logic_b.inputs)
        print(0/0)
        sys.exit(-1)
      else:
        self.inputs = self.inputs[:]
    else:
      # Default a
      self.inputs = self.inputs[:]
      if len(self.inputs) <= 0:
        self.inputs = logic_b.inputs[:]
    
    if len(self.outputs) > 0 and len(logic_b.outputs) > 0:
      # Check for equal
      if self.outputs != logic_b.outputs:
        print("Cannot merge comb logic with mismatching outputs !")
        print(self.func_name, self.outputs)
        print(logic_b.func_name, logic_b.outputs)
        sys.exit(-1)
      else:
        self.outputs = self.outputs[:]
    else:
      # Default a
      self.outputs = self.outputs[:]
      if len(self.outputs) <= 0:
        self.outputs = logic_b.outputs[:]
      
    
    # Merge dicts
    self.wire_to_c_type = UNIQUE_KEY_DICT_MERGE(self.wire_to_c_type,logic_b.wire_to_c_type)
    self.submodule_instances = UNIQUE_KEY_DICT_MERGE(self.submodule_instances,logic_b.submodule_instances)  
    self.wire_driven_by = UNIQUE_KEY_DICT_MERGE(self.wire_driven_by,logic_b.wire_driven_by)
    
    # WTF MERGE BUG?
    lens = len(self.wire_drives)+ len(logic_b.wire_drives)
    self.wire_drives = DICT_SET_VALUE_MERGE(self.wire_drives,logic_b.wire_drives)
    if lens > 0 and len(self.wire_drives) == 0:
      print("self.wire_drives",self.wire_drives)
      print("logic_b.wire_drives",logic_b.wire_drives)
      print("Should have at least",lens, "entries...")
      print("MERGE COMB self.wire_drives",self.wire_drives)
      print("WTF")
      sys.exit(-1)
    
    # C ast node values wont be == , manual check with coord str
    self.submodule_instance_to_c_ast_node = C_AST_VAL_UNIQUE_KEY_DICT_MERGE(self.submodule_instance_to_c_ast_node,logic_b.submodule_instance_to_c_ast_node)
    self.submodule_instance_to_input_port_names = LIST_VAL_UNIQUE_KEY_DICT_MERGE(self.submodule_instance_to_input_port_names,logic_b.submodule_instance_to_input_port_names)
    self.ref_submodule_instance_to_input_port_driven_ref_toks = LIST_VAL_UNIQUE_KEY_DICT_MERGE(self.ref_submodule_instance_to_input_port_driven_ref_toks,logic_b.ref_submodule_instance_to_input_port_driven_ref_toks)
    self.ref_submodule_instance_to_ref_toks = LIST_VAL_UNIQUE_KEY_DICT_MERGE(self.ref_submodule_instance_to_ref_toks, logic_b.ref_submodule_instance_to_ref_toks)
    
    # Also for both wire drives and driven by, remove wire driving self:
    # wire_driven_by
    new_wire_driven_by = dict()
    for driven_wire in self.wire_driven_by:
      # Filter out self driving
      driving_wire = self.wire_driven_by[driven_wire]
      if driving_wire != driven_wire:
        new_wire_driven_by[driven_wire] = driving_wire
    
    #print "new_wire_driven_by",new_wire_driven_by
    self.wire_driven_by = new_wire_driven_by
    
    # wire_drives
    new_wire_drives = dict()
    for driving_wire in self.wire_drives:
      driven_wires = self.wire_drives[driving_wire]
      new_driven_wires = set()
      for driven_wire in driven_wires:
        if driven_wire != driving_wire:
          new_driven_wires.add(driven_wire) 
      new_wire_drives[driving_wire] = new_driven_wires
    self.wire_drives=new_wire_drives
        
    '''   
    # If one node is null then use other
    if self.c_ast_node is None:
      self.c_ast_node = logic_b.c_ast_node
    if logic_b.c_ast_node is None:
      self.c_ast_node = self.c_ast_node
    '''
    # C ast must match if set
    if (self.c_ast_node is not None) and (logic_b.c_ast_node is not None):
      # For now its the same c ast node if its the same coord
      # If causes problems... abandon then
      if C_AST_NODE_COORD_STR(self.c_ast_node) != C_AST_NODE_COORD_STR(logic_b.c_ast_node):
        print("Cannot merge comb logic with mismatching c_ast_node!")
        print(self.func_name)
        print(logic_b.func_name)
        print(self.c_ast_node)
        print(logic_b.c_ast_node)
        print(0/0)
        sys.exit(-1)
      else:
        self.c_ast_node = self.c_ast_node
    # Otherwise use whichever is set
    elif self.c_ast_node is not None:
      self.c_ast_node = self.c_ast_node
    else:
      self.c_ast_node = logic_b.c_ast_node
    
    
    
    # Only way this makes sense with MERGE_SEQUENTIAL_LOGIC
    # Need to be equal per variable
    # List val merge should do the trick
    self.wire_aliases_over_time = LIST_VAL_UNIQUE_KEY_DICT_MERGE(self.wire_aliases_over_time, logic_b.wire_aliases_over_time)
    
    # Only one orig wire name per alias
    self.alias_to_orig_var_name = UNIQUE_KEY_DICT_MERGE(self.alias_to_orig_var_name,logic_b.alias_to_orig_var_name)
    self.alias_to_driven_ref_toks = UNIQUE_KEY_DICT_MERGE(self.alias_to_driven_ref_toks,logic_b.alias_to_driven_ref_toks) 
    
    # Code text keep whichever is set
    if (self.c_code_text is not None) and (logic_b.c_code_text is not None):
      if self.c_code_text != logic_b.c_code_text:
        print("Cannot merge comb logic with mismatching c_code_text!")
        print(self.c_code_text)
        print(logic_b.c_code_text)
      else:
        self.c_code_text = self.c_code_text
    # Otherwise use whichever is set
    elif self.c_code_text is not None:
      self.c_code_text = self.c_code_text
    else:
      self.c_code_text = logic_b.c_code_text
      
    # Clock enables need to be equal
    if self.clock_enable_wires != logic_b.clock_enable_wires:
      print("Mismatch clock enable wires merging parallel logic!")
      print(self.clock_enable_wires)
      print(logic_b.clock_enable_wires)
      sys.exit(-1)      
    
    return None
      
  
  # Function to merge logic with implied execution order
  # Merges with self
  # Intentionally returns None
  def MERGE_SEQ_LOGIC(self, second_logic):    
    # only need to do specifically sequential part of merge here
    # We call COMB merge after adjusting for sequential
    # Um...?
    if self == second_logic:
      return None
    
    #print "===="
    #print "self.wire_drives", self.wire_drives 
    #print "self.wire_driven_by", self.wire_driven_by 
    #print "second_logic.wire_drives", second_logic.wire_drives 
    #print "second_logic.wire_driven_by", second_logic.wire_driven_by 

    # Driving wires need to reflect over time
    # Last alias from first logic replaces original wire name in second logic
    # self.wire_drives = dict() # wire_name -> set(driven,wire,names])
    for orig_var in self.wire_aliases_over_time:
      # And the var drives second_logic 
      if orig_var in second_logic.wire_drives:
        # First logic has aliases for orig var
        # Second logic has record of the orig var driving things
        # Both first and second logic should have same driven wies
        first_driven_wires = set()
        if orig_var in self.wire_drives:
          first_driven_wires = self.wire_drives[orig_var]
        second_driven_wires = set()
        if orig_var in second_logic.wire_drives:
          second_driven_wires = second_logic.wire_drives[orig_var]
          
        sorted_first_driven_wires = sorted(first_driven_wires)
        sorted_second_driven_wires = sorted(second_driven_wires)
        # Was the second logic actually refering to something different?
        if sorted_first_driven_wires != sorted_second_driven_wires: 
          # If second just has extra then OK
          if len(sorted_first_driven_wires) < len(sorted_second_driven_wires):
            # Check for match, but not like a dummy?
            #for i in range(0, len(sorted_first_driven_wires)):
            # if sorted_first_driven_wires[i] != sorted_second_driven_wires[i]:
            for sorted_first_driven_wire in sorted_first_driven_wires:
              if sorted_first_driven_wire not in sorted_second_driven_wires:
                print("first driven wire:", sorted_first_driven_wire,"was not in second logic driven wires? was removed? wtf?")
                print("first:",sorted_first_driven_wires)
                print("second:", sorted_second_driven_wires)
                #print 0/0
                sys.exit(-1)
            # Got match, first is subset of second, update first to match second
            if len(second_driven_wires) > 0:
              self.wire_drives[orig_var] = second_driven_wires
            for second_driven_wire in second_driven_wires:
              self.wire_driven_by[second_driven_wire] = second_logic.wire_driven_by[second_driven_wire]
            
          else:
            # First has same or more, cant match second at this point
            print("orig_var",orig_var)
            aliases = self.wire_aliases_over_time[orig_var]
            print("first aliases",aliases)
            last_alias = aliases[len(aliases)-1]
            print("first logic last_alias",last_alias)
            print("self.wire_drives[orig_var]",first_driven_wires)
            print("second_logic.wire_drives[orig_var]",second_driven_wires)
            # Get the last alias for that var from first logic
            print("second aliases", second_logic.wire_aliases_over_time[orig_var])
            
            # If this last alias is not in the first logic 
            
            # If aliases over time already agree then no need 
            
            # And replace that wire in the 
            # second logic wire_drives key (not value)
            temp_value = set(second_logic.wire_drives[orig_var])
            # Delete orig var key
            second_logic.wire_drives.pop(orig_var, None)
            # Replace with last alias
            second_logic.wire_drives[last_alias] = temp_value
            print(last_alias," DRIVES ", temp_value)
            sys.exit(-1)
            
    
    
    # wire_driven_by can't have multiple drivers over time and
    # should error out in normal merge below

    # wire_aliases_over_time  
    # Do first+second first
    # If first logic has aliases over time
    for var_name in self.wire_aliases_over_time:
      if var_name in second_logic.wire_aliases_over_time:
        # And so does second
        # Merged value is first plus second
        first = self.wire_aliases_over_time[var_name]
        second = second_logic.wire_aliases_over_time[var_name]
        # Start with including first
        self.wire_aliases_over_time[var_name] = first[:]
        
        # Check that the aliases over time are equal 
        # in the period of time they share (the first logic)
        for i in range(0, len(first)):
          if first[i] != second[i]:
            print("At time index", i,"for orig variable name =", var_name,"the first and second logic do not agree:")
            print("First logic aliases over time:", first)
            print("Second logic aliases over time:", second)
            print(0/0)
            sys.exit(-1)
        
        # Equal in shared time so only append not shared part of second
        for i in range(len(first), len(second)):
          self.wire_aliases_over_time[var_name].append(second[i])
        #print "self.wire_aliases_over_time",self.wire_aliases_over_time
          
      else:
        # First only alias (second does not have alias)
        # Merged value is first only
        self.wire_aliases_over_time[var_name] = self.wire_aliases_over_time[var_name][:]
    # Then include wire_aliases_over_time ONLY from second logic
    for var_name in second_logic.wire_aliases_over_time:
      # And first logic does not
      if not(var_name in self.wire_aliases_over_time):
        # Merged value is just from second logic
        second = second_logic.wire_aliases_over_time[var_name]
        self.wire_aliases_over_time[var_name] = second[:]
    
    # To not error in normal MERGE_LOGIC below, first and second logic must have same 
    # resulting wire_aliases_over_time
    modified_second_logic = second_logic
    modified_second_logic.wire_aliases_over_time = self.wire_aliases_over_time
    # Then merge logic as normal
    self.MERGE_COMB_LOGIC(modified_second_logic)
    
    return None
    
  # Allow a wire not to be driven
  def WIRE_ALLOW_NO_DRIVEN_BY(self, wire, FuncLogicLookupTable):
    if wire in self.variable_names:
      return True
    if wire in self.inputs:
      return True
    if wire == CLOCK_ENABLE_NAME:
      return True
    if wire in self.state_regs and self.state_regs[wire].is_volatile:
      return True
    # Only output ports are allowed to not to be driven by something
    if (SUBMODULE_MARKER in wire):
      toks = wire.split(SUBMODULE_MARKER)
      submodule_inst = toks[0]
      # Uh if inst doesnt exist then problem....
      if submodule_inst not in self.submodule_instances:
        print("self.func_name", self.func_name)
        print("wire",wire)
        print("No submodule instance called", submodule_inst)
        print(0/0)
        sys.exit(-1)
      # Otherwise proceed checking for outputs
      submodule_func_name = self.submodule_instances[submodule_inst]
      if submodule_func_name not in FuncLogicLookupTable:
        print("self.func_name", self.func_name)
        print("wire",wire)
        print("No func def for sub", submodule_func_name)
        print(FuncLogicLookupTable)
        sys.exit(-1)
      submodule_logic = FuncLogicLookupTable[submodule_func_name]
      port_name = toks[1]
      if port_name in submodule_logic.outputs:
        return True
        
    return False
  
  # Allow a wire not to drive anything
  def WIRE_ALLOW_NO_DRIVES(self,wire,FuncLogicLookupTable):
    if wire in self.variable_names:
      return True
    if wire in self.inputs:
      return True
    if wire == CLOCK_ENABLE_NAME:
      return True
    if wire in self.outputs:
      return True
    if wire in self.state_regs:
      return True
    # Only clock enable and input ports are allowed to not drive anything
    if (SUBMODULE_MARKER in wire):
      toks = wire.split(SUBMODULE_MARKER)
      submodule_inst = toks[0]
      # Uh if inst doesnt exist then problem....
      if submodule_inst not in self.submodule_instances:
        print("self.func_name", self.func_name)
        print("wire",wire)
        print("No submodule instance called", submodule_inst)
        print(0/0)
        sys.exit(-1)
      # Otherwise proceed checking for inputs
      submodule_func_name = self.submodule_instances[submodule_inst]
      if submodule_func_name not in FuncLogicLookupTable:
        print("self.func_name", self.func_name)
        print("wire",wire)
        print("No func def for sub", submodule_func_name)
        print(FuncLogicLookupTable)
        sys.exit(-1)
      submodule_logic = FuncLogicLookupTable[submodule_func_name]
      port_name = toks[1]
      if port_name == CLOCK_ENABLE_NAME:
        return True
      if port_name in submodule_logic.inputs:
        return True      
        
    return False
    
  def WIRE_DO_NOT_COLLAPSE(self, wire):
    if wire in self.variable_names:
      return True
    if wire in self.inputs:
      return True
    if wire == CLOCK_ENABLE_NAME:
      return True
    if wire in self.outputs:
      return True
    if wire in self.state_regs:
      return True
    if wire in self.feedback_vars:
      return True
      
    # THIS SEEMS WRONG?
    # NEED TO BE ABLE TO COLLAPSE/TRIM SUBMODULES?
    #if (SUBMODULE_MARKER in wire):
    #  return True 
    
    return False
  
  def REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(self, wire, FuncLogicLookupTable):
    #print("REMOVE",self.func_name, "  ", wire)
    #print "DEBUG: Not removing", wire
    #return None
    
    # Stop recursion if reached special wire
    if self.WIRE_DO_NOT_COLLAPSE(wire):
      return
    
    self.wires.discard(wire)        
    self.wire_to_c_type.pop(wire, None)
    
    # Remove record of driving-wire driving wire
    #   This might also remove the driving-wire
    if wire in self.wire_driven_by:
      driving_wire = self.wire_driven_by[wire]
      all_driven_wires = []
      if driving_wire in self.wire_drives:
        all_driven_wires = self.wire_drives[driving_wire]
        all_driven_wires.discard(wire)
      if len(all_driven_wires) > 0:
        self.wire_drives[driving_wire] = all_driven_wires
      else:
        # Driving wire no longer drives anything, recurse to delete it too
        self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(driving_wire, FuncLogicLookupTable)
        #self.wire_drives.pop(driving_wire)
        
      # Remove record of wire being driven by driving-wire
      self.wire_driven_by.pop(wire, None)
      
    # Remove record of wire driving driven-wires
    if wire in self.wire_drives:
      driven_wires = self.wire_drives[wire]
      self.wire_drives.pop(wire, None)
      # And remove all the driven wires too
      for driven_wire in driven_wires:
        self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(driven_wire, FuncLogicLookupTable)
        
    # Is this wire a submodule port?
    if SUBMODULE_MARKER in wire:
      toks = wire.split(SUBMODULE_MARKER)
      if len(toks) > 2:
        print("What berries? Goji Berries - Rubik")
        sys.exit(-1)
      submodule_inst = toks[0]
      submodule_func_name = self.submodule_instances[submodule_inst]
      submodule_logic = FuncLogicLookupTable[submodule_func_name]
      
      # Skip ripping up vhdl text submodules modules
      if submodule_func_name == VHDL_FUNC_NAME:
        return
      
      # Do the output ports drive anything now? 
      # (know this output port wire doesnt)
      all_outputs_disconnected = True
      if len(submodule_logic.outputs) == 0:
        all_outputs_disconnected = False
      for output_port in submodule_logic.outputs:
        submodule_output_wire = submodule_inst + SUBMODULE_MARKER + output_port
        if submodule_output_wire in self.wire_drives:
          # Still drives something
          all_outputs_disconnected = False
      
      # Rip up the submodule
      if all_outputs_disconnected:
        # Rip up wires starting at its inputs
        for in_port in submodule_logic.inputs:
          submodule_input_wire = submodule_inst + SUBMODULE_MARKER + in_port
          if submodule_input_wire in self.wires:
            self.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(submodule_input_wire, FuncLogicLookupTable)
        # Finally remove submodule itself
        self.REMOVE_SUBMODULE(submodule_inst, submodule_logic.inputs)
        
  # Intentionally return None
  def REMOVE_SUBMODULE(self,submodule_inst, input_port_names):    
    # Remove from list of subs yo
    self.submodule_instances.pop(submodule_inst,None)   
    
    # Make list of wires that look like
    #   submodule_inst + SUBMODULE_MARKER
    # SHOULD ONLY BE INPUT AND OUTPUT WIRES + submodule name
    io_wires = set()
    in_wires = set()
    for input_port_name in input_port_names:
      in_wire = submodule_inst + SUBMODULE_MARKER + input_port_name
      io_wires.add(in_wire)
      in_wires.add(in_wire)
    out_wire = submodule_inst + SUBMODULE_MARKER + RETURN_WIRE_NAME
    io_wires.add(out_wire)
    
    
    # Fast
    # NOT DONE UNTIL AFTER TRY GET LOGIC self.submodule_instances.pop(submodule_inst)
    # NOT DONE UNTIL AFTER TRY GET LOGIC self.submodule_instance_to_c_ast_node.pop(submodule_inst)
    # NOT DONE UNTIL AFTER TRY GET LOGIC self.submodule_instance_to_input_port_names.pop(submodule_inst, None)
    self.ref_submodule_instance_to_input_port_driven_ref_toks.pop(submodule_inst, None)
    self.ref_submodule_instance_to_ref_toks.pop(submodule_inst, None)
    
    # Discard a few, or intersect for many?
    if len(io_wires) < len(self.wires):
      for io_wire in io_wires:
        self.wires.discard(io_wire)
    else:
      self.wires = self.wires - io_wires
        
    for io_wire in io_wires:
      self.wire_to_c_type.pop(io_wire, None)
    
    # Super sloo?
    
    # WIRE_DRIVES
    # Only output port can drive something
    # HOWEVER # NOT DONE UNTIL AFTER TRY GET LOGIC
    '''
    io_wire = out_wire
    # Output wire drives stuff
    driven_wires = self.wire_drives[io_wire]
    # Remove opposite direction here
    for driven_wire in driven_wires:
      self.wire_driven_by.pop(driven_wire)
    # Then remove original direction
    self.wire_drives.pop(io_wire)
    '''
    
    # WIRE DRIVEN BY
    # Only inputs 
    for in_wire in in_wires:
      # IO wire is driven by thing
      if in_wire in self.wire_driven_by:
        driving_wire = self.wire_driven_by[in_wire]
        # Remove io wire from opposite direction
        all_driven_wires = self.wire_drives[driving_wire]
        all_driven_wires.discard(in_wire)
        if len(all_driven_wires) > 0:
          self.wire_drives[driving_wire] = all_driven_wires
        else:
          self.wire_drives.pop(driving_wire,None)
        # Then remove original direction
        self.wire_driven_by.pop(in_wire, None)
    

    # Shouldnt need to remove wire aliases since submodule connnections dont make assignment aliases?

    return None
    
  def CAN_BE_SLICED(self):
    return not self.uses_nonvolatile_state_regs and len(self.feedback_vars)==0
      
  def SHOW(self):
    # Make adjency matrix out of all wires and submodule isnts and own 'wire'/node in network
    nodes = list(self.wires)
    for submodule_inst in self.submodule_instances:
      nodes.append(submodule_inst)
    sorted_nodes = sorted(nodes)
    num_nodes = len(sorted_nodes)
    adjacency_matrix = np.zeros((num_nodes,num_nodes), dtype=np.int)
    # Build labels
    labels_dict = make_label_dict(sorted_nodes)
    rev_labels_dict = make_rev_label_dict(sorted_nodes)
    
    # Populate adjaceny matrix 
    for wire in self.wire_drives:
      driver_num = rev_labels_dict[wire]
      driven_wires = self.wire_drives[wire]
      
      # Get what a submodule inst form this wire would look like
      driving_submodule_inst_name = None
      if SUBMODULE_MARKER in wire:
        toks = wire.split(SUBMODULE_MARKER)
        inst_name = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
        if inst_name in self.submodule_instances:
          driving_submodule_inst_name = inst_name
      
      # Do driven wires
      for driven_wire in driven_wires:
        driven_num = rev_labels_dict[driven_wire]
        adjacency_matrix[driver_num,driven_num] = 1
        
        # Get what a submodule inst form this driven wire would look like
        driven_submodule_inst_name = None
        if SUBMODULE_MARKER in driven_wire:
          toks = driven_wire.split(SUBMODULE_MARKER)
          inst_name = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
          if inst_name in self.submodule_instances:
            driven_submodule_inst_name = inst_name
          
        # Assign IO for submodule insts
        if not(driving_submodule_inst_name is None):
          # Mus tbe output add common driver from submodule inst to output driver wire
          driving_submodule_node_num = rev_labels_dict[driving_submodule_inst_name]
          adjacency_matrix[driving_submodule_node_num,driver_num] = 1
        # Assign IO for submodule insts
        if not(driven_submodule_inst_name is None):
          # Msut be input
          # Add common inst driven by driver wire
          driven_submodule_node_num = rev_labels_dict[driven_submodule_inst_name]
          adjacency_matrix[driven_num,driven_submodule_node_num] = 1        
        
        
    show_graph_with_labels(adjacency_matrix, labels_dict)
      
      
    

# Thanks stack overflow
#https://stackoverflow.com/questions/29572623/plot-networkx-graph-from-adjacency-matrix-in-csv-file
def show_graph_with_labels(adjacency_matrix, mylabels):
    import matplotlib.pyplot as plt
    import networkx as nx
    import numpy as np
    rows, cols = np.where(adjacency_matrix == 1)
    edges = list(zip(rows.tolist(), cols.tolist()))
    gr = nx.Graph()
    gr.add_edges_from(edges)
    nx.draw(gr, node_size=500, labels=mylabels, with_labels=True)
    plt.show()
    
def make_label_dict(labels):
    l = {}
    for i, label in enumerate(labels):
        l[i] = label
    return l
def make_rev_label_dict(labels):
    l = {}
    for i, label in enumerate(labels):
        l[label] = i
    return l   

  
def WIRE_IS_CONSTANT(wire):
  new_wire = wire
  
  # Also split on last submodule marker
  toks = new_wire.split(SUBMODULE_MARKER)
  last_tok = toks[len(toks)-1]
  
  # Hey - this is dumb
  rv = last_tok.startswith(CONST_PREFIX) and not last_tok.startswith(CONST_REF_RD_FUNC_NAME_PREFIX+"_") and not last_tok.startswith(CONST_PREFIX+BIN_OP_SL_NAME + "_") and not last_tok.startswith(CONST_PREFIX+BIN_OP_SR_NAME + "_")
  if (CONST_PREFIX in wire) and not(rv) and not(CONST_REF_RD_FUNC_NAME_PREFIX+"_" in wire) and not(CONST_PREFIX+BIN_OP_SL_NAME+"_" in wire) and not(CONST_PREFIX+BIN_OP_SR_NAME+"_" in wire):
    print("WHJAT!?")
    print("wire",wire)
    print("new_wire", new_wire)
    print("WIRE_IS_CONSTANT   but is not?")
    print(0/0)
    sys.exit(-1) 
  
  return rv
  

def WIRE_IS_SUBMODULE_PORT(wire, logic):
  # Remove last tok, should be port name 
  toks = wire.split(SUBMODULE_MARKER)
  possible_submodule_inst_name = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
  
  # Check port name too?
  # No for now?
  return possible_submodule_inst_name in logic.submodule_instances
  
def WIRE_IS_VHDL_EXPR_SUBMODULE_INPUT_PORT(wire, Logic, parser_state):
  if SUBMODULE_MARKER in wire:
    toks = wire.split(SUBMODULE_MARKER)
    submodule_inst_name = toks[0]
    port_name = toks[1]
    submodule_func_name = Logic.submodule_instances[submodule_inst_name]
    submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
    if submodule_logic.is_vhdl_expr and (port_name in submodule_logic.inputs):
      return True
  return False
  
def WIRE_IS_VHDL_FUNC_SUBMODULE_INPUT_PORT(wire, Logic, parser_state):
  if SUBMODULE_MARKER in wire:
    toks = wire.split(SUBMODULE_MARKER)
    submodule_inst_name = toks[0]
    port_name = toks[1]
    submodule_func_name = Logic.submodule_instances[submodule_inst_name]
    submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
    if submodule_logic.is_vhdl_func and (port_name in submodule_logic.inputs):
      return True
  return False

def BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(containing_func_logic, submodule_inst, parser_state): 
  #print "containing_func_logic.func_name, submodule_inst"
  #print containing_func_logic.func_name, "|", submodule_inst
  #print "====================================================================================="
  # Construct a fake 'submodule_logic' with correct name, inputs, outputs
  submodule_logic = Logic()
  submodule_logic.is_c_built_in = True
  # Look up logic name for the submodule instance
  #print "containing_func_logic.func_name",containing_func_logic.func_name
  submodule_logic_name = containing_func_logic.submodule_instances[submodule_inst]
  #print "submodule_inst",submodule_inst
  #print "submodule_logic_name",submodule_logic_name
  submodule_logic.func_name = submodule_logic_name
  #print "...",submodule_logic.func_name
  
  # CONST refs are vhdl funcs
  if submodule_logic_name.startswith(CONST_REF_RD_FUNC_NAME_PREFIX):
    submodule_logic.is_vhdl_func = True
    # But can also be VHDL expressions if the feeling is right
    driven_ref_toks_list = containing_func_logic.ref_submodule_instance_to_input_port_driven_ref_toks[submodule_inst]
    # Just one input
    if len(driven_ref_toks_list) == 1:
      driven_ref_toks = driven_ref_toks_list[0]
      # Driving the base variable
      if len(driven_ref_toks) == 1:
        submodule_logic.is_vhdl_func = False
        submodule_logic.is_vhdl_expr = True
  
  # Ports and types are specific to the submodule instance
  # Get data from c ast node
  c_ast_node = containing_func_logic.submodule_instance_to_c_ast_node[submodule_inst]
  submodule_logic.c_ast_node = c_ast_node
  
  # It looks like the c parser doesnt let you look up type from name...
  # Probably would be complicated
  # Lets manually do it.
  # 1) parse funtion param declartions in wire_to_c_type
  # 2) parse var decls to wire_to_c_type
  # 3) Look up driver of submodule to determine type
  
  # Assume children list is is order of args
  input_names = []
  if submodule_inst in containing_func_logic.submodule_instance_to_input_port_names:
    input_names = containing_func_logic.submodule_instance_to_input_port_names[submodule_inst]
    submodule_logic.inputs += input_names
  else:
    for child in c_ast_node.children():
      name=child[0]
      input_names.append(name)
      submodule_logic.inputs.append(name) 
  
  # Try to get input type from port name in container logic
  # Fall back on type of driving wires
  # For each input wire look up type of driving wire
  input_types = []
  for input_name in input_names:  
    input_wire_name = submodule_inst + SUBMODULE_MARKER + input_name
    # First try input port type
    if input_wire_name in containing_func_logic.wire_to_c_type:
      c_type = containing_func_logic.wire_to_c_type[input_wire_name]
    else:
      # Fall back on driving wire
      #print logic.wire_driven_by
      driving_wire = containing_func_logic.wire_driven_by[input_wire_name]
      c_type = containing_func_logic.wire_to_c_type[driving_wire]
      
    # If driving wire c type is enum and this is BIN OP == then replace with input port wire with uint
    if (c_type in parser_state.enum_to_ids_dict) and (submodule_logic_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_EQ_NAME)):
      #print "submodule_logic_name", submodule_logic_name, "BIN_OP_EQ_NAME ENUM"
      #print "right enum"
      num_ids = len(parser_state.enum_to_ids_dict[c_type])
      width = int(math.ceil(math.log(num_ids,2)))
      c_type = "uint" + str(width) + "_t"
    
    # Record input info
    submodule_logic.wire_to_c_type[input_name] = c_type
    input_types.append(c_type)
    
  # Output wire is return wire 
  # Try to get output port type from containing logic
  # Fall back on type of what is driven
  output_port_name = RETURN_WIRE_NAME
  submodule_logic.outputs.append(RETURN_WIRE_NAME)
  output_wire_name = submodule_inst + SUBMODULE_MARKER + output_port_name
  c_type = None
  if output_wire_name in containing_func_logic.wire_to_c_type:
    c_type = containing_func_logic.wire_to_c_type[output_wire_name]
  else:
    # Fall back type of driven wire
    # By default assume type of driven wire if not yet driven
    if output_wire_name in containing_func_logic.wire_drives:
      driven_wires = containing_func_logic.wire_drives[output_wire_name]
      if len(driven_wires)==0 :
        print("Built in submodule not driving anthying?",submodule_inst)
        sys.exit(-1)
      c_type = containing_func_logic.wire_to_c_type[list(driven_wires)[0]]
    else:
      # Fine if vhdl func
      if submodule_logic.func_name != VHDL_FUNC_NAME:
        print("containing_func_logic.func_name",containing_func_logic.func_name)
        print("output_wire_name",output_wire_name)
        #print "containing_func_logic.wire_drives",containing_func_logic.wire_drives
        for wire in containing_func_logic.wire_drives:
          print(wire,"=>",containing_func_logic.wire_drives[wire])
        print("Input type to output type mapping assumption for built in submodule output ")
        print(submodule_logic.func_name)
        sys.exit(-1)   
  
  # Record output type
  if c_type is not None:
    submodule_logic.wire_to_c_type[output_port_name]=c_type 
  
  # Also do submodule instances for built in logic that is not raw VHDL
  if VHDL.C_BUILT_IN_FUNC_IS_RAW_HDL(submodule_logic_name,input_types): 
    # IS RAW VHDL
    pass
  # NOT RAW VHDL (assumed to be built from C code then)
  else:
    submodule_logic = BUILD_LOGIC_AS_C_CODE(submodule_inst, submodule_logic, parser_state, containing_func_logic)
      
  return submodule_logic
  
_other_partial_logic_cache = dict()
def BUILD_LOGIC_AS_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, parser_state, containing_func_logic):
  
  # Cache the other partial logic
  cache_tok = partially_complete_logic.func_name
  # SHOULDNT NEED INPUT TYPES SINCE FUNC NAME IS UNIQUE
    
  if cache_tok in _other_partial_logic_cache:
    other_partial_logic = _other_partial_logic_cache[cache_tok]
  else:
    out_dir = SYN.GET_OUTPUT_DIRECTORY(partially_complete_logic)
    # Get C code depending on function
    #print "BUILD_LOGIC_AS_C_CODE"
    #print "partially_complete_logic.func_name",partially_complete_logic.func_name
    #print "containing_func_logic.func_name",containing_func_logic.func_name
    #print "=================================================================="
    if partially_complete_logic.func_name.startswith(VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_"):
      c_code_text = SW_LIB.GET_VAR_REF_ASSIGN_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, containing_func_logic, out_dir, parser_state)
    elif partially_complete_logic.func_name.startswith(VAR_REF_RD_FUNC_NAME_PREFIX + "_"):
      c_code_text = SW_LIB.GET_VAR_REF_RD_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, containing_func_logic, out_dir, parser_state)  
    elif partially_complete_logic.func_name.startswith(CAST_FUNC_NAME_PREFIX + "_"):
      c_code_text = SW_LIB.GET_CAST_C_CODE(partially_complete_logic, containing_func_logic, out_dir, parser_state)  
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MULT_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_MULT_C_CODE(partially_complete_logic, out_dir, parser_state)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_DIV_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_DIV_C_CODE(partially_complete_logic, out_dir, parser_state)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MOD_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_MOD_C_CODE(partially_complete_logic, out_dir)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GT_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str=">")
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_GTE_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_GT_GTE_C_CODE(partially_complete_logic, out_dir, op_str=">=")
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LT_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_LT_LTE_C_CODE(partially_complete_logic, out_dir, op_str="<")
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_LTE_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_LT_LTE_C_CODE(partially_complete_logic, out_dir, op_str="<=")
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_PLUS_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_PLUS_C_CODE(partially_complete_logic, out_dir)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_MINUS_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_MINUS_C_CODE(partially_complete_logic, out_dir)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SL_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_SL_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, out_dir, containing_func_logic, parser_state)
    elif partially_complete_logic.func_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SR_NAME):
      c_code_text = SW_LIB.GET_BIN_OP_SR_C_CODE(partially_complete_logic_local_inst_name, partially_complete_logic, out_dir, containing_func_logic, parser_state)
    else:
      print("How to BUILD_LOGIC_AS_C_CODE for",partially_complete_logic.func_name, "?")
      sys.exit(-1) 
      
    # Use the c code to get the logic
    partially_complete_logic.c_code_text = c_code_text
    
    #print "c_code_text"
    #print c_code_text
    
    # And read logic
    #print "partially_complete_logic.
    fake_filename = partially_complete_logic.func_name + ".c"
    #print "fake_filename",fake_filename
    out_path = out_dir + "/" + fake_filename
      
    # Parse and return the only func def
    func_name = partially_complete_logic.func_name
    #print "... as C code...",partially_complete_logic.func_name
    
    preprocessed_c_code_text = preprocess_text(c_code_text)
    sw_func_name_2_logic = SW_LIB.GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(preprocessed_c_code_text, parser_state)
    # Merge into existing
    for sw_func_name in sw_func_name_2_logic:
      #print "sw_func_name",sw_func_name
      parser_state.FuncLogicLookupTable[sw_func_name] = sw_func_name_2_logic[sw_func_name]
    
    FuncLogicLookupTable = GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(c_code_text, fake_filename, parser_state, parse_body = True)
    
    # Get the other partial logic if it exists
    if not(func_name in FuncLogicLookupTable ):
      print("I cant find func name",func_name,"in the C code so far")
      print("c_code_text")
      print(c_code_text)
      print("=========")
      print("sw_func_name_2_logic")
      print(sw_func_name_2_logic)
      print("CHECK CODE PARSING autogenerated stuff?")
      sys.exit(-1)
    other_partial_logic = FuncLogicLookupTable[func_name]
    # CACHE THIS
    _other_partial_logic_cache[cache_tok] = other_partial_logic
  
  
  # Also needs built in flag from partial logic
  other_partial_logic.is_c_built_in = partially_complete_logic.is_c_built_in
  # Fix cast ndoe too
  other_partial_logic.c_ast_node = partially_complete_logic.c_ast_node
  
  # Combine two partial logics
  #print "partially_complete_logic.c_ast_node.coord", partially_complete_logic.c_ast_node.coord
  #print "other_partial_logic.c_ast_node.coord", other_partial_logic.c_ast_node.coord
  partially_complete_logic.MERGE_COMB_LOGIC(other_partial_logic)
  #print "merged_logic.c_ast_node.coord", merged_logic.c_ast_node.coord
  #print "merged_logic.func_name", merged_logic.func_name
  
  return partially_complete_logic
    

def GET_FUNC_NAME_LOGIC_LOOKUP_TABLE_FROM_C_CODE_TEXT(text, fake_filename, parser_state, parse_body):
  # Build function name to logic from func defs from files
  FuncLogicLookupTable = dict(parser_state.FuncLogicLookupTable)  #### Was deep copy Uh need this copy so bit manip/math funcs not directly in C text are accumulated over time wtf? TODO: Fix 
  func_defs = GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename)

  for func_def in func_defs:
    #print "...func def"
    # Each func def produces a single logic item
    parser_state.existing_logic=None
    driven_wire_names=[]
    prepend_text=""
    logic = C_AST_FUNC_DEF_TO_LOGIC(func_def, parser_state, parse_body)
    FuncLogicLookupTable[logic.func_name] = logic
  
  return FuncLogicLookupTable
  
    
# WHY CAN I NEVER REMEMBER DICT() IS NOT IMMUTABLE (AKA needs copy operator)
# BECAUSE YOU ARE A PIECE OF SHIT 

# Node needs context for variable renaming over time, can give existing logic
#_node_record = dict()
def C_AST_NODE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state):
  
  '''
  key = (str(c_ast_node), str(c_ast_node.coord), prepend_text)
  if key not in _node_record:
    _node_record[key] = 0
  _node_record[key] += 1
  if _node_record[key] > 1:
    print prepend_text, c_ast_node.coord, "AGAIN?", _node_record[key]
  ''' 
  
  # Cover logic as far up in c ast tree as possible
  # Each node will have function to deal with node type:
  # which may or may not recursively call this function.
  
  # C_AST nodes can represent pure structure logic
  
  if type(c_ast_node) == c_ast.Compound:
    return C_AST_COMPOUND_TO_LOGIC(c_ast_node, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Decl:
    return C_AST_DECL_TO_LOGIC(c_ast_node, prepend_text, parser_state)  
  elif type(c_ast_node) == c_ast.If:
    return C_AST_IF_TO_LOGIC(c_ast_node,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Return:
    return C_AST_RETURN_TO_LOGIC(c_ast_node, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.FuncCall:
    return C_AST_FUNC_CALL_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.BinaryOp:
    return C_AST_BINARY_OP_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.UnaryOp:
    return C_AST_UNARY_OP_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Constant:
    return C_AST_CONSTANT_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.ID:
    return C_AST_ID_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.StructRef or type(c_ast_node) == c_ast.ArrayRef:
    return C_AST_REF_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Assignment:
    return C_AST_ASSIGNMENT_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.For:
    return C_AST_FOR_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Cast:
    return C_AST_CAST_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.Pragma:
    return C_AST_PRAGMA_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state)
  elif type(c_ast_node) == c_ast.EmptyStatement:
    print("Unecessary empty statement - extra ';' ?", c_ast_node.coord)
    sys.exit(-1)
  else:
    #start here
    print("Animal Collective - The Purple Bottle")
    print("Cannot parse c ast node to logic:", c_ast_node.coord)
    print(c_ast_node)
    #casthelp(c_ast_node)
    #print "driven_wire_names=",driven_wire_names
    sys.exit(-1)
    
def C_AST_PRAGMA_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state):
  toks = c_ast_node.string.split(" ")
  
  # FEEDBACK WIRES
  if toks[0] == "FEEDBACK":
    var_name = toks[1]
    parser_state.existing_logic.feedback_vars.add(var_name)
    #print(c_ast_node)
  
  return parser_state.existing_logic
  
def C_AST_RETURN_TO_LOGIC(c_ast_return, prepend_text, parser_state):
  # Check for double return
  if RETURN_WIRE_NAME in parser_state.existing_logic.wire_driven_by:
    print("What, more than one return? Come on man don't make me sad...", str(c_ast_return.coord))
    sys.exit(-1) 
  
  # Return is just connection to wire
  # Since each logic blob is a C function
  # only one return per function allowed
  # connect variable wire name to "return"
  driven_wire_names=[RETURN_WIRE_NAME]
  prepend_text=""
  return_logic = C_AST_NODE_TO_LOGIC(c_ast_return.expr, driven_wire_names, prepend_text, parser_state)
  
  
  parser_state.existing_logic = return_logic
  # Connect the return logic node to this one
  return return_logic
  
def CONNECT_FINAL_STATE_WIRES(prepend_text, parser_state, c_ast_node):
  # Tie all state regs to state wire
  # Collpase struct ref hierarchy to get top most orig wire name nodes
  for state_reg in parser_state.existing_logic.state_regs:
    # Read ref_toks takes care of it
    ref_toks = (state_reg,)
    connect_logic = C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_node, [state_reg], prepend_text, parser_state)
    parser_state.existing_logic.MERGE_COMB_LOGIC(connect_logic)
    
  # Tie feedback wires to var like state regs
  for feedback_var in parser_state.existing_logic.feedback_vars:
    ref_toks = (feedback_var,)
    connect_logic = C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_node, [feedback_var], prepend_text, parser_state)
    parser_state.existing_logic.MERGE_COMB_LOGIC(connect_logic)  
    
  return parser_state.existing_logic

  
def GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref):
  if type(c_ast_structref.name) == c_ast.StructRef:
    names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref.name)
    names_list = names_list + [c_ast_structref.field.name]
    return names_list
  elif type(c_ast_structref.name) == c_ast.ID:
    name_wire = str(c_ast_structref.name.name)
    names_list = [name_wire, c_ast_structref.field.name]
    return names_list
  elif type(c_ast_structref.name) == c_ast.ArrayRef:
    names_list = GET_NAMES_LIST_FROM_ARRAYREF(c_ast_structref.name)
    names_list = names_list + [c_ast_structref.field.name]
    return names_list
  else:
    print("Need entry in GET_NAMES_LIST_FROM_STRUCTREF", end=' ') 
    casthelp(c_ast_structref.name)
    sys.exit(-1)
  
  return rv


  
def GET_LEAF_FIELD_NAME_FROM_STRUCTREF(c_ast_structref):
  names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
  return names_list[len(names_list)-1]
  
  
def GET_BASE_VARIABLE_NAME_FROM_STRUCTREF(c_ast_structref):
  names_list = GET_NAMES_LIST_FROM_STRUCTREF(c_ast_structref)
  return names_list[0]
    
def ORIG_VAR_NAME_TO_MOST_RECENT_ALIAS(orig_var_name, existing_logic):
  if existing_logic is not None:
    most_recent_alias = GET_MOST_RECENT_ALIAS(existing_logic, orig_var_name)
    return most_recent_alias
  else:
    return orig_var_name  

def C_AST_REF_TOKS_ARE_CONST(ref_toks):
  for ref_tok in ref_toks:
    # Constant array ref
    if type(ref_tok) == int:
      pass
    # Sanity check
    elif (type(ref_tok) == str) and (ref_tok=="*"):
      print("Using string variable ref tok when not aware, fix.")
      sys.exit(-1)
    # ID or struct ref
    elif type(ref_tok) == str:
      pass
    # Variable array ref
    elif isinstance(ref_tok, c_ast.Node):
      return False
    else:
      print("Whats this ref eh yo?", ref_tok, c_ast_node.coord)
      sys.exit(-1)
  return True
      
      
def C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(ref_toks, c_ast_node, parser_state):
  existing_logic = parser_state.existing_logic
  orig_var_name = ref_toks[0]
  id_str = ""
  for i in range(0, len(ref_toks)):
    ref_tok = ref_toks[i]
    # Constant array ref
    if type(ref_tok) == int:
      id_str += "[" + str(ref_tok) + "]"
    # ID or struct ref
    elif type(ref_tok) == str:
      if i == 0:
        # Base ID
        id_str += ref_tok
      else:
        # Struct ref
        id_str += "." + ref_tok
    # Variable array ref
    elif isinstance(ref_tok, c_ast.Node):
      id_str += "[*]"
    else:
      print("Whats this ref eh?", ref_tok, c_ast_node.coord)
      sys.exit(-1)
      
  
  # Alias will include location in src
  coord_str = C_AST_NODE_COORD_STR(c_ast_node)
  # Base name
  alias_base = id_str+"_"+coord_str
  
  # Return base without number appended?
  if orig_var_name in existing_logic.wire_aliases_over_time:
    aliases = existing_logic.wire_aliases_over_time[orig_var_name]
    if alias_base not in aliases:
      return alias_base
  
  # Check existing logic for alias
  # First one to try is "0"
  i=0
  alias = alias_base + "_" + str(i)
  if existing_logic is not None:
    if orig_var_name in existing_logic.wire_aliases_over_time:
      # Aliases exist, start i at last one
      aliases = existing_logic.wire_aliases_over_time[orig_var_name]
      last_alias = aliases[len(aliases)-1]
      last_num = int(last_alias.replace(alias_base+"_",""))
      i=last_num+1
      alias = alias_base + "_" + str(i)
      while alias in aliases:
        i=i+1
        alias = alias_base + "_" + str(i)
  
  return alias
  

def ORIG_WIRE_NAME_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(orig_wire_name, c_ast_node,  existing_logic):
  # Alias will include location in src
  coord_str = C_AST_NODE_COORD_STR(c_ast_node)
  # Base name
  alias_base = orig_wire_name+"_"+coord_str+"_"
  
  # Check existing logic for alias
  # First one to try is "0"
  i=0
  alias = alias_base+str(i)
  if existing_logic is not None:
    if orig_wire_name in existing_logic.wire_aliases_over_time:
      aliases = existing_logic.wire_aliases_over_time[orig_wire_name]
      while alias in aliases:
        i=i+1
        alias = alias_base+str(i)
  
  return alias

def C_AST_CONSTANT_TO_ORIG_WIRE_NAME(c_ast_node):
  return str(c_ast_node.value)
    
def GET_MOST_RECENT_ALIAS(logic,orig_var_name):
  if orig_var_name in logic.wire_aliases_over_time:
    aliases =  logic.wire_aliases_over_time[orig_var_name]
    last_alias = aliases[len(aliases)-1]
    return last_alias
  else:
    return orig_var_name

def GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(ref_toks, c_ast_node, parser_state):
  #print "=="
  #print "ref_toks",ref_toks
  var_dim_ref_tok_indices = []
  var_dims = []
  var_dim_iter_types = []
  curr_ref_toks = ref_toks[:]   
  # need at last 2 ref toks, array cant be in pos 0
  while len(curr_ref_toks) >= 2:
    #print "=="
    #print "curr_ref_toks",curr_ref_toks
    last_index = len(curr_ref_toks)-1
    last_tok = curr_ref_toks[last_index]
    if isinstance(last_tok, c_ast.Node):
      # is variable array dim
      # Pop off this last entry
      curr_ref_toks = curr_ref_toks[:last_index]
      # Get the array type
      c_array_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(curr_ref_toks, c_ast_node, parser_state)
      # Sanity check
      if not C_TYPE_IS_ARRAY(c_array_type):
        print("Oh no not an array?", c_array_type)
        sys.exit(-1)
      # Get the dims from the array
      #print "c_array_type",c_array_type
      elem_type,dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
      #print "elem_type",elem_type
      #print "dims",dims
      # Want last dim? 
      '''
      last_dim = dims[len(dims)-1]
      # Save
      var_dim_ref_tok_indices.append(last_index)
      var_dims.append(last_dim)   
      var_dim_iter_types.append("uint" + str(int(math.ceil(math.log(last_dim,2)))) + "_t")
      '''
      # Or wait want first dim?
      first_dim = dims[0]
      # Save
      var_dim_ref_tok_indices.append(last_index)
      var_dims.append(first_dim)    
      var_dim_iter_types.append("uint" + str(int(math.ceil(math.log(first_dim,2)))) + "_t")     
    else:
      # Pop off this entry
      curr_ref_toks = curr_ref_toks[:last_index]
      # Thats it
  
  # Have been reversed
  var_dim_ref_tok_indices.reverse()
  var_dims.reverse()
  var_dim_iter_types.reverse()
  
  #print "var_dim_ref_tok_indices, var_dims, var_dim_iter_types",var_dim_ref_tok_indices, var_dims, var_dim_iter_types
  
  return var_dim_ref_tok_indices, var_dims, var_dim_iter_types



def MAYBE_GLOBAL_STATE_REG_INFO_TO_LOGIC(maybe_state_reg_var, parser_state):
  # Regular globals
  # If has same name as global and hasnt been declared as (local) variable already
  if (maybe_state_reg_var in parser_state.global_state_regs) and (maybe_state_reg_var not in parser_state.existing_logic.variable_names):
    # Copy info into existing_logic
    parser_state.existing_logic.state_regs[maybe_state_reg_var] = parser_state.global_state_regs[maybe_state_reg_var]
    parser_state.existing_logic.wire_to_c_type[maybe_state_reg_var] = parser_state.global_state_regs[maybe_state_reg_var].type_name
    parser_state.existing_logic.variable_names.add(maybe_state_reg_var)      
    # Record using globals
    if not parser_state.existing_logic.state_regs[maybe_state_reg_var].is_volatile:
      parser_state.existing_logic.uses_nonvolatile_state_regs = True
      #print "rv.func_name",rv.func_name, rv.uses_nonvolatile_state_regs
    
  # Sanity check not using clock cross globals?
  # TODO: for other things like brams declared but not directly used?
  if maybe_state_reg_var in parser_state.clk_cross_var_info:
    print("Looks like you are using a clock crossing variable '", maybe_state_reg_var, "' directly instead of with READ and WRITE functions?")
    sys.exit(-1) 

  return parser_state.existing_logic


# If this works great, if not ill be so sad
# Sadness forever

def C_AST_ASSIGNMENT_TO_LOGIC(c_ast_assignment,driven_wire_names,prepend_text, parser_state):
  # Assume lhs can be evaluated as ref?
  lhs_ref_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(c_ast_assignment.lvalue, prepend_text, parser_state)
  lhs_orig_var_name = lhs_ref_toks[0] 


  FuncLogicLookupTable = parser_state.FuncLogicLookupTable
  existing_logic = parser_state.existing_logic
  
  parser_state.existing_logic = Logic()
  if existing_logic is not None:
    parser_state.existing_logic = existing_logic
  # BOTH LHS and RHS CAN BE EXPRESSIONS!!!!!!
  # BUT LEFT SIDE MUST RESULT IN VARIABLE ADDRESS / wire?
  #^^^^^^^^^^^^^^^^^
  
  #### GLOBALS \/
  # This is the first place we should see a global reference in terms of this function/logic
  parser_state.existing_logic = MAYBE_GLOBAL_STATE_REG_INFO_TO_LOGIC(lhs_orig_var_name, parser_state)
  
  # Sanity check
  if lhs_orig_var_name not in parser_state.existing_logic.wire_to_c_type:
    print("It looks like variable",lhs_orig_var_name,"isn't declared?", c_ast_assignment.coord)
    sys.exit(-1)
  lhs_base_type = parser_state.existing_logic.wire_to_c_type[lhs_orig_var_name]
  const_lhs = C_AST_REF_TOKS_ARE_CONST(lhs_ref_toks)

  if not const_lhs:
    # TODO
    if c_ast_assignment.op != "=":
      print("Unsupported assignment op non const",c_ast_assignment.op)
      sys.exit(-1)
    
    # Variable references write to larger "sized" references then constant references
    # dims=A,B,C
    # x[i] = 0   writes the entire 'x' array  (aka reads from anywhere in 'x' depend on this)
    # x[0][i] writes all of x[0] which is of type array[B]
    # x[i][0] writes all of x[ ][0]?? which is of type array[A]  ???
    # x[0][1][i] writes all of x[0][1] which is of type array[C]
    # x[i][0][j] writes all of x[ ][0][ ] which is of type x_type[A][C] ?
    # y[k].x[i][0][j]  = rhs       
    #
    # The RHS value is 'written' by muxing it into that portion of the array
    # First ready the entire struct portion that could be written
    # The full range of references is a sum of reading a bunch of constants
    # Build list of ref toks
    # [y,0,x,0,0,0]
    # [y,0,x,0,0,1]
    # [y,0,x,1,0,0]
    # ...
    # Get list of variable dims
    var_dim_ref_tok_indices, var_dims, var_dim_iter_types = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(lhs_ref_toks, c_ast_assignment.lvalue, parser_state)

    #print "lhs_ref_toks",lhs_ref_toks
    #print "var_dims",var_dims
    #print "var_dim_ref_tok_indices",var_dim_ref_tok_indices
  
    # Do the nest loops to create all possible ref toks
    ref_toks_set = set()
    
    for orig_ref_tok_i in range(0, len(lhs_ref_toks)):
      orig_ref_tok = lhs_ref_toks[orig_ref_tok_i]
      # Start a new return set()
      new_ref_toks_set = set()
      # Is this orig ref tok variable?
      if isinstance(orig_ref_tok, c_ast.Node):
        # Variable
        # What dimension is this variable
        # Sanity check
        if orig_ref_tok_i not in var_dim_ref_tok_indices:
          print("Wait this ref tok isnt variable?", orig_ref_tok)
          sys.exit(-1)
        # Get index of this var dim is list of var dims
        var_dim_i = var_dim_ref_tok_indices.index(orig_ref_tok_i)
        var_dim = var_dims[var_dim_i]
        # For each existing ref tok append that with all possible dim values
        for ref_toks in ref_toks_set:
          for dim_val in range(0, var_dim):
            new_ref_toks = ref_toks + (dim_val,)
            new_ref_toks_set.add(new_ref_toks)
      else:
        # Constant just append this constant value to all ref toks in list
        for ref_toks in ref_toks_set:
          new_ref_toks = ref_toks + (orig_ref_tok,)
          new_ref_toks_set.add(new_ref_toks)
        # Or add as base element
        if len(ref_toks_set) == 0:
          new_ref_toks_set.add((orig_ref_tok,))
      
      # Next iteration save new ref toks
      ref_toks_set = set(new_ref_toks_set)
    
    

    # Reduce that list of refs
    reduced_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(ref_toks_set, c_ast_assignment.lvalue, parser_state)
    sorted_reduced_ref_toks_set = sorted(reduced_ref_toks_set) # To establish an order for name strings
    
    ##########################################
    # These refs are input to write funciton
    #   Do regular logic writing to 'base' variable (in C this time?)
    # Writing to this base variable is mux between different copies of base var?
    # ^^^^^^^^^^^^^^^^^^^^ NOOOOOOOO dont want to be muxing giant base var when only writing a portion
    #
    # IF
    # x[ ][0][ ] which is of type x_type[A][C] 
    # What is the type driven by y[k].name[i][0][j]   
    #     is it    y_name_type[A][B][D] ????
    # Assign all the ref toks into a type like y_name_type[A][B][D]
    # Make copyies of that val and make constant assingments into it
    # Then nmux the copies type based on values of k,i,j
    # Output of write function is like y_name_type[A][B][D]
    lhs_elem_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(lhs_ref_toks, c_ast_assignment.lvalue, parser_state)
    
    # Build C array type using variable dimensions
    lhs_array_type = None
    # Elem might be array so try to break apart
    if C_TYPE_IS_ARRAY(lhs_elem_c_type):
      # Innner element is constant sized array, has those dims, then variable ones
      lhs_array_elem_c_type, lhs_array_elem_dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(lhs_elem_c_type)
      lhs_array_type = lhs_array_elem_c_type
      for var_dim in var_dims:
        lhs_array_type += "[" + str(var_dim) + "]"  
      for lhs_array_elem_dim in lhs_array_elem_dims:
        lhs_array_type += "[" + str(lhs_array_elem_dim) + "]" 
    else:
      # Innner element is not an array, just variable dims
      lhs_array_type = lhs_elem_c_type
      for var_dim in var_dims:
        lhs_array_type += "[" + str(var_dim) + "]"
      
    #print "lhs_ref_toks",lhs_ref_toks
    #print "var_dim_ref_tok_indices, var_dims, var_dim_iter_types",var_dim_ref_tok_indices, var_dims, var_dim_iter_types
    #print "lhs_array_type",lhs_array_type
      
    # Use recognized auto generated array types
    lhs_struct_array_type = lhs_elem_c_type.replace("[","_").replace("]","_").replace("__","_").strip("_") + "_array"
    for var_dim in var_dims:
      lhs_struct_array_type += "_" + str(var_dim)
    lhs_struct_array_type += "_t"   
    
    # This is going to be implemented in as C so func name needs to be unique
    func_name = VAR_REF_ASSIGN_FUNC_NAME_PREFIX
  
    # Fuck it just make names that wont be wrong/overlap
    # Are there built in structs?
    # output/elem type
    func_name += "_" + lhs_elem_c_type.replace("[","_").replace("]","_").replace("__","_").strip("_")
    # Base type
    lhs_base_var_type_c_name = lhs_base_type.replace("[","_").replace("]","_").replace("__","_").strip("_")
    func_name += "_" +lhs_base_var_type_c_name
    # output ref toks --dont include base var name
    for ref_tok in lhs_ref_toks[1:]:
      if type(ref_tok) == int:
        func_name += "_" + str(ref_tok)
      elif type(ref_tok) == str:
        func_name += "_" + ref_tok
      elif isinstance(ref_tok, c_ast.Node):
        func_name += "_" + "VAR"
      else:
        print("What is lhs ref tok?", ref_tok)
        sys.exit(-1)
    # input ref toks  --dont include base var name
    for ref_toks in sorted_reduced_ref_toks_set:
      for ref_tok in ref_toks[1:]:
        if type(ref_tok) == int:
          func_name += "_" + str(ref_tok)
        elif type(ref_tok) == str:
          func_name += "_" + ref_tok
        elif isinstance(ref_tok, c_ast.Node):
          func_name += "_" + "VAR"
        else:
          print("What is lhs ref tok?", ref_tok)
          sys.exit(-1)
    
    # NEED HASH to account for reduced ref toks as name
    input_ref_toks_str = ""
    for ref_toks in sorted(ref_toks_set):
      for ref_tok in ref_toks[1:]: # Skip base var name
        if type(ref_tok) == int:
          input_ref_toks_str += "_INT_" + str(ref_tok)
        elif type(ref_tok) == str:
          input_ref_toks_str += "_STR_" + ref_tok
        elif isinstance(ref_tok, c_ast.Node):
          input_ref_toks_str += "_" + "VAR"
        else:
          print("What is ref tok bleh????", ref_tok)
          sys.exit(-1)
    # Hash the string
    hash_ext = "_" + ((hashlib.md5(input_ref_toks_str.encode("utf-8")).hexdigest())[0:4]) # 4 chars enough?
    func_name += hash_ext
    
    
    # Preparing for N arg func inst
    func_c_ast_node = c_ast_assignment.lvalue
    func_base_name = func_name # Func name is unique
    base_name_is_name = True  
    input_drivers = [] # Wires or C ast nodes
    input_driver_types = [] # Might be none if not known
    input_port_names = [] # Port names on submodule 
    
    # get inst name
    func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_assignment.lvalue)
    output_wire_name = func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
    # LHS type is output type too
    parser_state.existing_logic.wire_to_c_type[output_wire_name] = lhs_dumb_struct_array_type
    # Save ref toks for this ref submodule
    parser_state.existing_logic.ref_submodule_instance_to_ref_toks[func_inst_name] = lhs_ref_toks
    
    # DO INPUT WIRES
    # (elem_val, ref_tok0, ref_tok1, ..., var_dim0, var_dim1, ...)
    
    # Elem val is from rhs
    input_port_name = "elem_val"
    input_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
    # Set type of input wire if not set already
    if input_wire not in parser_state.existing_logic.wire_to_c_type:
      parser_state.existing_logic.wire_to_c_type[input_wire] = lhs_elem_c_type
    # Make the c_ast node drive the input wire
    input_connect_logic = C_AST_NODE_TO_LOGIC(c_ast_assignment.rvalue, [input_wire], prepend_text, parser_state)
    # Merge this connect logic
    parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
    parser_state.existing_logic = parser_state.existing_logic
    # What drives the input port?
    driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]
    # Save this
    input_drivers.append(driving_wire)
    input_driver_types.append(lhs_elem_c_type)
    input_port_names.append(input_port_name)
    
    
    # Do C_AST_REF_TOKS_TO_LOGIC
    # For all the ref toks
    # DONT INCLUDE VAR NAMES IN ports
    # Dont want to encode ref toks?
    # Var assign is implemented in C, then must be C safe
    ref_toks_i = 0
    parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[func_inst_name] = []
    for ref_toks in sorted_reduced_ref_toks_set:
      input_port_name = "ref_toks_" + str(ref_toks_i)
      ref_toks_i += 1
      
      ## if base variable then call it base
      #if len(ref_toks) == 1:
      # input_port_name = "base_var"      
      input_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
      
      # Make the ref toks drive the input wire
      # This can create submoduel so have useful prepend text saying auto gen by this assignment
      input_connnect_prepend_text = VAR_REF_ASSIGN_FUNC_NAME_PREFIX + "_INPUT_" + prepend_text
      input_connect_logic = C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_assignment.lvalue, [input_wire], input_connnect_prepend_text, parser_state)
      # Merge this connect logic
      parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
      parser_state.existing_logic = parser_state.existing_logic
      # What the type?
      input_wire_c_type = parser_state.existing_logic.wire_to_c_type[input_wire]
      
      # What drives the input port?
      driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]
      
      # Save this
      input_drivers.append(driving_wire)
      input_driver_types.append(input_wire_c_type)
      input_port_names.append(input_port_name)  
      
      # SET ref_submodule_instance_to_input_port_driven_ref_toks
      parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[func_inst_name].append(ref_toks)
      
      
      
    # Do C_AST_NODE_TO_LOGIC for var_dim c_ast_nodes
    for var_dim_i in range(0, len(var_dims)):
      ref_tok_index = var_dim_ref_tok_indices[var_dim_i]
      ref_tok_c_ast_node = lhs_ref_toks[ref_tok_index]
      # Sanity check
      if not isinstance(ref_tok_c_ast_node, c_ast.Node):
        print("Not a variable ref tok?", ref_tok_c_ast_node)
        sys.exit(-1)
        
      # Cant use hacky str encode sinc eis just "*"
      # Say which variable index this is
      input_port_name = "var_dim_" + str(var_dim_i)
      input_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
      
      # Set type of input wire
      parser_state.existing_logic.wire_to_c_type[input_wire] = var_dim_iter_types[var_dim_i]
      
      # Make the c_ast node drive the input wire
      input_connect_logic = C_AST_NODE_TO_LOGIC(ref_tok_c_ast_node, [input_wire], prepend_text, parser_state)
      # Merge this connect logic
      parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
      parser_state.existing_logic = parser_state.existing_logic
      # What the type?
      input_wire_c_type = parser_state.existing_logic.wire_to_c_type[input_wire]
      
      # What drives the input port?
      driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]
      
      # Save this     
      input_drivers.append(driving_wire)
      input_driver_types.append(input_wire_c_type)
      input_port_names.append(input_port_name)  
      
      
    # OK, got all the input wires connected
  
    # VERY SIMILAR TO CONST
    ###########################################
    # RECORD NEW ALIAS FOR THIS ASSIGNMENT!!!
    
    # Assignments are ordered over time with existing logic
    # Assigning to a variable creates an alias
    # future reads on this variable are done from the alias
    lhs_next_wire_assignment_alias = prepend_text+C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(lhs_ref_toks, c_ast_assignment.lvalue, parser_state)
    #print "lhs_next_wire_assignment_alias",lhs_next_wire_assignment_alias
      
    # /\
    # SET LHS TYPE
    # Type of alias wire is "larger" sized array type
    #parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = lhs_array_type
    parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = lhs_dumb_struct_array_type
        
    
    # Save orig var name
    parser_state.existing_logic = parser_state.existing_logic
    parser_state.existing_logic.variable_names.add(lhs_orig_var_name)
    
    #print "lhs_next_wire_assignment_alias",lhs_next_wire_assignment_alias
    

    #print "c_ast_assignment.rvalue"
    #casthelp(c_ast_assignment.rvalue)
    driven_wire_names=[lhs_next_wire_assignment_alias]
    parser_state.existing_logic = parser_state.existing_logic
    
    # Get func logic 
    rhs_to_lhs_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
              prepend_text,
              func_c_ast_node,
              func_base_name,
              base_name_is_name,
              input_drivers, # Wires or C ast nodes
              input_driver_types, # Might be none if not known
              input_port_names, # Port names on submodule
              driven_wire_names,
              parser_state)
    
    # Set type of RHS wire as LHS type if not known
    rhs_driver = rhs_to_lhs_logic.wire_driven_by[lhs_next_wire_assignment_alias]
    if rhs_driver not in rhs_to_lhs_logic.wire_to_c_type:
      #rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_array_type 
      rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_struct_array_type
      
    # Merge existing and rhs logic
    parser_state.existing_logic.MERGE_SEQ_LOGIC(rhs_to_lhs_logic) 

    # Add alias to list in existing logic
    existing_aliases = []
    if lhs_orig_var_name in parser_state.existing_logic.wire_aliases_over_time:
      existing_aliases = parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name]
    new_aliases = existing_aliases
    
    # Dont double add aliases
    if not(lhs_next_wire_assignment_alias in new_aliases):
      new_aliases = new_aliases + [lhs_next_wire_assignment_alias]
    parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name] = new_aliases
    parser_state.existing_logic.alias_to_driven_ref_toks[lhs_next_wire_assignment_alias] = lhs_ref_toks
    parser_state.existing_logic.alias_to_orig_var_name[lhs_next_wire_assignment_alias] = lhs_orig_var_name
    
    
    return parser_state.existing_logic
  
  
  
  else:
    # CONSTANT ~~~~~~~~~~~~~~
    ###########################################
    return C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(lhs_ref_toks, c_ast_assignment.lvalue, c_ast_assignment.rvalue, parser_state, prepend_text, c_ast_assignment)
    
    
def C_AST_AUG_ASSIGNMENT_TO_RHS_LOGIC(c_ast_assignment, driven_wire_names, prepend_text, parser_state):
  # Ah fuckery can we just convert this into a binary op now?
  # I think I am seeing the promise land 
  # of compiler optimizations and the beauty of pycparser again
  op = None
  if c_ast_assignment.op == "+=":
    op="+"
  elif c_ast_assignment.op == "-=":
    op="-"
  elif c_ast_assignment.op == "*=":
    op="*"
  elif c_ast_assignment.op == "/=":
    op="/"
  elif c_ast_assignment.op == "%=":
    op="%"  
  elif c_ast_assignment.op == "<<=":
    op="<<"  
  elif c_ast_assignment.op == ">>=":
    op=">>"
  elif c_ast_assignment.op == "&=":
    op="&"
  elif c_ast_assignment.op == "^=":
    op='^'
  elif c_ast_assignment.op == "|=":
    op="|"
    
  if op is not None:
    fake_bin_op_rhs = c_ast.BinaryOp(op,left=c_ast_assignment.lvalue, right=c_ast_assignment.rvalue)
    fake_bin_op_rhs.coord = c_ast_assignment.coord
    #print(fake_bin_op_rhs.coord)
    #casthelp(fake_bin_op_rhs)
    #sys.exit(0)
    return C_AST_BINARY_OP_TO_LOGIC(fake_bin_op_rhs, driven_wire_names, prepend_text, parser_state)
  else:
    print("Unsupported assignment op",c_ast_assignment.op, c_ast_assignment.coord)
    sys.exit(-1)
    
    
def C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(lhs_ref_toks, lhs_c_ast_node, rhs_c_ast_node, parser_state, prepend_text, c_ast_assignment):
    # RECORD NEW ALIAS FOR THIS ASSIGNMENT!!!
    lhs_orig_var_name = lhs_ref_toks[0]
    
    # Assignments are ordered over time with existing logic
    # Assigning to a variable creates an alias
    # future reads on this variable are done from the alias
    lhs_next_wire_assignment_alias = prepend_text+C_AST_REF_TOKS_TO_NEXT_WIRE_ASSIGNMENT_ALIAS(lhs_ref_toks, lhs_c_ast_node, parser_state)
      
    # /\
    # SET LHS TYPE
    lhs_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(lhs_ref_toks, lhs_c_ast_node, parser_state)
    parser_state.existing_logic.variable_names.add(lhs_orig_var_name)
    # Type of alias wire is same as original wire
    parser_state.existing_logic.wire_to_c_type[lhs_next_wire_assignment_alias] = lhs_c_type
    
    # Get the RHS logic driving the alias
    driven_wire_names=[lhs_next_wire_assignment_alias]
    # Ahhhh jeez this is shitty special casing for augmented operators
    if c_ast_assignment is not None and c_ast_assignment.op != "=":
      rhs_to_lhs_logic = C_AST_AUG_ASSIGNMENT_TO_RHS_LOGIC(c_ast_assignment, driven_wire_names, prepend_text, parser_state)
    else:
      # Normal "=" 'operator'
      rhs_to_lhs_logic = C_AST_NODE_TO_LOGIC(rhs_c_ast_node, driven_wire_names, prepend_text, parser_state)
    
    # Set type of RHS wire as LHS type if not known
    rhs_driver = rhs_to_lhs_logic.wire_driven_by[lhs_next_wire_assignment_alias]
    if rhs_driver not in rhs_to_lhs_logic.wire_to_c_type:
      #print "rhs_driver",rhs_driver
      #print "lhs_c_type",lhs_c_type
      rhs_to_lhs_logic.wire_to_c_type[rhs_driver] = lhs_c_type  
        
    # Merge existing and rhs logic
    parser_state.existing_logic.MERGE_SEQ_LOGIC(rhs_to_lhs_logic) 

    # Add alias to list in existing logic
    existing_aliases = []
    if lhs_orig_var_name in parser_state.existing_logic.wire_aliases_over_time:
      existing_aliases = parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name]
    new_aliases = existing_aliases
    
    # Dont double add aliases
    if not(lhs_next_wire_assignment_alias in new_aliases):
      new_aliases = new_aliases + [lhs_next_wire_assignment_alias]
    parser_state.existing_logic.wire_aliases_over_time[lhs_orig_var_name] = new_aliases
    parser_state.existing_logic.alias_to_driven_ref_toks[lhs_next_wire_assignment_alias] = lhs_ref_toks
    parser_state.existing_logic.alias_to_orig_var_name[lhs_next_wire_assignment_alias] = lhs_orig_var_name
   
    return parser_state.existing_logic
  
  
def C_AST_NODE_TO_ORIG_VAR_NAME(c_ast_node):
  if type(c_ast_node) == c_ast.ID:
    return C_AST_ID_TO_ORIG_WIRE_NAME(c_ast_node)
  elif type(c_ast_node) == c_ast.StructRef:
    return GET_BASE_VARIABLE_NAME_FROM_STRUCTREF(c_ast_node)
  else:
    print("WHat C_AST_NODE_TO_ORIG_VAR_NAME", c_ast_node)
    sys.exit(-1)
  
def EXPAND_REF_TOKS_OR_STRS(ref_toks_or_strs, c_ast_ref, parser_state):
  #print "EXPAND:",ref_toks_or_strs
  
  # Get list of variable dims TODO: Modify  GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES to accept strs?
  var_dim_ref_tok_indices = [] 
  var_dims = []
  curr_ref_toks = ref_toks_or_strs[:]   
  # need at last 2 ref toks, array cant be in pos 0
  while len(curr_ref_toks) >= 2:
    last_index = len(curr_ref_toks)-1
    last_tok = curr_ref_toks[last_index]
    if last_tok == "*" or isinstance(last_tok, c_ast.Node):
      # is variable array dim
      # Pop off this last entry
      curr_ref_toks = curr_ref_toks[:last_index]
      
      # need to fake c_ast node for is this is strs
      curr_ref_toks_faked = ()
      for curr_ref_tok in curr_ref_toks:
        if curr_ref_tok == "*":
          curr_ref_toks_faked += (c_ast.Node(),)
        else:
          curr_ref_toks_faked += (curr_ref_tok,)
      
      # Get the array type
      c_array_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(curr_ref_toks_faked, c_ast_ref, parser_state)
      # Sanity check
      if not C_TYPE_IS_ARRAY(c_array_type):
        print("Oh no not an array?2", c_array_type)
        sys.exit(-1)
      # Get the dims from the array
      elem_type,dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
      # Want last dim
      #last_dim = dims[len(dims)-1]
      # First dim?
      first_dim = dims[0];
      # Save
      var_dim_ref_tok_indices.append(last_index)
      var_dims.append(first_dim)        
    else:
      # Pop off this last entry
      curr_ref_toks = curr_ref_toks[:last_index]
      # Thats it
  
  # Do the nest loops to create all possible ref toks
  ref_toks_set = set()
  
  for orig_ref_tok_i in range(0, len(ref_toks_or_strs)):
    orig_ref_tok = ref_toks_or_strs[orig_ref_tok_i]
    # Start a new return list
    new_ref_toks_set = set()
    # Is this orig ref tok variable?
    if orig_ref_tok =="*" or isinstance(orig_ref_tok, c_ast.Node):
      # Variable
      # What dimension is this variable
      # Sanity check
      if orig_ref_tok_i not in var_dim_ref_tok_indices:
        print("Wait this ref tok isnt variable?2", orig_ref_tok)
        sys.exit(-1)
      # Get index of this var dim is list of var dims
      var_dim_i = var_dim_ref_tok_indices.index(orig_ref_tok_i)
      var_dim = var_dims[var_dim_i]
      # For each existing ref tok append that with all possible dim values
      for ref_toks in ref_toks_set:
        for dim_val in range(0, var_dim):
          new_ref_toks = ref_toks + (dim_val,)
          new_ref_toks_set.add(new_ref_toks)
    else:
      ## Fix string digits to be ints
      #if type(orig_ref_tok) == str and orig_ref_tok.isdigit():
      # orig_ref_tok = int(orig_ref_tok)
      #???^^^ what?
      
      # Constant just append this constant value to all ref toks in list
      for ref_toks in ref_toks_set:
        new_ref_toks = ref_toks + (orig_ref_tok,)
        new_ref_toks_set.add(new_ref_toks)        
      # Or add as base element
      if len(ref_toks_set) == 0:
        new_ref_toks_set.add((orig_ref_tok,))
    
    # Next iteration save new ref toks
    ref_toks_set = set(new_ref_toks_set)
  
  

  return ref_toks_set
    

# Do one level of expansion to next branches
# Expands variable ref toks, structs to fields, arrays to elements
# Does not return self ref_toks in set, self is not a branch of self
_REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache = dict()
def REF_TOKS_TO_OWN_BRANCH_REF_TOKS(ref_toks, c_ast_ref, parser_state):
  # Try for cache
  if parser_state.existing_logic.func_name is None:
    print("Wtf none??????")
    sys.exit(-1)
  cache_key = (parser_state.existing_logic.func_name, ref_toks)
  try:
    return set(_REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache[cache_key]) # Copy since set is mutable + WILL be mutated
  except:
    pass
  
  debug = False
  # Only return one level of extra branchs
  # Current c type
  # Get the C type as evaulated (a,*,b) is like a[0].b
  c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_ref, parser_state)
  
  # Use this type to do struct and array expansion
  rv = set()
  # Struct?
  if C_TYPE_IS_STRUCT(c_type, parser_state):
    # Child branches are struct field names
    field_type_dict = parser_state.struct_to_field_type_dict[c_type]
    if debug:
      print("Struct:",field_type_dict)   
    for field in field_type_dict:
      new_toks = ref_toks[:]
      new_toks += (field,)
      rv.add(new_toks)
      
  # Array?
  elif C_TYPE_IS_ARRAY(c_type):
    # One dimension at a time works?
    base_elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
    current_dim = dims[0]
    inner_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(c_type)
    for i in range(0, current_dim):
      new_toks = ref_toks[:]
      new_toks += (i,)
      rv.add(new_toks)
  else:
    # Not composite type 
    # Only branch is self, not included
    rv = set()
    
  # Then expand all variable references
  # rv is based on ref_toks so wont have variable ref toks if ref_toks wasnt
  if not C_AST_REF_TOKS_ARE_CONST(ref_toks):
    # Expand know all variable ref toks inrv
    expanded_ref_toks_set = set()
    for ref_toks_i in rv:
      expanded_ref_toks_set |= EXPAND_REF_TOKS_OR_STRS(ref_toks_i, c_ast_ref, parser_state)
    rv = expanded_ref_toks_set
  
  
  # Update cache
  _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache[cache_key] = frozenset(rv)
  #print cache_key
  return rv

    
_REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache = dict()
# Traverse compound types down to individual ref toks to collect all branches
#  expanding variable refs along the way
def REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(ref_toks, c_ast_ref, parser_state):
  debug = False 
  
  # Try for cache
  if parser_state.existing_logic.func_name is None:
    print("Wtf none??????")
    sys.exit(-1)
  cache_key = (parser_state.existing_logic.func_name, ref_toks)
  try:
    return set(_REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache[cache_key]) # Copy since set is mutable + WILL be mutated
  except:
    pass
  
  # Will I forget to trim elsewhere?
  #   Arcade Fire - Everything Now
  rv = set([TRIM_VAR_REF_TOKS(ref_toks)])
  # Get next level branches
  next_branch_ref_toks_set = REF_TOKS_TO_OWN_BRANCH_REF_TOKS(ref_toks, c_ast_ref, parser_state)
  rv |= next_branch_ref_toks_set
  #print "ref_toks",ref_toks,"next_branch_ref_toks_set",next_branch_ref_toks_set
  # Recurse from there
  for next_branch_ref_toks in next_branch_ref_toks_set:
    rv |= REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(next_branch_ref_toks, c_ast_ref, parser_state)
  
  if debug:
    print("All branches:", rv)
    sys.exit(-1)     
      
  # Update cache
  _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache[cache_key] = frozenset(rv)
        
  return rv
  
  
_REDUCE_REF_TOKS_OR_STRS_cache = dict()
def REDUCE_REF_TOKS_OR_STRS(ref_toks_set, c_ast_node, parser_state):
  # Try for cache
  if parser_state.existing_logic.func_name is None:
    print("Wtf none??????")
    sys.exit(-1) 
  cache_key = (parser_state.existing_logic.func_name, frozenset(ref_toks_set))
  try:
    return set(_REDUCE_REF_TOKS_OR_STRS_cache[cache_key]) # Copy since set is mutable + WILL be mutated
  except:
    pass
  
  # Collpase ex. [ [struct,pointa,x] , [struct,pointa,y], [struct,pointb,x] ]
  # collpases down to [ [struct,pointa], [struct,pointb,x] ] since sub elements of point are all driven
  # What about if ref_toks ends in variable/array ref tok? Collapse down to array base name right?
  #   [struct,array,*/castnode, anotherarray, */castnode]
  # First expand to get rid of variable ref toks
  expanded_ref_toks_set = set()
  for ref_toks in ref_toks_set:
    expanded_ref_toks_set_i = EXPAND_REF_TOKS_OR_STRS(ref_toks,c_ast_node, parser_state)
    expanded_ref_toks_set |= expanded_ref_toks_set_i
  
  # Then reduce that expanded list
  rv_ref_toks_set = set(expanded_ref_toks_set)
  still_removing_elements = True
  while still_removing_elements:
    # Assume stoping now
    still_removing_elements = False
    
    # Loop over all ref toks
    loop_copy_rv_ref_toks_set = set(rv_ref_toks_set)
    for ref_toks in loop_copy_rv_ref_toks_set:
      # IF removing elements then back to outermost loop
      if still_removing_elements:
        break
      
      # Remove children of this ref_tok
      for maybe_child_ref_tok in loop_copy_rv_ref_toks_set:
        if maybe_child_ref_tok != ref_toks:
          if REF_TOKS_COVERED_BY(maybe_child_ref_tok, ref_toks, parser_state):
            rv_ref_toks_set.remove(maybe_child_ref_tok)
            
      # Record if change was made and jump to next iteration
      if rv_ref_toks_set != loop_copy_rv_ref_toks_set:
        still_removing_elements = True
        break
              
      # Check if these ref_toks are a leaf with all sibling leafs driven
      if len(ref_toks) < 2:
        continue

      # Get root struct for this struct ref
      root_ref_toks = ref_toks[0:len(ref_toks)-1]
      # Check if all fields of this root struct ref are in this list
      root_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(root_ref_toks, c_ast_node, parser_state)
      all_fields_present = True
      if C_TYPE_IS_STRUCT(root_c_type,parser_state):
        field_types_dict = parser_state.struct_to_field_type_dict[root_c_type]
        for field_name in field_types_dict:
          possible_ref_toks = root_ref_toks + (field_name,)
          if possible_ref_toks not in rv_ref_toks_set:
            all_fields_present = False
              
        # If all there then remove them all
        if all_fields_present:
          still_removing_elements = True
          for field_name in field_types_dict:
            possible_ref_toks = root_ref_toks + (field_name,)
            rv_ref_toks_set.remove(possible_ref_toks)
          # And replace with root
          rv_ref_toks_set.add(root_ref_toks)
          # Next iteration
          break
            
      elif C_TYPE_IS_ARRAY(root_c_type):
        #print "!~~~"
        #print "root_ref_toks",root_ref_toks
        #print "root_c_type",root_c_type
        elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(root_c_type)
        #last_dim = dims[len(dims)-1]
        # No want first dim?
        first_dim = dims[0]
        
        for i in range(0, first_dim):
          possible_ref_toks = root_ref_toks + (i,)
          #print "  possible_ref_toks",possible_ref_toks
          #print "in"

          if possible_ref_toks not in rv_ref_toks_set:
            #print "NO"
            all_fields_present = False
            
            
        # If all there then remove them all
        if all_fields_present:
          #print "all_fields_present", root_ref_toks
          still_removing_elements = True
          for i in range(0, first_dim):
            possible_ref_toks = root_ref_toks + (i,)
            #print "  REMOVING possible_ref_toks",possible_ref_toks
            rv_ref_toks_set.remove(possible_ref_toks)
          # And replace with root
          rv_ref_toks_set.add(root_ref_toks)
          # Next iteration
          break
      else:
        # Is not a composite type?
        pass
       
  
  # Update cache
  _REDUCE_REF_TOKS_OR_STRS_cache[cache_key] = frozenset(rv_ref_toks_set)
  
  #sys.exit(-1)
  return rv_ref_toks_set

# Please just be mostly used for silly len(ref_toks) compare stuff, not fundamentally required
#141 sec w/ cache
#186 w/o cache
_TRIM_VAR_REF_TOKS_cache = dict()
def TRIM_VAR_REF_TOKS(ref_toks):
  # Try for cache
  try:
    return _TRIM_VAR_REF_TOKS_cache[ref_toks]
  except:
    pass  
  
  # Remove last variable tok since
  # Ex. (a,1,c) covers same as (a,1,c,*)
  last_ref_tok = ref_toks[len(ref_toks)-1]
  while isinstance(last_ref_tok, c_ast.Node):
    ref_toks = ref_toks[0:len(ref_toks)-1]
    last_ref_tok = ref_toks[len(ref_toks)-1]
    
  # Update cache
  _TRIM_VAR_REF_TOKS_cache[ref_toks] = ref_toks
  return ref_toks
  
#_REF_TOKS_COVERED_BY_cache = dict()
# With cache: 63.812 seconds, 206.699 seconds
# Without cache: 47.065 seconds, 128.514 seconds
# More testing: without cache: 141, with cache: 240
def REF_TOKS_COVERED_BY(ref_toks, covering_ref_toks, parser_state):
  
  '''
  # Try for cache
  if parser_state.existing_logic.func_name is None:
    print "Wtf none??????"
    sys.exit(-1) 
  cache_key = (parser_state.existing_logic.func_name, ref_toks, covering_ref_toks)
  try:
    return _REF_TOKS_COVERED_BY_cache[cache_key]
  except:
    pass
  '''
  
  # Remove last variable tok since
  # Ex. (a,1,c) covers same as (a,1,c,*), and makes len check easier below
  # For both input ref toks
  covering_ref_toks = TRIM_VAR_REF_TOKS(covering_ref_toks)
  ref_toks = TRIM_VAR_REF_TOKS(ref_toks)
  
  rv = True
  # Immediate len check
  # Large len means more specific/narrow/smaller covering
  if len(covering_ref_toks) > len(ref_toks):
    rv = False
  else:
    '''
    # Simple compare of range -  NOT faster
    if ref_toks[0:len(covering_ref_toks)] == covering_ref_toks:
      rv = True
    else:
    '''
    # Individual tok checking 
    # Likely mismatches are towards end? - Hell yeah for big arrays?
    # Build Me Up Buttercup - The Foundatons
    #for ref_tok_i in range(0, len(covering_ref_toks)):
    for ref_tok_i in range(len(covering_ref_toks)-1, -1, -1):
      ref_tok = ref_toks[ref_tok_i]
      covering_ref_tok = covering_ref_toks[ref_tok_i]
      # Look for mismatch
      if ref_tok == covering_ref_tok:
        pass
      # Didnt match check type first, isinstance is slow?
      else:
        if (type(covering_ref_tok)==int and type(ref_tok)==int): # ALREADY KNOW != and (covering_ref_tok != ref_tok):
          rv = False
          break
        elif (type(covering_ref_tok)==str and type(ref_tok)==str): # ALREADY KNOW != and (covering_ref_tok != ref_tok):
          rv = False
          break
        # Variable c ast nodes only match one way
        # * covers digit but digit doesnt cover *
        elif isinstance(covering_ref_tok, c_ast.Node) and ref_tok.isdigit():
          pass
        # * covers others *
        elif isinstance(covering_ref_tok, c_ast.Node) and isinstance(ref_tok, c_ast.Node):
          pass      
        else:
          rv = False
          break
  
  '''
  # Update cache
  _REF_TOKS_COVERED_BY_cache[cache_key] = rv
  '''
  
  return rv


def WIRE_TO_DRIVEN_REF_TOKS(wire, parser_state):
  # Get ref toks for this alias
  if wire in parser_state.existing_logic.alias_to_driven_ref_toks:
    driven_ref_toks = parser_state.existing_logic.alias_to_driven_ref_toks[wire]
  else:
    # Must be orig variable name
    if wire in parser_state.existing_logic.variable_names:
      driven_ref_toks=(wire,)
    # Or input
    elif wire in parser_state.existing_logic.inputs:
      driven_ref_toks=(wire,)
    # Or state regs
    elif wire in parser_state.global_state_regs:
      driven_ref_toks=(wire,)
    else:
      print("wire:",wire)
      print("var name?:",parser_state.existing_logic.variable_names)
      print("does not have associatated ref toks", parser_state.existing_logic.alias_to_driven_ref_toks)
      print(0/0)
      sys.exit(-1)
      
  return driven_ref_toks

# THIS IS DIFFERENT FROM REDUCE DONE ABOVE
# (does modifies remaining_ref_toks, but use return value since can be cached)

# Fat cache...
# With cache, run time 230 sec w heapy, Total size = 1261187248 bytes
# Without cache, run time 180 sec w heapy, Total size = 1098484016 bytes
#_REMOVE_COVERED_REF_TOK_BRANCHES_cache = dict()
# Try without heapy...
# With cache runtime: 74.670 seconds, 304.788 seconds
# Without cache runtime: 61.963 seconds, 210.264 seconds, 
def REMOVE_COVERED_REF_TOK_BRANCHES(remaining_ref_toks_set, driven_ref_toks, c_ast_node, parser_state): 
  #print "remaining_ref_toks_set",remaining_ref_toks_set
  #print "driven_ref_toks",driven_ref_toks
  #print "=="
  debug = False
  #debug = (parser_state.existing_logic.func_name == "VAR_REF_RD_uint8_t_64_uint8_t_64_64_VAR_4538") and driven_ref_toks==('base', 0, 63)
  
  if debug:
    orig_remaining_ref_toks_set = set(remaining_ref_toks_set) #debug
  
  if parser_state.existing_logic.func_name is None:
    print("Wtf none??????")
    sys.exit(-1)
  
  
  '''
  # Try for cache
  cache_key = (parser_state.existing_logic.func_name, driven_ref_toks, frozenset(remaining_ref_toks_set))
  remaining_ref_toks_set_cache = None
  try:
    remaining_ref_toks_set_cache = set(_REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]) # Copy since set is mutable + WILL be mutated
  except:
    pass
  if remaining_ref_toks_set_cache:
    if debug:
      print "orig_remaining_ref_toks_set",orig_remaining_ref_toks_set
      print "orig driven_ref_toks",driven_ref_toks
      print "remaining_ref_toks_set",remaining_ref_toks_set_cache
      print "2" 
    if driven_ref_toks in remaining_ref_toks_set_cache:
      print parser_state.existing_logic.func_name
      print "orig driven_ref_toks",driven_ref_toks
      print "remaining_ref_toks_set",remaining_ref_toks_set_cache
      print "pre remaining_ref_toks_set==remaining_ref_toks_set_cache",remaining_ref_toks_set==remaining_ref_toks_set_cache
      print "WTF? driven_ref_toks in remaining_ref_toks_set_cache"
      sys.exit(-1)
      
    remaining_ref_toks_set = remaining_ref_toks_set_cache
    return remaining_ref_toks_set
  '''

  # Removed covered branches
  removed_something = False
  # Given alias wire (a,1,c) it covers any remaining wire (a,1,c) , (a,1,c,0) ,  (a,1,c,1)
  to_be_removed = set()
  for ref_toks in remaining_ref_toks_set: #set(remaining_ref_toks_set): # NO -slo? Copy for iteration
    if REF_TOKS_COVERED_BY(ref_toks, driven_ref_toks, parser_state):
      # Remove this ref toks
      if debug:
        print(ref_toks, "covered by", driven_ref_toks)
      #remaining_ref_toks_set.remove(ref_toks)
      to_be_removed.add(ref_toks)
      removed_something = True
    else:
      if debug:
        print(ref_toks, "not covered by", driven_ref_toks)
  remaining_ref_toks_set -= to_be_removed

  if debug:
    print("orig_remaining_ref_toks_set",orig_remaining_ref_toks_set)
    print("orig driven_ref_toks",driven_ref_toks)
    print("remaining_ref_toks_set after removing coverage",remaining_ref_toks_set)

  if removed_something:
    # The current driven_ref_toks would be removed from list 
    # Removing the branches at/under driven_ref_toks might also 
    # Might also be removing all the branches of the parent to driven_ref_toks
    # Ex. (a,1,c) removed from a list of that could have had (a,1,a) , (a,1,b)
    #   BUT DIDNT 
    #   So (a,1,c) might be the last child of (a,1) remaining, check
    # Do this repeatedly up the tree collapsing as far as possible
    # Need at least 2 toks to get root tok
    ref_toks_removed = TRIM_VAR_REF_TOKS(driven_ref_toks)
    while len(ref_toks_removed) >= 2:
      root_toks = ref_toks_removed[0:len(ref_toks_removed)-1]
      keep_root = True # default keep root branch
      # Is root even a compound type?
      own_branch_ref_toks = REF_TOKS_TO_OWN_BRANCH_REF_TOKS(root_toks, c_ast_node, parser_state)
      
      # Set stuff faster?
      keep_root = len(own_branch_ref_toks.intersection(remaining_ref_toks_set))>0
      '''
      if len(own_branch_ref_toks) > 0:
        # Has branches, are they all removed now?
        keep_root = False # Assume all branches are gone
        for branch_ref_toks in own_branch_ref_toks:
          if branch_ref_toks in remaining_ref_toks_set:
              # Found a remaining branch, root stays
              keep_root = True
              break
      '''
        
        
    
      if not keep_root:
        # Remove root, and loop again
        '''
        if root_toks not in remaining_ref_toks_set:
          print "orig_remaining_ref_toks_set",orig_remaining_ref_toks_set
          print "orig driven_ref_toks",driven_ref_toks
          print "Missing ref tok?",root_toks
          print "remaining_ref_toks_set",remaining_ref_toks_set
          print "ref_toks_removed",ref_toks_removed
          sys.exit(-1)       
        '''
        remaining_ref_toks_set.discard(root_toks)
        ref_toks_removed = root_toks
      else:
        # Keeping root, stop here
        break;
      
    if debug:
      print("remaining_ref_toks_set after collpasing refs too",remaining_ref_toks_set)
      print("")        
  
  '''
  # Update cache  
  _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key] = frozenset(remaining_ref_toks_set) # Copy since set is mutable + WILL be mutated
  if debug:
    print "Updating cache", cache_key
    print _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]
  '''
  
  #WTF?
  if (driven_ref_toks in remaining_ref_toks_set): # or (driven_ref_toks in _REMOVE_COVERED_REF_TOK_BRANCHES_cache[cache_key]):
    print("WTF? driven_ref_toks in remaining_ref_toks_set2")
    sys.exit(-1)

  return remaining_ref_toks_set
  
  

# Struct read is different from array read since:
# At the time of struct read it is possible to narrow down the 
# renamed intermediate wires that of what the struct ref is referreing
# for an array reference the "struct locations in memory / memory addrs" cannot be known ahead of time
# Always need to input entire array unless constant, when constant do like struct ref?

'''
DID you do struct ref wrong?
CANT PROCESS AS single x.y.z expression
Need to recursively get X, with .y  ... then get output of that DOT z
fuck

ONly diff between constant array and dynamic is where the "branches" start in the structref/array search
# Since arrays are written to like structs, COPY ON READ
Structref and constant array look very similar
'''
  
# ID could be a struct ID which needs struct read logic
# ID could also be an array ID which needs array read logic


# x[i][1][k]
# First need to select the i'th [n][n] array from 'x'
# Then select the 1st [n] array from output of above
# Then select k'th element from output of above
# So out of all x only these elements are needed
# 
# x 0 0 0    
# x 0 0 1
# x 0 1 0     X
# x 0 1 1     X 
# x 1 0 0 
# x 1 0 1
# x 1 1 0     X
# x 1 1 1     X

# Need to expand struct, array to all branches?
# Then evaluate  s.x[i][1] to be  s[x,i,1]
# s.x[0][0]   
# s.x[0][1]   X
# s.x[1][0]
# s.x[1][1]   X
# s.y[0][0]
# s.y[0][1]
# s.y[1][0]
# s.y[1][1]

def C_TYPE_IS_STRUCT(c_type_str, parser_state):
  return (c_type_str in parser_state.struct_to_field_type_dict) or SW_LIB.C_TYPE_IS_ARRAY_STRUCT(c_type_str, parser_state)
  
def C_TYPE_IS_ENUM(c_type_str, parser_state):
  #print("parser_state.enum_to_ids_dict",parser_state.enum_to_ids_dict)
  return c_type_str in parser_state.enum_to_ids_dict
  
def C_TYPE_IS_ARRAY(c_type):
  return "[" in c_type and c_type.endswith("]")
  
def C_TYPE_IS_USER_TYPE(c_type,parser_state):
  user_code = False
  if C_TYPE_IS_STRUCT(c_type,parser_state):
    if SW_LIB.C_TYPE_IS_ARRAY_STRUCT(c_type, parser_state):
      c_array_type = SW_LIB.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(c_type, parser_state)
      elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
      if C_TYPE_IS_STRUCT(elem_t,parser_state):
        user_code = True
    else:
      # Not the dumb array thing, is regular struct
      user_code = True
  elif C_TYPE_IS_ARRAY(c_type):
    elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
    if C_TYPE_IS_STRUCT(elem_type,parser_state):
      user_code = True
      
  return user_code
  
  
# Returns None if not resolved
# THIS RELYS ON optimizing away constant funcs to const wires in N ARG FUNC logic
# returns  (const, logic)
def RESOLVE_CONST_ARRAY_REF_TO_LOGIC(c_ast_array_ref, prepend_text, parser_state):
  # So this is like needed because constant resolving variable ref
  # into a smaller var ref, or totally constant ref is hard to do
  # ~hElP!~
  
  # Do a fake C_AST_NODE to logic for subscript
  # if can trace to constant wire then
  dummy_wire = "DUMMY_RESOLVE_WIRE"
  driven_wire_names = [dummy_wire]
  # This will be removed always?
  # OK to pre evaluate the subscript because will be evaluated always the same
  # Will just be driving var ref opr var assign submodules instead of dummy?
  #parser_state.existing_logic.wire_to_c_type[dummy_wire] = "uint32_t"
  parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_array_ref.subscript, driven_wire_names, prepend_text, parser_state)
  # Is dummy wire driven by constant?
  const_driving_wire = FIND_CONST_DRIVING_WIRE(dummy_wire, parser_state.existing_logic)
  
  # Remove the dummy wire
  # Fast
  parser_state.existing_logic.wires.remove(dummy_wire)
  parser_state.existing_logic.wire_to_c_type.pop(dummy_wire, None)
  # IO wire is driven by thing
  driving_wire = parser_state.existing_logic.wire_driven_by[dummy_wire]
  # Remove io wire from opposite direction
  all_driven_wires = parser_state.existing_logic.wire_drives[driving_wire]
  all_driven_wires.remove(dummy_wire)
  if len(all_driven_wires) > 0:
    parser_state.existing_logic.wire_drives[driving_wire] = all_driven_wires
  else:
    parser_state.existing_logic.wire_drives.pop(driving_wire)
  # Then remove original direction
  parser_state.existing_logic.wire_driven_by.pop(dummy_wire)
  
  
  # Return the constant or None
  if const_driving_wire is not None:
    # Get value from this constant
    maybe_digit = GET_VAL_STR_FROM_CONST_WIRE(const_driving_wire, parser_state.existing_logic, parser_state)
    if not maybe_digit.isdigit():
      print("Constant array ref with non integer index?", const_driving_wire)
      sys.exit(-1)
    #print "CONST",maybe_digit
    return int(maybe_digit), parser_state.existing_logic
  else:
    return None, parser_state.existing_logic


# ONLY USE THIS WITH REF C AST NODES
# Returns toks, logic
def C_AST_REF_TO_TOKENS_TO_LOGIC(c_ast_ref, prepend_text, parser_state):
  toks = tuple()
  if type(c_ast_ref) == c_ast.ID:
    toks += (str(c_ast_ref.name),)
  elif type(c_ast_ref) == c_ast.ArrayRef:
    new_tok = None
    # Only constant array ref right now 
    const, parser_state.existing_logic = RESOLVE_CONST_ARRAY_REF_TO_LOGIC(c_ast_ref, prepend_text, parser_state)
    if const is None:
      new_tok = c_ast_ref.subscript
    else:
      new_tok = const
    # Name is a ref node
    new_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(c_ast_ref.name, prepend_text, parser_state)
    toks += new_toks
    toks += (new_tok,)
  elif type(c_ast_ref) == c_ast.StructRef:
    # Name is a ref node
    new_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(c_ast_ref.name, prepend_text, parser_state)
    toks += new_toks
    toks += (str(c_ast_ref.field.name),)
  else:
    print("Uh what node in C_AST_REF_TO_TOKENS?",c_ast_ref)
    print(0/0)
    sys.exit(-1)
    
  # Reverse reverse
  #toks = toks[::-1]
    
  return toks, parser_state.existing_logic
  
_C_AST_REF_TOKS_TO_C_TYPE_cache = dict()
# "Const" here means variable refs are evaluated x[*] = type of x[0] 
def C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_ref, parser_state):
  #print "ref_toks",ref_toks
  # Try to get cache
  # Build key
  ref_toks_str = parser_state.existing_logic.func_name[:]
  for ref_tok in ref_toks:
    if type(ref_tok) == int:
      ref_toks_str += "_INT_" + str(ref_tok)
    elif type(ref_tok) == str:
      ref_toks_str += "_STR_" + ref_tok
    elif isinstance(ref_tok, c_ast.Node):
      ref_toks_str += "_" + "VAR"
    else:
      print("What is ref tok bleh?sdsd???", ref_tok)
      sys.exit(-1)
  cache_key = ref_toks_str
  #cache_key = (parser_state.existing_logic.func_name, ref_toks)
    
  # Try for cache
  try:
    return _C_AST_REF_TOKS_TO_C_TYPE_cache[cache_key]
  except:
    pass
  
  # Get base variable name
  var_name = ref_toks[0]
    
  # Get the type of this base name
  if var_name in parser_state.existing_logic.wire_to_c_type:
    base_type = parser_state.existing_logic.wire_to_c_type[var_name]
  else:
    #print "parser_state.existing_logic",parser_state.existing_logic
    #print "parser_state.existing_logic.func_name",parser_state.existing_logic.func_name
    #print "known variables:",parser_state.existing_logic.variable_names
    print("It looks like variable", var_name, "is not defined?",c_ast_ref.coord)
    #for wire in sorted(parser_state.existing_logic.wire_to_c_type):
    # print wire, ":", parser_state.existing_logic.wire_to_c_type[wire]
    #print "parser_state.existing_logic.wire_to_c_type",parser_state.existing_logic.wire_to_c_type
    #print 0/0
    sys.exit(-1)
    
  # Is this base type an ID, array or struct ref?
  if len(ref_toks) == 1:
    # Just an ID
    current_c_type =  base_type
  else:
    # Is a struct ref and/or array ref
    remaining_toks = ref_toks[1:]
    
    # While we have a reminaing tok
    current_c_type = base_type
    while len(remaining_toks) > 0:
      #if var_name == "bs":
      # print "current_c_type",current_c_type
      # print "remaining_toks",remaining_toks
        
      next_tok = remaining_toks[0]
      if type(next_tok) == int:
        # Constant array ref
        # Sanity check
        if not C_TYPE_IS_ARRAY(current_c_type):
          print("Arrayref tok but not array type?", current_c_type, remaining_toks,c_ast_ref.coord)
          sys.exit(-1)
        # Go to next tok      
        remaining_toks = remaining_toks[1:]
        # Remove inner subscript to form output type
        current_c_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(current_c_type)
      elif type(next_tok) == str:
        # Struct
        # Sanity check
        if not C_TYPE_IS_STRUCT(current_c_type, parser_state):
          print("Struct ref tok but not struct type?", remaining_toks,c_ast_ref.coord)
          sys.exit(-1)
        field_type_dict = parser_state.struct_to_field_type_dict[current_c_type]
        if next_tok not in field_type_dict:
          print(next_tok, "is not a member field of",current_c_type, c_ast_ref.coord)
          #print 0/0
          sys.exit(-1)
        # Go to next tok      
        remaining_toks = remaining_toks[1:]
        current_c_type = field_type_dict[next_tok]      
      elif isinstance(next_tok, c_ast.Node):
        # Variable array ref
        # Sanity check
        if not C_TYPE_IS_ARRAY(current_c_type):
          print("Arrayref tok but not array type?2", current_c_type, remaining_toks,c_ast_ref.coord)
          sys.exit(-1)
        # Go to next tok      
        remaining_toks = remaining_toks[1:]
        # Remove inner subscript to form output type
        current_c_type = GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(current_c_type)   
      else:
        casthelp(next_tok)
        print("What kind of reference is this?", c_ast_ref.coord)
        sys.exit(-1)
      
  # Sanity check on const ref must be array type
  '''
  if not C_AST_REF_TOKS_ARE_CONST(ref_toks):
    if not C_TYPE_IS_ARRAY(current_c_type):
      print "Ref toks are array type?"
      print ref_toks
      print current_c_type
      sys.exit(-1)
  ''' 
  
  # Write cache 
  _C_AST_REF_TOKS_TO_C_TYPE_cache[cache_key] = current_c_type
      
  return current_c_type
  

def C_AST_ID_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state): 
  # Is the ID an ENUM constant?
  is_enum_const = ID_IS_ENUM_CONST(c_ast_node, parser_state.existing_logic, prepend_text, parser_state)
  
  #print c_ast_node
  #print "is_enum_const",is_enum_const
  
  
  
  if is_enum_const:
    return C_AST_ENUM_CONST_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state)
  else:
    return C_AST_REF_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state)

def C_AST_REF_TO_LOGIC(c_ast_ref, driven_wire_names, prepend_text, parser_state):
  if type(c_ast_ref) == c_ast.ArrayRef:
    pass
  elif type(c_ast_ref) == c_ast.StructRef:
    pass
  elif type(c_ast_ref) == c_ast.ID:
    pass
  else:
    print("What type of ref is this?", c_ast_ref)
    sys.exit(-1)
    
  # Get tokens to identify the reference
  # x.y[5].z.q[i]   is [x,y,5,z,q,<c_ast_node>]
  ref_toks, parser_state.existing_logic = C_AST_REF_TO_TOKENS_TO_LOGIC(c_ast_ref, prepend_text, parser_state)
  
  return C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_ref, driven_wire_names, prepend_text, parser_state)
  
def C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_ref, driven_wire_names, prepend_text, parser_state):        
  
  # FUCK
  debug = False
  #debug = (parser_state.existing_logic.func_name == "deserializer") and (ref_toks==("msg",))
  
  # The original variable name is the first tok
  base_var_name = ref_toks[0]
  
  # This is the first place we could see a global reference in terms of this function/logic
  parser_state.existing_logic = MAYBE_GLOBAL_STATE_REG_INFO_TO_LOGIC(base_var_name, parser_state)
  
  # What type is this reference?
  c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_ref, parser_state)
  
  # Use base var (NOT ORIG WIRE SINCE structs) to look up alias list
  driving_aliases_over_time = []
  # Some wires are special and are already considered driven
  #  ex. input, global, volatile global, or in wire driven by
  if ( (base_var_name in parser_state.existing_logic.inputs) or
       (base_var_name in parser_state.existing_logic.state_regs) or
       (base_var_name in parser_state.existing_logic.wire_driven_by) or
       (base_var_name in parser_state.existing_logic.feedback_vars) ):
    driving_aliases_over_time += [base_var_name]
  aliases_over_time = []
  if base_var_name in parser_state.existing_logic.wire_aliases_over_time:
    aliases_over_time = parser_state.existing_logic.wire_aliases_over_time[base_var_name]
  driving_aliases_over_time += aliases_over_time

  # Does most recent alias cover entire wire?
  # Break orig wire name to all branches
  #print "ref_toks",ref_toks
  entire_tree_ref_toks_set = REF_TOKS_TO_ENTIRE_TREE_REF_TOKS(ref_toks, c_ast_ref, parser_state)
  if debug:
    print("ref_toks to logic",ref_toks)
    print("entire_tree_ref_toks_set",entire_tree_ref_toks_set)
  #print ""
  
  #sys.exit(-1)
  if len(driving_aliases_over_time)==0:
    #if debug:
    #print "=="
    #print "func name",parser_state.existing_logic.func_name
    #print "ref_toks",ref_toks
    #print "driving_aliases_over_time",driving_aliases_over_time
    #print "entire_tree_ref_toks_set",entire_tree_ref_toks_set
    #print "No driving aliases?", prepend_text, c_ast_ref.coord
    #print 0/0
    print(ref_toks, "not fully driven when read at?", c_ast_ref.coord)
    sys.exit(-1)
  
  # Find the first alias (IN REVERSE ORDER) that elminates some branches
  remaining_ref_toks_set = set(entire_tree_ref_toks_set)
  i = len(driving_aliases_over_time)-1
  first_driving_alias = None
  while len(remaining_ref_toks_set) == len(entire_tree_ref_toks_set):
    if i < 0:
      print("Ran out of aliases?")
      print("func name",parser_state.existing_logic.func_name)
      print("ref_toks",ref_toks)
      print("entire_tree_ref_toks_set",entire_tree_ref_toks_set)
      print("driving_aliases_over_time",driving_aliases_over_time)
      print("remaining_ref_toks_set",remaining_ref_toks_set)
      print("This is either my problem or your code doesnt drive all your local variables...")
      print("Why you so angry at me?")
      print("   The Lemon Twigs - Baby, Baby")
      sys.exit(-1)

    alias = driving_aliases_over_time[i]
    alias_c_type = parser_state.existing_logic.wire_to_c_type[alias]
    alias_driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(alias, parser_state)
    
    if debug:
      print("maybe first alias#",i,alias)
      print("alias_driven_ref_toks",alias_driven_ref_toks)
      print("orig ref_toks",ref_toks)
      print("pre remaining_ref_toks_set",remaining_ref_toks_set)
    
    remaining_ref_toks_set = REMOVE_COVERED_REF_TOK_BRANCHES(remaining_ref_toks_set, alias_driven_ref_toks, c_ast_ref, parser_state)
    # Next alias working backwards
    i = i - 1
    
    if debug:
      print("post remaining_ref_toks_set",remaining_ref_toks_set)
      print("")
  
  # At this point alias is first driver
  first_driving_alias = alias
  first_driving_alias_c_type = alias_c_type
  # If all wires elminated because was exact type match then do simple wire assignment
  first_driving_alias_type_match = first_driving_alias_c_type==c_type 
  

  
  if len(remaining_ref_toks_set) == 0 and first_driving_alias_type_match: 
    return APPLY_CONNECT_WIRES_LOGIC(parser_state, first_driving_alias, driven_wire_names, prepend_text, c_ast_ref)
  else:   
    '''
    print "ref_toks",ref_toks   
    print "c_type",c_type
    print "first_driving_alias_c_type",first_driving_alias_c_type
    print "entire_tree_ref_toks_set",entire_tree_ref_toks_set
    print "first_driving_alias",first_driving_alias
    print "remaining_ref_toks_set",remaining_ref_toks_set
    '''

    # Create list of driving aliases
    driving_aliases = []
    #if len(remaining_wires) < len_pre_drive:
    driving_aliases += [first_driving_alias]
    
    
    #print "remaining_wires after first alias",remaining_wires

    # Work backwards in alias list starting with next wire
    i = len(driving_aliases_over_time)-2
    while len(remaining_ref_toks_set) > 0:
      if i < 0:
        print("Ran out of aliases?@@@@@@@")
        print("func name",parser_state.existing_logic.func_name)
        print("starting ref_toks",ref_toks)
        print("c_type",c_type)
        print("expanded entire_tree_ref_toks_set",entire_tree_ref_toks_set)
        print("driving_aliases_over_time",driving_aliases_over_time)
        print("remaining_ref_toks_set",remaining_ref_toks_set)
        #print "="
        #print "first_driving_alias",first_driving_alias
        #print "first_driving_alias_c_type",first_driving_alias_c_type
        print("=")
        print("This is either my problem or your code doesnt drive all your local variables...")
        sys.exit(-1)
        
      alias = driving_aliases_over_time[i]
      alias_driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(alias, parser_state)
      # Then remove all branch wires covered by this driver
      len_pre_drive = len(remaining_ref_toks_set)
      
      if debug:
        print("alias#",i,alias)
        print("alias_driven_ref_toks",alias_driven_ref_toks)
        print("orig ref_toks",ref_toks)
        print("pre remaining_ref_toks_set",remaining_ref_toks_set)
      
      remaining_ref_toks_set = REMOVE_COVERED_REF_TOK_BRANCHES(remaining_ref_toks_set, alias_driven_ref_toks, c_ast_ref, parser_state)
      
      if debug:
        print("post remaining_ref_toks_set",remaining_ref_toks_set)
        print("")
      
      # Record this alias as driver if it drove wires
      if len(remaining_ref_toks_set) < len_pre_drive:
        driving_aliases += [alias]
      
      # Next alias working backwards
      i = i - 1 
    
    # Reverse order of drivers
    driving_aliases = driving_aliases[::-1]
  
    
    #print "func_inst_name",func_inst_name
    #print "driving_aliases_over_time",driving_aliases_over_time
    #print "first_driving_alias",first_driving_alias
    #print "ref driving aliases",driving_aliases
    
    # Needs ref read function
    # Name needs ot include the ref being done
    
    # Constant ref ?
      
    prefix = CONST_REF_RD_FUNC_NAME_PREFIX
    if not C_AST_REF_TOKS_ARE_CONST(ref_toks):
      prefix = VAR_REF_RD_FUNC_NAME_PREFIX
      
    # NEEDS TO BE LEGIT C FUNC NAME
    # Func name == base name since is custom unique name
    func_name = prefix
    # Cant cache all refs?
    # Fuck it just make names that wont be wrong/overlap
    # Are there built in structs?
    # output type
    # Base type
    # output ref toks --dont include base var name
    # input ref toks  --dont include base var name
    # # ?? not needed, included in output ref toks?  variable dims (If not const)    
    
    # Output type of the ref
    func_name += "_" + c_type.replace("[","_").replace("]","")
    
    # Base type of the ref
    # Dont always have to use base var type?
    # x.y.int[const 2]   driven by array int[4]
    # Same func as
    # somearray[const 2] driven by array int[4]   
    base_var_type = parser_state.existing_logic.wire_to_c_type[base_var_name]
    base_var_type_c_name = base_var_type.replace("[","_").replace("]","")
    func_name += "_" + base_var_type_c_name
    
    # Output ref toks
    for ref_tok in ref_toks[1:]: # Skip base var name
      if type(ref_tok) == int:
        func_name += "_" + str(ref_tok)
      elif type(ref_tok) == str:
        func_name += "_" + ref_tok
      elif isinstance(ref_tok, c_ast.Node):
        func_name += "_" + "VAR"
      else:
        print("What is ref tok?", ref_tok)
        sys.exit(-1)
    
    
    # Need to condense c_ast_ref in function name since too big for file name?
    # Bleh? TODO later and solve for bigger reasons?
    # Damnit cant postpone
    # Build list of driven ref toks and reduce
    driven_ref_toks_list = []
    for driving_alias in driving_aliases:
      driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(driving_alias, parser_state)
      driven_ref_toks_list.append(driven_ref_toks)
    # Reduce
    reduced_driven_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(driven_ref_toks_list, c_ast_ref , parser_state)
    sorted_reduced_driven_ref_toks_set = sorted(reduced_driven_ref_toks_set)
    
    # Sanity
    if len(sorted_reduced_driven_ref_toks_set) <= 0:
      print("Wtf no sorted input ref toks for ref read @", c_ast_ref.coord)
      sys.exit(-1)
    if len(driven_ref_toks_list) <= 0:
      print("Wtf no input ref toks for ref read @", c_ast_ref.coord)
      sys.exit(-1)
    
    # Func name built with reduced list
    for driven_ref_toks in sorted_reduced_driven_ref_toks_set:
      for ref_tok in driven_ref_toks[1:]: # Skip base var name
        if type(ref_tok) == int:
          func_name += "_" + str(ref_tok)
        elif type(ref_tok) == str:
          func_name += "_" + ref_tok
        elif isinstance(ref_tok, c_ast.Node):
          func_name += "_" + "VAR"
        else:
          print("What is ref tok bleh?", ref_tok)
          sys.exit(-1)
          
          
    # APPEND HASH to account for differences when not reduced name
    # BLAGH
    # Ref toks driven by aliases
    input_ref_toks_str = ""
    for driven_ref_toks in driven_ref_toks_list:
      for ref_tok in driven_ref_toks[1:]: # Skip base var name
        if type(ref_tok) == int:
          input_ref_toks_str += "_INT_" + str(ref_tok)
        elif type(ref_tok) == str:
          input_ref_toks_str += "_STR_" + ref_tok
        elif isinstance(ref_tok, c_ast.Node):
          input_ref_toks_str += "_" + "VAR"
        else:
          print("What is ref tok bleh????", ref_tok)
          sys.exit(-1)
    # Hash the string
    hash_ext = "_" + ((hashlib.md5(input_ref_toks_str.encode("utf-8")).hexdigest())[0:4]) # 4 chars enough?
    func_name += hash_ext
    
    
    # VAR DIMS HANDLED IN output ref toks?
    '''
    # Variable dimensions
    var_dim_ref_tok_indices, var_dims, var_dim_iter_types = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(ref_toks, c_ast_ref, parser_state)
    for var_dim in var_dims:
      # uint width is log2
      width = int(math.ceil(math.log(var_dim,2)))
      var_dim_type = "uint" + str(width) + "_t"
      func_name += "_" + var_dim_type
    '''
    
    #print "REF FUNC NAME:", func_name
    
    # Get inst name
    func_base_name = func_name # Is unique
    func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_ref)
    # Save ref toks for this ref submodule
    parser_state.existing_logic.ref_submodule_instance_to_ref_toks[func_inst_name] = ref_toks[:]
    
  
    # Input wire is most recent copy of input ID node 

    # N input port names named by their arg name
    # Decompose inputs to N ARG FUNCTION
    input_drivers = [] # Wires or C ast nodes
    input_driver_types = [] # Might be none if not known
    input_port_names = [] # Port names on submodule 
    
    # Each of those aliases drives an input port
    # Var ref is implemented in C, then must be C safe (just do same for const ref too , why not)
    ref_toks_i = 0
    parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[func_inst_name] = []
    for driving_alias in driving_aliases:
      #print "driving_alias",driving_alias
      # Build an input port name based off the tokens this alias drives?
      driven_ref_toks = WIRE_TO_DRIVEN_REF_TOKS(driving_alias, parser_state)
      driving_alias_type = parser_state.existing_logic.wire_to_c_type[driving_alias]
      
      # This is strange... ref tok to c type resolves to constant type
      # Type for this maybe variable refence wire might be weird non constant array thing
      # use type of driving alias instead of ref to c type?
      # ref_tok_c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(driven_ref_toks, c_ast_ref, parser_state)
      
      # if base variable then call it base
      #if len(driven_ref_toks) == 1:
      # input_port_name = "base_var"
      input_port_name = "ref_toks_" + str(ref_toks_i)
      ref_toks_i += 1
      input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
      # Remember using driving wire not c ast node  (since doing use_input_nodes_fuck_it = False)
      #print "driving_alias",driving_alias
      #print "drives:"
      #print "input_port_wire",input_port_wire
      input_drivers.append(driving_alias)
      input_driver_types.append(driving_alias_type)
      input_port_names.append(input_port_name)

      # SET ref_submodule_instance_to_input_port_driven_ref_toks
      parser_state.existing_logic.ref_submodule_instance_to_input_port_driven_ref_toks[func_inst_name].append(driven_ref_toks)

    #print "ref_toks",ref_toks  
    # Variable dimensions come after
    var_dim_ref_tok_indices, var_dims, var_dim_iter_types = GET_VAR_REF_REF_TOK_INDICES_DIMS_ITER_TYPES(ref_toks, c_ast_ref, parser_state)
    for var_dim_i in range(0, len(var_dims)):
      ref_tok_index = var_dim_ref_tok_indices[var_dim_i]
      var_dim_iter_type = var_dim_iter_types[var_dim_i]
      ref_tok_c_ast_node = ref_toks[ref_tok_index]
      # Sanity check
      if not isinstance(ref_tok_c_ast_node, c_ast.Node):
        print("Not a variable ref tok?2", ref_tok_c_ast_node)
        sys.exit(-1)
        
      # Say which variable index this is
      input_port_name = "var_dim_" + str(var_dim_i)
      input_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
      
      # Set type of input wire
      parser_state.existing_logic.wire_to_c_type[input_wire] = var_dim_iter_types[var_dim_i]
      
      # Make the c_ast node drive the input wire
      input_connect_logic = C_AST_NODE_TO_LOGIC(ref_tok_c_ast_node, [input_wire], prepend_text, parser_state)
      # Merge this connect logic
      parser_state.existing_logic.MERGE_SEQ_LOGIC(input_connect_logic)
      
      # What drives the input port?
      driving_wire = parser_state.existing_logic.wire_driven_by[input_wire]
      
      # Save this
      input_drivers.append(driving_wire)
      input_driver_types.append(var_dim_iter_type)
      input_port_names.append(input_port_name)
    
      
    # Can't.shouldnt rely on uint resizing to occur in the raw vhdl (for const ref)
    # So force output to be same type as ref would imply
    
    # Output wire is the type of the struct ref
    output_port_name = RETURN_WIRE_NAME
    
    # Output wire is the type of the ref rd
    output_c_type = c_type
    # Variable ref reads are implemented in C
    # and so cant have an output type of an array type
    # Use auto gen struct array types
    if not C_AST_REF_TOKS_ARE_CONST(ref_toks) and C_TYPE_IS_ARRAY(c_type):
      elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)       
      output_struct_array_type = elem_t.replace("[","_").replace("]","_").replace("__","_").strip("_") + "_array"
      for dim in dims:
        output_struct_array_type += "_" + str(dim)
      output_struct_array_type += "_t"
      output_c_type = output_struct_array_type
    
    output_wire = func_inst_name+SUBMODULE_MARKER+output_port_name
    parser_state.existing_logic.wire_to_c_type[output_wire] = output_c_type
    # Don't set type of output wire - shouldnt need to?
            
    
    # DO THE N ARG FUNCTION
    func_c_ast_node = c_ast_ref
    base_name_is_name = True
    func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
      prepend_text,
      func_c_ast_node,
      func_base_name,
      base_name_is_name,
      input_drivers, # Wires or C ast nodes
      input_driver_types, # Might be none if not known
      input_port_names, # Port names on submodule
      driven_wire_names,
      parser_state)

    parser_state.existing_logic = func_logic
    
    
    # After a constant reference read insert new alias?         
    
    return func_logic
  
def C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type):
  toks = input_array_type.split("[")
  #print toks
  elem_type = toks[0]
  dims = []
  for tok_i in range(1,len(toks)):
    tok = toks[tok_i]
    dim = int(tok.replace("]",""))
    dims.append(dim)
  return elem_type, dims
  
def GET_ARRAYREF_OUTPUT_TYPE_FROM_C_TYPE(input_array_type):
  elem_type, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(input_array_type)
  output_dims = dims[1:]
  output_type = elem_type
  for output_dim in output_dims:
    output_type = output_type + "[" + str(output_dim) + "]"
    
  return output_type

# WTF enums
# Bullshit.
# 
def WIRE_IS_ENUM(maybe_not_enum_wire, existing_logic, parser_state):  
  # Will not be:
  # (this is dumb)
  #   known to enum
  #   Known not to be enum? wtf?
  # input
  # global
  #   volatile global
  # variable
  #   output
  #
  # Then must be ENUM
  
  #ORIG_WIRE_NAME_TO_ORIG_VAR_NAME
  
  if (maybe_not_enum_wire in existing_logic.wire_to_c_type) and (existing_logic.wire_to_c_type[maybe_not_enum_wire] in parser_state.enum_to_ids_dict):
    return True
  elif (maybe_not_enum_wire in existing_logic.wire_to_c_type) and (existing_logic.wire_to_c_type[maybe_not_enum_wire] not in parser_state.enum_to_ids_dict):
    return False
  elif maybe_not_enum_wire in existing_logic.inputs: 
    return False
  elif (maybe_not_enum_wire in existing_logic.state_regs):
    return False
  elif maybe_not_enum_wire in existing_logic.variable_names:
    return False
  elif maybe_not_enum_wire in existing_logic.outputs:
    return False
  else:
    print("ENUM:",maybe_not_enum_wire)
    return True


def ID_IS_ENUM_CONST(c_ast_id, existing_logic, prepend_text, parser_state): 
  # Get ref tokens 
  base_name = str(c_ast_id.name)
  ref_toks = (base_name,)
    
  # Will not be:
  # (this is dumb)
  #   known to enum const
  # input
  # global
  #   volatile global
  # variable
  #   output
  #
  # Then must be ENUM 
  if (base_name in existing_logic.wire_to_c_type) and (existing_logic.wire_to_c_type[base_name] in parser_state.enum_to_ids_dict) and WIRE_IS_CONSTANT(base_name):
    return True
  elif base_name in existing_logic.inputs:
    return False
  elif (base_name in existing_logic.state_regs): # or (base_name in parser_state.global_state_regs):
    return False
  elif base_name in existing_logic.variable_names:
    return False
  elif base_name in existing_logic.outputs:
    return False
  else:
    # Check that is one of the enum consts available at least :(
    for enum_type in parser_state.enum_to_ids_dict:
      ids = parser_state.enum_to_ids_dict[enum_type]
      for id_str in ids:
        if id_str == base_name:
          return True
    return False
  
# ENUM is like constant
def C_AST_ENUM_CONST_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state):
  # Create wire for this constant
  #wire_name =  CONST_PREFIX + str(c_ast_node.type)+ "_"+ str(c_ast_node.value)
  value = str(c_ast_node.name)
  #casthelp(c_ast_node)
  #print "value",value
  #print "==="
  # Hacky use $ for enum only oh sad
  wire_name =  CONST_PREFIX + str(value) + "$" + C_AST_NODE_COORD_STR(c_ast_node)
  
  # flag to not check types /cast in APPLY_CONNNECT since dontknow exact enum type?
  #is resolved immediately after? boo enums??
  check_types_do_cast=False
  parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, wire_name, driven_wire_names, prepend_text, c_ast_node, check_types_do_cast)

  ### FUCK CAN'T DO ENUM TYPE CHECKING SINCE OPERATORS IMPLEMENTED AS unsigned compare (not num type compare, for pipelining...)
  # Hey yeah this sucks
     
  return parser_state.existing_logic
  
def GET_VAL_STR_FROM_CONST_WIRE(wire_name, Logic, parser_state):
  local_name = wire_name
  
  # Get last submodule tok
  toks = local_name.split(SUBMODULE_MARKER)
  last_tok = toks[len(toks)-1]
  local_name = last_tok 
  
  # What type of const
  # Strip off CONST_
  stripped_wire_name = local_name
  if local_name.startswith(CONST_PREFIX):
    stripped_wire_name = local_name[len(CONST_PREFIX):]
  #print "stripped_wire_name",stripped_wire_name
  # Split on under
  toks = stripped_wire_name.split("_")
  
  ami_digit = toks[0]

  return ami_digit
  
def BUILD_CONST_WIRE(value_str, c_ast_node):
  return CONST_PREFIX + value_str + "_" + C_AST_NODE_COORD_STR(c_ast_node)

# Const jsut makes wire with CONST name
def C_AST_CONSTANT_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated=False): 
  # Since constants are constants... dont add prepend text or line location info
  # Create wire for this constant
  c_type_str = None
  value_str = c_ast_node.value
  #print "value_str",value_str
  
  return CONST_VALUE_STR_TO_LOGIC(value_str, c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated)

def CONST_VALUE_STR_TO_LOGIC(value_str, c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated=False):
  if value_str.startswith("0x"):
    hex_str = value_str.replace("0x","")
    hex_str = hex_str.strip("LL").strip("U")
    value = int(hex_str, 16)
    bits = value.bit_length()
    if bits == 0:
      bits = 1
    if is_negated:
      c_type_str = "int" + str(bits+1) + "_t"
    else:
      c_type_str = "uint" + str(bits) + "_t"
  elif ("." in value_str) or ("e-" in value_str) or (value_str.endswith("F")) or (value_str.endswith("L")):
    value = float(value_str)
    c_type_str = "float"
  elif value_str.isdigit():
    value = int(value_str)
    bits = value.bit_length()
    if bits == 0:
      bits = 1
    if is_negated:
      c_type_str = "int" + str(bits+1) + "_t"
    else:
      c_type_str = "uint" + str(bits) + "_t"
  elif type(c_ast_node) == c_ast.Constant and c_ast_node.type=='char':
    value = value_str.strip("'")
    c_type_str = "char"
    #print "Char val", value 
  else:
    print("What type of constant is?", value_str, c_ast_node)
    sys.exit(-1)
  
  if is_negated:
    value = value * -1
  wire_name = BUILD_CONST_WIRE(str(value), c_ast_node)
  
  if not(c_type_str is None):
    parser_state.existing_logic.wire_to_c_type[wire_name]=c_type_str
    
    
  # Connect the constant to the wire it drives
  parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, wire_name, driven_wire_names, prepend_text, c_ast_node)
       
  return parser_state.existing_logic
 
def C_AST_STATIC_DECL_TO_LOGIC(c_ast_static_decl, prepend_text, parser_state, state_reg_var, c_type):
  # Like a global variable 
  state_reg_info = StateRegInfo()
  state_reg_info.name = state_reg_var
  state_reg_info.type_name = c_type
  state_reg_info.init = c_ast_static_decl.init
  state_reg_info.is_volatile = 'volatile' in c_ast_static_decl.quals
  state_reg_info.is_static = True
  
  # Copy info into existing_logic
  parser_state.existing_logic.state_regs[state_reg_var] = state_reg_info 
  # Record using non vol state
  if not state_reg_info.is_volatile:
    parser_state.existing_logic.uses_nonvolatile_state_regs = True
    
  return parser_state.existing_logic
    
def C_AST_DECL_TO_LOGIC(c_ast_decl, prepend_text, parser_state):
  if type(c_ast_decl.type) == c_ast.ArrayDecl:
    c_ast_array_decl = c_ast_decl.type
    name, elem_type, dim = C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(c_ast_array_decl, parser_state)
    wire_name = name
    c_type = elem_type + "[" + str(dim) + "]"
    parser_state.existing_logic.wire_to_c_type[wire_name] = c_type
  elif type(c_ast_decl.type) == c_ast.TypeDecl:
    c_ast_typedecl = c_ast_decl.type
    wire_name = c_ast_decl.name
    c_type = c_ast_typedecl.type.names[0]
    parser_state.existing_logic.wire_to_c_type[wire_name] = c_type
  else:
    print("C_AST_DECL_TO_LOGIC",c_ast_decl.type)
    sys.exit(-1)
  
  # This is a variable declaration
  parser_state.existing_logic.wires.add(wire_name)
  parser_state.existing_logic.variable_names.add(wire_name)
  
  if 'static' in c_ast_decl.storage:
    return C_AST_STATIC_DECL_TO_LOGIC(c_ast_decl, prepend_text, parser_state, wire_name, c_type)
  
  # Variable should have no assignments to it at time of declaration
  # A repeated declaration is the same as clearing assignments
  if wire_name in parser_state.existing_logic.wire_aliases_over_time:
    parser_state.existing_logic.wire_aliases_over_time[wire_name] = []
  
  # If has init value then is also assignment
  if c_ast_decl.init is not None:
    # Dont support struct init here yet
    if type(c_ast_decl.init) == c_ast.InitList:
      #print(c_ast_decl.init)
      print("Dont support local variable struct/array init statement yet...", c_ast_decl.init.coord)
      sys.exit(-1)
    
    #print parent_c_ast_decl.init
    lhs_ref_toks = (wire_name,)
    parser_state.existing_logic = C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC(lhs_ref_toks, c_ast_decl.type, c_ast_decl.init, parser_state, prepend_text, None)
  
  return parser_state.existing_logic

  
def C_AST_COMPOUND_TO_LOGIC(c_ast_compound, prepend_text, parser_state):
  existing_logic = parser_state.existing_logic
  
  # How to handle assignment over time?
  # Use function that merges logic over time
  # MERGE_SEQUENTIAL_LOGIC
  # TODO: Do this every place merge logic is used? probabhly not
  # Assumption: Compound logic block items imply execution order
  rv = existing_logic
  if existing_logic is None:
    rv = Logic()
    
  if not(c_ast_compound.block_items is None):
    for block_item in c_ast_compound.block_items:
      #print "block_item in c_ast_compound.block_items"
      #casthelp(block_item)
      #print '"leading_zeros" in rv.wire_to_c_type', ("leading_zeros" in rv.wire_to_c_type)
      #print "block_item",block_item
      parser_state.existing_logic = rv
      driven_wire_names=[]
      item_logic = C_AST_NODE_TO_LOGIC(block_item, driven_wire_names, prepend_text, parser_state)
      prev_logic = rv
      next_logic = item_logic
      
      #print "MERGING block item sequentially"
      #print "PRE SEQ MERGE rv.wire_drives", rv.wire_drives 
      #print "PRE SEQ MERGE rv.wire_driven_by", rv.wire_driven_by 
      
      prev_logic.MERGE_SEQ_LOGIC(next_logic)
      rv = prev_logic
      
      # Update parser state since merged in exsiting logic
      parser_state.existing_logic = rv
      
      #print str(block_item)
      #print "rv.wire_drives", rv.wire_drives 
      #print "rv.wire_driven_by", rv.wire_driven_by 
      
    
      
  return rv

_C_AST_NODE_COORD_STR_cache = dict()
def C_AST_NODE_COORD_STR(c_ast_node):
  
  # Try cache
  try:
    rv =  _C_AST_NODE_COORD_STR_cache[c_ast_node]
    #print "_C_AST_NODE_COORD_STR_cache"
    return rv
  except:
    pass
    
  c_ast_node_cord = c_ast_node.coord
  
  # pycparser doesnt actually do column numbers right
  # But string representation of node is correct and can be hashed
  hash_ext = "_" + (hashlib.md5(str(c_ast_node).encode("utf-8")).hexdigest())[0:4] #4 chars enough?
  
  file_coord_str = str(c_ast_node_cord.file) + "_l" + str(c_ast_node_cord.line) + "_c" + str(c_ast_node_cord.column)+hash_ext
  # Get leaf name (just stem file name of file hierarcy)
  file_coord_str = LEAF_NAME(file_coord_str)
  #file_coord_str = file_coord_str.replace(".","_").replace(":","_")
  #file_coord_str = file_coord_str.replace(":","_")
  # Lose readability for sake of having DOTs mean struct ref in wire names
  file_coord_str = file_coord_str.replace(".","_")
  
  # Save cache
  _C_AST_NODE_COORD_STR_cache[c_ast_node] = file_coord_str
  
  return file_coord_str

def C_AST_FOR_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state):
  # Do init first
  parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.init, [], prepend_text, parser_state)
  
  # Repeatedly:
  #   // Evaluate condition
  #   if cond: 
  #     body statement
  #     next statement
  i = 0
  while True:
    # Separate the duplicated logic with identifying prepend text
    iter_prepend_text = prepend_text + "FOR_" + C_AST_NODE_COORD_STR(c_ast_node) +  "_ITER_" + str(i) + "_"
    # Evaluate condition driving a dummy wire so we can recover the value?
    cond_val = None
    COND_DUMMY = iter_prepend_text + "COND_DUMMY"
    parser_state.existing_logic.wire_to_c_type[COND_DUMMY] = BOOL_C_TYPE
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.cond, [COND_DUMMY], iter_prepend_text, parser_state) 
    const_cond_wire = FIND_CONST_DRIVING_WIRE(COND_DUMMY, parser_state.existing_logic)
    if const_cond_wire is None:
      print("I dont know how to handle what you are doing in the for loop condition at", c_ast_node.cond.coord, "iteration", i)
      sys.exit(-1)
    cond_val = int(GET_VAL_STR_FROM_CONST_WIRE(const_cond_wire, parser_state.existing_logic, parser_state))
    
    # Now that constant condition evaluated
    # Remove dummy COND wire and anything driving it / driven by it?
    parser_state.existing_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(COND_DUMMY, parser_state.FuncLogicLookupTable)
    
    # If the condition is true, do an iteration of the body statement
    # Otherwise stop loop
    if not cond_val:
      break
    
    # Do body statement
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.stmt, [], iter_prepend_text, parser_state)
    
    # Do next statement
    i = i + 1
    parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.next, [], iter_prepend_text, parser_state)
    
  return parser_state.existing_logic
  
def C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_ref):
  rv = ""
  # For now only deal with constant
  for i in range(0,len(ref_toks)):
    ref_tok = ref_toks[i]
    if type(ref_tok) == int:
      # Array ref
      rv += "_" + str(ref_tok)
    elif type(ref_tok) == str:
      if i == 0:
        # Base var
        rv += ref_tok
      else:
        # Struct ref
        rv += "_" + ref_tok
    elif isinstance(ref_tok, c_ast.Node):
      rv += "_" + "VAR"
    else:
      print("What kind of ref is this?", ref_toks, c_ast_ref.coord)
      sys.exit(-1)
  return rv


def C_AST_IF_TO_LOGIC(c_ast_node,prepend_text, parser_state):   
  # Each if is just an IF ELSE (no explicit logic for "else if")
  # If logic is MUX with SEL, TRUE, and FALSE logic connected
    
  # One submodule MUX instance per variable contains in the if at this location
  # Name comes from location in file
  file_coord_str = C_AST_NODE_COORD_STR(c_ast_node)
  
  # Port names from c_ast
  
  # Mux select is driven by intermediate shared wire without variable name
  mux_cond_port_name = c_ast_node.children()[0][0]
  mux_intermediate_cond_wire_wo_var_name = prepend_text + MUX_LOGIC_NAME + "_" + file_coord_str + "_interm_" + mux_cond_port_name
  parser_state.existing_logic.wires.add(mux_intermediate_cond_wire_wo_var_name)
  parser_state.existing_logic.wire_to_c_type[mux_intermediate_cond_wire_wo_var_name] = BOOL_C_TYPE    
  # Get logic for this if condition with it driving the shared condition wire
  cond_logic = C_AST_NODE_TO_LOGIC(c_ast_node.cond, [mux_intermediate_cond_wire_wo_var_name], prepend_text, parser_state)
  parser_state.existing_logic.MERGE_SEQ_LOGIC(cond_logic)
  
  # See if condition is constant - no mux at all
  # Just only parse one branch of the logic as is just a compound statement in line
  const_driving_wire = FIND_CONST_DRIVING_WIRE(mux_intermediate_cond_wire_wo_var_name, parser_state.existing_logic)
  if const_driving_wire is not None:
    #print("const_driving_wire",const_driving_wire)
    # ONLY USE ONE BRANCH AND RETURN
    const_val_str = GET_VAL_STR_FROM_CONST_WIRE(const_driving_wire, parser_state.existing_logic,parser_state)
    try:
      const_cond_val = int(const_val_str)
    except:
      print("Something weird with constant use in if at:",c_ast_node.coord)
      sys.exit(-1)
    driven_wire_names = [] # The compand branch doesnt drive anything
    # Remove cond wire
    parser_state.existing_logic.wires.remove(mux_intermediate_cond_wire_wo_var_name)
    parser_state.existing_logic.wire_to_c_type.pop(mux_intermediate_cond_wire_wo_var_name)
    
    # Remove record of cond being driven
    # DRIVEN BY
    cond_driver = parser_state.existing_logic.wire_driven_by[mux_intermediate_cond_wire_wo_var_name]
    parser_state.existing_logic.wire_driven_by.pop(mux_intermediate_cond_wire_wo_var_name)
    # WIRE DRIVES
    all_wires_driven_by_cond_driver = parser_state.existing_logic.wire_drives[cond_driver]
    all_wires_driven_by_cond_driver.remove(mux_intermediate_cond_wire_wo_var_name)
    if len(all_wires_driven_by_cond_driver) > 0:
      parser_state.existing_logic.wire_drives[cond_driver] = all_wires_driven_by_cond_driver
    else:
      parser_state.existing_logic.wire_drives.pop(cond_driver)
    
    if const_cond_val == 1:
      # TRUE BRANCH ONLY
      # Sanity check?
      if(c_ast_node.iftrue is None):
        print("If reduces to true branch but true is none?", c_ast_node.coord)
        sys.exit(-1) 
      parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iftrue, driven_wire_names, prepend_text, parser_state)
      return parser_state.existing_logic
    else:
      # FALSE BRANCH ONLY
      # Sanity check?
      if(c_ast_node.iffalse is None):
        print("If reduces to false branch but false is none?", c_ast_node.coord)
        sys.exit(-1)      
      parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iffalse, driven_wire_names, prepend_text, parser_state)
      return parser_state.existing_logic
    
    
  #~~~~~~ NOT A CONSTANT MUX ~~~~~~~~~~ \/
  # Why are port names not constant and instead derived from child names?
  mux_true_port_name = c_ast_node.children()[1][0]
  mux_false_port_name = "iffalse" # Will this work?
  if len(c_ast_node.children()) >= 3:
    mux_false_port_name = c_ast_node.children()[2][0]
  
  # Create TRUE and FALSE branch clock enable muxes
  func_base_name = MUX_LOGIC_NAME
  base_name_is_name = False # Append types
  most_recent_clk_en_wire = parser_state.existing_logic.clock_enable_wires[-1]
  zero_wire = BUILD_CONST_WIRE(str(0), c_ast_node)
  parser_state.existing_logic.wire_to_c_type[zero_wire]=BOOL_C_TYPE
  input_port_names = []
  input_port_names.append(mux_cond_port_name)
  input_port_names.append(mux_true_port_name)
  input_port_names.append(mux_false_port_name)
  input_driver_types = []
  input_driver_types.append(BOOL_C_TYPE)
  input_driver_types.append(BOOL_C_TYPE)
  input_driver_types.append(BOOL_C_TYPE)
  # TRUE
  #  mux cond true means clock enable should be on the true mux input
  input_drivers = []
  input_drivers.append(mux_intermediate_cond_wire_wo_var_name) # Cond Wire
  input_drivers.append(most_recent_clk_en_wire) # true value is clock enable
  input_drivers.append(zero_wire) # false value is zero
  # New clock enable wire to be used in TRUE branch
  true_clock_enable_prepend_text = prepend_text + "TRUE_" + CLOCK_ENABLE_NAME + "_"
  true_clock_enable_wire_name = true_clock_enable_prepend_text + "_" + file_coord_str
  output_driven_wire_names = []
  output_driven_wire_names.append(true_clock_enable_wire_name)  
  parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    true_clock_enable_prepend_text,
    c_ast_node.iftrue,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    output_driven_wire_names,
    parser_state)
  # FALSE
  false_clock_enable_prepend_text = prepend_text + "FALSE_" + CLOCK_ENABLE_NAME + "_"
  false_clock_enable_wire_name = false_clock_enable_prepend_text + "_" + file_coord_str
  if len(c_ast_node.children()) >= 3:
    #  mux cond false means clock enable should be on the false mux input
    input_drivers = []
    input_drivers.append(mux_intermediate_cond_wire_wo_var_name) # Cond Wire
    input_drivers.append(zero_wire) # true value is zero
    input_drivers.append(most_recent_clk_en_wire) # false value is clock enable
    # New clock enable wire to be used in TRUE branch
    output_driven_wire_names = []
    output_driven_wire_names.append(false_clock_enable_wire_name)  
    parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
      false_clock_enable_prepend_text,
      c_ast_node.iffalse,
      func_base_name,
      base_name_is_name,
      input_drivers, # Wires or C ast nodes
      input_driver_types, # Might be none if not known
      input_port_names, # Port names on submodule
      output_driven_wire_names,
      parser_state)
  
  
  # Get true/false logic
  # Add prepend text to seperate the two branches into paralel combinational logic
  # Rename each driven wire with inst name and _true or _false
  prepend_text_true = prepend_text  #""#prepend_text+MUX_LOGIC_NAME+"_"+file_coord_str+"_true"+"/"   # Line numbers should be enough?
  prepend_text_false = prepend_text  #""#prepend_text+MUX_LOGIC_NAME+"_"+file_coord_str+"_false"+"/" # Line numbers should be enough?
  driven_wire_names=[] 
  #
  # Should be able to get away with only deep copying existing_logic
  parser_state_for_true = copy.copy(parser_state)
  parser_state_for_true.existing_logic = parser_state.existing_logic.DEEPCOPY()
  # Should be able to get away with only deep copying existing_logic
  parser_state_for_false = copy.copy(parser_state)
  parser_state_for_false.existing_logic = parser_state.existing_logic.DEEPCOPY()
  
  # TRUE BRANCH
  parser_state_for_true.existing_logic.clock_enable_wires.append(true_clock_enable_wire_name)
  true_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iftrue, driven_wire_names, prepend_text_true, parser_state_for_true)
  #
  if len(c_ast_node.children()) >= 3:
    # FALSE BRANCH
    parser_state_for_false.existing_logic.clock_enable_wires.append(false_clock_enable_wire_name)
    false_logic = C_AST_NODE_TO_LOGIC(c_ast_node.iffalse, driven_wire_names, prepend_text_false, parser_state_for_false)
  else:
    # No false branch false logic if identical to existing logic
    false_logic = parser_state.existing_logic.DEEPCOPY()
  
  # Var names cant be mixed type per C spec
  merge_var_names = true_logic.variable_names | false_logic.variable_names
    
  # Find out which ref toks parser_state.existing_logic, p.x, p.y etc are driven inside this IF
  # Driving is recorded with aliases over time
  # True and false can share some existing drivings we dont want to consider
  # Loop over each variable
  var_name_2_all_ref_toks_set = dict()
  ref_toks_id_str_to_output_wire = dict()
  #print "==== IF",file_coord_str,"======="
  for var_name in merge_var_names:    
    # Might be first place to see globals... is this getting out of hand?
    parser_state.existing_logic = MAYBE_GLOBAL_STATE_REG_INFO_TO_LOGIC(var_name, parser_state)
    
    #print "var_name",var_name
    # vars declared inside and IF cannot be used outside that if so cannot/should not have MUX inputs+outputs
    declared_in_this_if = not(var_name in parser_state.existing_logic.variable_names) and (var_name not in parser_state.existing_logic.state_regs)
    if declared_in_this_if:
      #print var_name, "declared_in_this_if"
      continue
    #print var_name, "declared outside if"
    
    # Get aliases over time
    # original
    original_aliases= []
    if var_name in parser_state.existing_logic.wire_aliases_over_time:
      original_aliases = parser_state.existing_logic.wire_aliases_over_time[var_name]
    # true
    true_aliases = []
    if var_name in true_logic.wire_aliases_over_time:
      true_aliases = true_logic.wire_aliases_over_time[var_name]
    # false
    false_aliases = []
    if var_name in  false_logic.wire_aliases_over_time:
      false_aliases = false_logic.wire_aliases_over_time[var_name]
    # Max len
    max_aliases_len = max(len(true_aliases),len(false_aliases))
  
    #print var_name, "original_aliases:", original_aliases
    #print var_name, "true_aliases",true_aliases
    #print var_name, "false_aliases",false_aliases
  
    # Find where the differences start in the wire aliases over time
    diff_start_i = None
    for i in range(0, max_aliases_len):
      # If no element here then difference starts here
      if (i > len(true_aliases)-1) or (i > len(false_aliases)-1):
        diff_start_i = i
        break
      
      # Both have elements, same?
      if true_aliases[i] != false_aliases[i]:
        diff_start_i = i
        break
        
    # If no difference then this var was not driven inside this IF
    if diff_start_i is None:
      #print var_name, "NO DIFFERENT ALIASES = NOT DRIVEN" 
      continue
    
    # Collect all the ref toks from aliases - whatever order
    all_ref_toks_set = set()
    for i in range(diff_start_i, max_aliases_len):
      if (i < len(true_aliases)):
        true_ref_toks = true_logic.alias_to_driven_ref_toks[true_aliases[i]]
        if true_ref_toks not in all_ref_toks_set:
          all_ref_toks_set.add(true_ref_toks)
      if (i < len(false_aliases)):
        false_ref_toks = false_logic.alias_to_driven_ref_toks[false_aliases[i]]
        if false_ref_toks not in all_ref_toks_set:
          all_ref_toks_set.add(false_ref_toks)
    
    # Collpase hierarchy to get top most orig wire name nodes 
    
    all_ref_toks_set = REDUCE_REF_TOKS_OR_STRS(all_ref_toks_set, c_ast_node, parser_state)
    
    #sys.exit(-1)
    # Ok now have collpased list of ref toks that needed MUXes for this IF
    # Save this for later too
    var_name_2_all_ref_toks_set[var_name] = set(all_ref_toks_set)

    # Now do MUX inst logic
    for ref_toks in all_ref_toks_set:
      # Might be first place to see globals... is this getting out of hand?
      var_name = ref_toks[0]      
      parser_state.existing_logic = MAYBE_GLOBAL_STATE_REG_INFO_TO_LOGIC(var_name, parser_state)
      
      # Get c type of ref
      c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_node, parser_state)
            
      # Preparing to do N arg func instance
      # Prepend text needed ot identify specific ref tok for instance
      ref_tok_id_str = C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_node)
      mux_prepend_text = prepend_text + ref_tok_id_str+"_"
      func_c_ast_node = c_ast_node
      func_base_name = MUX_LOGIC_NAME
      base_name_is_name = False # Append types
      input_port_names = []
      input_port_names.append(mux_cond_port_name)
      input_port_names.append(mux_true_port_name)
      input_port_names.append(mux_false_port_name)
      input_driver_types = []
      input_driver_types.append(BOOL_C_TYPE)
      input_driver_types.append(c_type)
      input_driver_types.append(c_type)
      input_drivers = []
      input_drivers.append(mux_intermediate_cond_wire_wo_var_name) # Wire
      
      # Need to do logic of reading ref toks
      # So need to construct wire names
      # Build instance name
      func_inst_name = BUILD_INST_NAME(mux_prepend_text, func_base_name, func_c_ast_node)

      # Using each branches logic use id_or_structref logic to form read wire driving T/F ports
      # TRUE
      mux_true_connection_wire_name = func_inst_name + SUBMODULE_MARKER + mux_true_port_name
      parser_state.existing_logic.wire_to_c_type[mux_true_connection_wire_name] = c_type
      true_logic.wire_to_c_type[mux_true_connection_wire_name]=c_type
      parser_state_for_true.existing_logic = true_logic
      true_read_logic = C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_node, [mux_true_connection_wire_name], mux_prepend_text+"TRUE_INPUT_"+MUX_LOGIC_NAME+"_", parser_state_for_true)
      # Merge in read
      true_logic.MERGE_COMB_LOGIC(true_read_logic)
      # Record input driving wire and type
      true_input_driving_wire = true_logic.wire_driven_by[mux_true_connection_wire_name]
      true_input_driving_wire_type = true_logic.wire_to_c_type[true_input_driving_wire]
      parser_state.existing_logic.wire_to_c_type[true_input_driving_wire] = true_input_driving_wire_type
      input_drivers.append(true_input_driving_wire)

      # FALSE
      mux_false_connection_wire_name = func_inst_name + SUBMODULE_MARKER + mux_false_port_name
      parser_state.existing_logic.wire_to_c_type[mux_false_connection_wire_name] = c_type
      false_logic.wire_to_c_type[mux_false_connection_wire_name]=c_type
      parser_state_for_false.existing_logic = false_logic
      false_read_logic = C_AST_REF_TOKS_TO_LOGIC(ref_toks, c_ast_node, [mux_false_connection_wire_name], mux_prepend_text+"FALSE_INPUT_"+MUX_LOGIC_NAME+"_", parser_state_for_false)
      # Merge in read
      false_logic.MERGE_COMB_LOGIC(false_read_logic)
      # Record input driving wire and type
      false_input_driving_wire = false_logic.wire_driven_by[mux_false_connection_wire_name]
      false_input_driving_wire_type = false_logic.wire_to_c_type[false_input_driving_wire]
      parser_state.existing_logic.wire_to_c_type[false_input_driving_wire] = false_input_driving_wire_type
      input_drivers.append(false_input_driving_wire)
      
      # Mux doesnt have connecitons from output right now
      # Instead mux changes most recent alias for a variable 
      output_driven_wire_names = []
      # Record type of output wire
      mux_output_wire_name = func_inst_name + SUBMODULE_MARKER + RETURN_WIRE_NAME
      parser_state.existing_logic.wire_to_c_type[mux_output_wire_name] = c_type
      ref_toks_id_str_to_output_wire[ref_tok_id_str] = mux_output_wire_name
      
      # Hook up the MUX instance now, adjust aliases after
      parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
                      mux_prepend_text,
                      func_c_ast_node,
                      func_base_name,
                      base_name_is_name,
                      input_drivers, # Wires or C ast nodes
                      input_driver_types, # Might be none if not known
                      input_port_names, # Port names on submodule
                      output_driven_wire_names,
                      parser_state)
      
      
      # Merge MUX instance this into true and false now so dont have to after TF merge at end
      # Mux instance occurs AFTER inputs so use SEQ MERGE
      #true_logic.MERGE_SEQ_LOGIC(parser_state.existing_logic)
      #false_logic.MERGE_SEQ_LOGIC(parser_state.existing_logic)
      
      
  # Merge T/F branches into existing logic
  # Wire aliases over time from the true and false branches CANT be merged  
  # since selection of final alias from either true or false branch is what THIS MUX DOES
  # Loop over and remove branch-only aliases over time
  # RV contains logic before T/F logic so orig aliases
  new_true_false_logic_wire_aliases_over_time = dict()
  for orig_var in merge_var_names:    
    # Filtered aliases contains orig from RV logic
    filtered_aliases = []
    original_aliases = []
    if orig_var in parser_state.existing_logic.wire_aliases_over_time:
      original_aliases = parser_state.existing_logic.wire_aliases_over_time[orig_var]
    filtered_aliases += original_aliases
      
    # Remove aliases not in original
    if orig_var in true_logic.wire_aliases_over_time:
      for alias in true_logic.wire_aliases_over_time[orig_var]:
        if alias in original_aliases:
          # Is in orig, keep if not in list already
          if not(alias in filtered_aliases):
            filtered_aliases.append(alias)
        
    if orig_var in false_logic.wire_aliases_over_time:
      for alias in false_logic.wire_aliases_over_time[orig_var]:
        if alias in original_aliases:
          # Is in orig, keep if not in list already
          if not(alias in filtered_aliases):
            filtered_aliases.append(alias)
      
    if len(filtered_aliases) > 0:
      new_true_false_logic_wire_aliases_over_time[orig_var] = filtered_aliases
            
  # Shared comb mergeable wire aliases over time
  true_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
  false_logic.wire_aliases_over_time = new_true_false_logic_wire_aliases_over_time
  # Pop off last elements of each branches not mergeable clock enables
  del true_logic.clock_enable_wires[-1]
  if len(c_ast_node.children()) >= 3:
    del false_logic.clock_enable_wires[-1]
  # Merge the true and false logic as parallel COMB logic since aliases over time fixed above
  true_logic.MERGE_COMB_LOGIC(false_logic)
  true_false_merged = true_logic

  # After TF merge we can have correct alias list include the mux output
  # Alias list for struct variable may be appended to multiple times
  # But since by def those drivings dont overlap then order doesnt really matter in aliases list
  for variable in merge_var_names:
    # vars declared inside and IF cannot be used outside that if so cannot/should not have MUX inputs+outputs
    declared_in_this_if = not(variable in parser_state.existing_logic.variable_names) and (variable not in parser_state.existing_logic.state_regs)
    if declared_in_this_if:
      continue
      
    # If not driven then skip
    if variable not in var_name_2_all_ref_toks_set:
      continue
    # Otherwise get drive orig wire names (already collapsed)
    all_ref_toks_set = var_name_2_all_ref_toks_set[variable]
    
    # Add mux output as alias for this var
    aliases = []
    if variable in true_false_merged.wire_aliases_over_time:
      aliases = true_false_merged.wire_aliases_over_time[variable]
      # Remove and re add after
      true_false_merged.wire_aliases_over_time.pop(variable)
    
    # Ok to add to same alias list multiple times for each orig_wire
    for ref_toks in all_ref_toks_set:
      ref_tok_id_str = C_AST_IF_REF_TOKS_TO_STR(ref_toks, c_ast_node)
      mux_connection_wire_name = ref_toks_id_str_to_output_wire[ref_tok_id_str]
      true_false_merged.alias_to_orig_var_name[mux_connection_wire_name] = variable
      true_false_merged.alias_to_driven_ref_toks[mux_connection_wire_name] = ref_toks
      # set the C type for output connection based on orig var name
      c_type = C_AST_REF_TOKS_TO_CONST_C_TYPE(ref_toks, c_ast_node, parser_state)
      true_false_merged.wire_to_c_type[mux_connection_wire_name] = c_type
      # Mux output just adds an alias over time to the original variable
      # So that the next read of the variable uses the mux output
      if not(mux_connection_wire_name in aliases):
        aliases.append(mux_connection_wire_name)
    
    # Re add if not empty list
    if len(aliases) > 0:
      true_false_merged.wire_aliases_over_time[variable] = aliases

  
  # Update parser state since aliases have been updated
  # HELP ME
  parser_state.existing_logic.MERGE_SEQ_LOGIC(true_false_merged)
  # TF merged has existing state, was merged when doing inputs
  #parser_state.existing_logic = true_false_merged
  
  return parser_state.existing_logic
  

def GET_CONTAINER_INST(inst_name):
  # Construct container from full inst name
  toks = inst_name.split(SUBMODULE_MARKER)
  container = SUBMODULE_MARKER.join(toks[0:len(toks)-1])
  return container
  
# For things that look like
# Get the last token (leaf) token when splitting by "/" and sub marker
def LEAF_NAME(name, do_submodule_split=False):
  new_name = name
  
  # Pick last submodule item 
  if (SUBMODULE_MARKER in name) and do_submodule_split:
    toks = new_name.split(SUBMODULE_MARKER)
    toks.reverse()
    new_name = toks[0]  
  
  # And last leaf item
  if "/" in new_name:
    toks = new_name.split("/")
    toks.reverse()
    new_name = toks[0]
    
  return new_name

# Function instance is module connection
# Connect certain input nodes to certain lists of wire names
# dict[c_ast_node] => [list of driven wire names]
def SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_wire_names, prepend_text, parser_state):
  rv = parser_state.existing_logic
  # Get logic for each connection and merge
  for c_ast_node in c_ast_node_2_driven_wire_names:
    driven_wire_names = c_ast_node_2_driven_wire_names[c_ast_node]
    parser_state.existing_logic = rv
    l = C_AST_NODE_TO_LOGIC(c_ast_node, driven_wire_names, prepend_text, parser_state)
    first = rv
    second = l
    first.MERGE_SEQ_LOGIC(second)
    rv = first
    parser_state.existing_logic = rv    
  
  return rv


def TRY_CONST_REDUCE_C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    output_driven_wire_names,
    parser_state):
    
  
  # Build instance name
  func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, func_c_ast_node)
  
  # Dont need to process input nodes with separate parser state since will remove old submodule if optimized away
  
  # Can't evaluate mixed wires and cast node inputs, func arg evaluation order is broken?
  
  # Input drivers can be c_ast nodes so evaluate those first
  c_ast_node_2_driven_input_wire_names = OrderedDict()
  for i in range(0, len(input_drivers)):
    input_driver = input_drivers[i]
    if isinstance(input_driver,c_ast.Node):
      input_port_name = input_port_names[i]
      input_wire_name = func_inst_name+SUBMODULE_MARKER+input_port_name
      c_ast_node_2_driven_input_wire_names[input_driver] = [input_wire_name]
  parser_state.existing_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
  
  # Other input drivers are just wires so connect those
  for i in range(0, len(input_drivers)):
    input_driver = input_drivers[i]
    if type(input_driver) == str:
      input_port_name = input_port_names[i]
      driven_input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
      parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, input_driver,[driven_input_port_wire], prepend_text, func_c_ast_node)   
  
  # Finally include types as passed in if able to
  
  # NOw inputs have been connected it is useful
  # Ex. FOR constant funcs x==1
  # To assign the type of driving wire if not assigned yet
  for i in range(0, len(input_drivers)):
    input_port_name = input_port_names[i]
    input_driver_type = input_driver_types[i]
    driven_input_wire_name = func_inst_name+SUBMODULE_MARKER+input_port_name
    if driven_input_wire_name in parser_state.existing_logic.wire_driven_by:
      driving_wire = parser_state.existing_logic.wire_driven_by[driven_input_wire_name]
      if driving_wire not in parser_state.existing_logic.wire_to_c_type:
        parser_state.existing_logic.wire_to_c_type[driving_wire] = input_driver_type
    
  # Global functions cannot optimize away
  is_global_func = False
  func_logic = None
  if func_base_name in parser_state.FuncLogicLookupTable:
    func_logic = parser_state.FuncLogicLookupTable[func_base_name]
    is_global_func = len(func_logic.state_regs) > 0 or func_logic.uses_nonvolatile_state_regs
  if is_global_func:
    return None
      
  # Check if can be replaced by constant output wire
  # Or reduced function due to partial constant inputs
  all_inputs_constant = True
  some_inputs_constant = False
  # Check parser_state.existing_logic for input ports driven by constants
  const_input_wires = []
  for i in range(0, len(input_drivers)):
    input_port_name = input_port_names[i]
    driven_input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
    const_driving_wire = FIND_CONST_DRIVING_WIRE(driven_input_port_wire, parser_state.existing_logic)
    const_input_wires.append(const_driving_wire)
    all_inputs_constant = all_inputs_constant and (const_driving_wire is not None)
    some_inputs_constant = some_inputs_constant or (const_driving_wire is not None)

  # If no constants then nothing to reduce
  if not(all_inputs_constant or some_inputs_constant):
    return None
    
  # For now, its an error if a totally constant function cannot be reduced

  # Some inputs may be constant, this changes the behavior/funcname of some functions
  #   Ex. constant shift is no longer the same logic binary op logic  (func name determines logic)
  #   Ex. Float mult by const -1 is just sign flip, TODO
  # If all inputs are constant then should be able replace function with constant
  #############################################################################################
  #
  # ALL INPUTS CONSTANT - REPLACE WITH CONSTANT
  if all_inputs_constant:
    const_val_str = None
    # Is this binary op?
    # TODO other things
    if func_base_name.startswith(BIN_OP_LOGIC_NAME_PREFIX) and not base_name_is_name:
      lhs_wire = const_input_wires[0]
      rhs_wire = const_input_wires[1]
      # Get values from constants
      lhs_val_str = GET_VAL_STR_FROM_CONST_WIRE(lhs_wire, parser_state.existing_logic, parser_state)
      rhs_val_str = GET_VAL_STR_FROM_CONST_WIRE(rhs_wire, parser_state.existing_logic, parser_state)
      # First check for integer arguments
      is_ints = True
      try:
        lhs_val = int(lhs_val_str)
        rhs_val = int(rhs_val_str)
      except:
        is_ints = False
      
      # Then allow for floats
      is_floats = False
      if not is_ints:
        is_floats = True
        try:
          lhs_val = float(lhs_val_str)
          rhs_val = float(rhs_val_str)
        except:
          is_floats = False
      
      # Number who?
      if not is_ints and not is_floats:
        print("Function", func_base_name, func_c_ast_node.coord, "is constant binary op of non numbers?")
        sys.exit(-1)
        
      # What type of binary op
      if func_base_name.endswith(BIN_OP_PLUS_NAME):
          const_val_str = str(lhs_val+rhs_val)
      elif func_base_name.endswith(BIN_OP_MINUS_NAME):
          const_val_str = str(lhs_val-rhs_val)
      elif func_base_name.endswith(BIN_OP_OR_NAME):
          const_val_str = str(lhs_val|rhs_val)
      elif func_base_name.endswith(BIN_OP_MULT_NAME):
          const_val_str = str(lhs_val*rhs_val)
      elif func_base_name.endswith(BIN_OP_DIV_NAME):
        # Div leaves group of ints and returns float
        if is_ints:
          const_val_str = str(int(lhs_val/rhs_val))
        else:
          const_val_str = str(lhs_val/rhs_val)
      elif func_base_name.endswith(BIN_OP_LT_NAME):
        const_val_str = "1" if lhs_val<rhs_val else "0"
      elif func_base_name.endswith(BIN_OP_LTE_NAME):
        const_val_str = "1" if lhs_val<=rhs_val else "0"
      elif func_base_name.endswith(BIN_OP_GT_NAME):
        const_val_str = "1" if lhs_val>rhs_val else "0"
      elif func_base_name.endswith(BIN_OP_GTE_NAME):
        const_val_str = "1" if lhs_val>=rhs_val else "0"
      elif func_base_name.endswith(BIN_OP_EQ_NAME):
        const_val_str = "1" if lhs_val==rhs_val else "0"
      # Bit operations
      elif func_base_name.endswith(BIN_OP_SR_NAME): 
        # SHIFT INT ONLY FOR NOW?
        if not is_ints:
          print("Constant bit operation function", func_base_name, func_c_ast_node.coord, "for ints only right now...")
          sys.exit(-1)
          
        # Output type is type of LHS
        c_type = parser_state.existing_logic.wire_to_c_type[lhs_wire]
        width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state, c_type)
        # Thanks stackoverflow for twos comp BullSHEEIITITT FUCK ECE 200
        def int2bin(integer, digits):
          if integer >= 0:
            return bin(integer)[2:].zfill(digits)
          else:
            return bin(2**digits + integer)[2:]
        # STACKOVERFLOW MY MAN
        def to_int(bin):
          x = int(bin, 2)
          if bin[0] == '1': # "sign bit", big-endian
             x -= 2**len(bin)
          return x
        
        # TODO actually use this if
        if func_base_name.endswith(BIN_OP_SR_NAME):
          # lhs_val >> rhs_val
          lhs_bin_str = int2bin(lhs_val, width)
          fill_bit = "0"
          if VHDL.C_TYPE_IS_INT_N(c_type):
            fill_bit = lhs_bin_str[0] # Sign bit
          fill_bits = fill_bit * rhs_val
          output_bin_str = (fill_bits + lhs_bin_str)[0:width]
          output_int = to_int(output_bin_str)
          const_val_str = str(output_int)
        else:
          print("Unsupported const bit operation")
          sys.exit(-1)
      else:
        print("Function", func_base_name, func_c_ast_node.coord, "is constant binary op yet to be supported.",func_base_name)
        sys.exit(-1)
    elif (func_logic is not None) and SW_LIB.IS_BIT_MANIP(func_logic):
      # TODO
      return None    
    # CASTING
    elif func_base_name == CAST_FUNC_NAME_PREFIX and not base_name_is_name :
      in_t = parser_state.existing_logic.wire_to_c_type[const_input_wires[0]]
      out_t = parser_state.existing_logic.wire_to_c_type[output_driven_wire_names[0]]
      in_val_str = GET_VAL_STR_FROM_CONST_WIRE(const_input_wires[0], parser_state.existing_logic, parser_state)
      if VHDL.C_TYPES_ARE_INTEGERS([in_t]) and out_t == "float":
        const_val_str = str(float(in_val_str))
      elif in_t == "float" and VHDL.C_TYPES_ARE_INTEGERS([out_t]) :
        const_val_str = str(int(float(in_val_str)))
      else:
        print("How to cast? ", in_t,in_val_str,"->",out_t, func_c_ast_node.coord, prepend_text)
        sys.exit(-1) 
        
    # MATH FUNCS
    elif func_base_name == "sqrt" and base_name_is_name:
      in_val_str = GET_VAL_STR_FROM_CONST_WIRE(const_input_wires[0], parser_state.existing_logic, parser_state)
      in_val = float(in_val_str)
      out_val = math.sqrt(in_val)
      const_val_str = str(out_val)  
    elif func_base_name == "cos" and base_name_is_name:
      in_val_str = GET_VAL_STR_FROM_CONST_WIRE(const_input_wires[0], parser_state.existing_logic, parser_state)
      in_val = float(in_val_str)
      out_val = math.cos(in_val)
      const_val_str = str(out_val)
    elif func_base_name == "sin" and base_name_is_name:
      in_val_str = GET_VAL_STR_FROM_CONST_WIRE(const_input_wires[0], parser_state.existing_logic, parser_state)
      in_val = float(in_val_str)
      out_val = math.sin(in_val)
      const_val_str = str(out_val)
    # CONST REFs are ok not to reduce for now. I.e CANNOT PROPOGATE CONSTANTS through compound references (structs, arrays)
    elif func_base_name.startswith(CONST_REF_RD_FUNC_NAME_PREFIX):
      return None
    # If func has no inputs and is not global then must be const
    # similar to above cant propogate consts through compound types yet?
    elif len(input_drivers) == 0:
      return None
    else:
      print("WARNING: Not reducing constant function call:")
      print(func_inst_name, end=' ')
      print(func_base_name, func_c_ast_node.coord)
      sys.exit(-1)
      return None
    
    # Going to replace with constant
    # Remove old submodule instance
    #print "Replacing:",func_inst_name,"with constant",const_val_str
    parser_state.existing_logic.REMOVE_SUBMODULE(func_inst_name, input_port_names)
        
    # Connect const wire to output wire and return
    # Do connection using real parser state and logic
    is_negated = False
    if const_val_str.startswith("-"):
      const_val_str = const_val_str.lstrip("-")
      is_negated = True
    parser_state.existing_logic = CONST_VALUE_STR_TO_LOGIC(const_val_str, func_c_ast_node, output_driven_wire_names, prepend_text, parser_state, is_negated)
    
    
    return parser_state.existing_logic
  
  
  #############################################################################################
  # 
  # SOME INPUTS CONSTANT - REPLACE WITH ALTERNATE FUNCTION
  #
  new_func_base_name = None
  new_base_name_is_name = False
  new_input_drivers = [] # Wires or C ast nodes
  new_input_driver_types = [] # Might be none if not known
  new_input_port_names = [] # Port names on submodule
  is_reducable = False
  # TODO other things
  # CONSTANT SHIFT LEFT
  if func_base_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SL_NAME) and const_input_wires[1] is not None:
    # Replace with const
    rhs_wire = const_input_wires[1]
    rhs_val_str = GET_VAL_STR_FROM_CONST_WIRE(rhs_wire, parser_state.existing_logic, parser_state)
    new_func_base_name = CONST_PREFIX + BIN_OP_SL_NAME + "_" + rhs_val_str
    new_base_name_is_name = False # needs types
    new_input_drivers = [input_drivers[0]] # Dont need RHS, is const
    new_input_driver_types = [input_driver_types[0]]
    new_input_port_names = ["x"] # One input port, not LHS or RHS\
    new_func_inst_name = BUILD_INST_NAME(prepend_text,new_func_base_name, func_c_ast_node)
    new_output_wire = new_func_inst_name + SUBMODULE_MARKER + RETURN_WIRE_NAME
    parser_state.existing_logic.wire_to_c_type[new_output_wire] = new_input_driver_types[0] # Shift outputs LHS type
    is_reducable = True
  # CONSTANT SHIFT RIGHT  
  elif func_base_name.startswith(BIN_OP_LOGIC_NAME_PREFIX + "_" + BIN_OP_SR_NAME) and const_input_wires[1] is not None:
    # Replace with const
    rhs_wire = const_input_wires[1]
    rhs_val_str = GET_VAL_STR_FROM_CONST_WIRE(rhs_wire, parser_state.existing_logic, parser_state)
    new_func_base_name = CONST_PREFIX + BIN_OP_SR_NAME + "_" + rhs_val_str
    new_base_name_is_name = False # needs types
    new_input_drivers = [input_drivers[0]] # Dont need RHS, is const
    new_input_driver_types = [input_driver_types[0]]
    new_input_port_names = ["x"] # One input port, not LHS or RHS
    new_func_inst_name = BUILD_INST_NAME(prepend_text,new_func_base_name, func_c_ast_node)
    new_output_wire = new_func_inst_name + SUBMODULE_MARKER + RETURN_WIRE_NAME
    parser_state.existing_logic.wire_to_c_type[new_output_wire] = new_input_driver_types[0] # Shift outputs LHS type
    is_reducable = True
  # CONSTANT condition MUX
  elif func_base_name == MUX_LOGIC_NAME and const_input_wires[0] is not None:
    # Easier to do in C_AST_IF, can not evaluate branch in full instead of just removing MUX func here
    print("Hey you did a bad job at your job reducing MUXES. Atlas Sound w. Noah Lennox - Walkabout")
    sys.exit(-1)
  # Not a reducable function
  if not is_reducable:
    return None
    
  # Remove old submodule instance
  #print "Replacing:",func_inst_name, "with reduced function", new_func_base_name
  parser_state.existing_logic.REMOVE_SUBMODULE(func_inst_name,input_port_names)
  
  # And remove the constant wires that were optimized away ?
  #@GAHMAKETHIS PART OF REMOVE SUBMODULE OR WHAT?????
  
  # Can reduce, do logic to for reduced funciton
  parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
      prepend_text,
      func_c_ast_node,
      new_func_base_name,
      new_base_name_is_name,
      new_input_drivers, # Wires or C ast nodes
      new_input_driver_types, # Might be none if not known
      new_input_port_names, # Port names on submodule
      output_driven_wire_names,
      parser_state)   
  
  return parser_state.existing_logic


# ORDER OF N ARGS MATTERS
#_funcd = []
def C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    output_driven_wire_names,
    parser_state):
      
  #@@@@@@@@@ Maybe just require casting operation instead?  don't allow float + int  (bin op still changes to float+float  and errors connecting int to float ???
  #  Maybe?^ SEEMS RIGHT
  '''
  # OTherwise? \/
  @TODO if defined in C code use parsed C def for types
  @OTHERwise  need to infer types with LOOKAHEAD "precast" wires  (TODO remove if extra?)
  @##@ Once types of inputs are looked ahead you need to let each func change the types
  @# Ex. bin op  float + int  is actually  float + (float)int
  @# Then do APPLY_/ SEQ_C    
  '''
  
  # Build instance name
  func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, func_c_ast_node)
  
  # Should not be evaluating c ast node if driver is already known
  for input_i in range(0, len(input_port_names)):
    input_port_name = input_port_names[input_i]
    input_port_wire = func_inst_name + SUBMODULE_MARKER + input_port_name
    if input_port_wire in parser_state.existing_logic.wire_driven_by and isinstance(input_drivers[input_i],c_ast.Node):
      print("Why evaluating c ast node", input_drivers[input_i], "input to", func_inst_name)
      print("When it is known that input",input_port_wire," is driven by:", parser_state.existing_logic.wire_driven_by[input_port_wire])
      sys.exit(-1)
  
  # Try to determine output type
  # Should be knowable except for mux, which can be inferred
  # Set type for outputs based on func_name (only base name known right now? base name== func name for parsed C coe) if possible
  if func_base_name in parser_state.FuncLogicLookupTable:
    func_def_logic_object = parser_state.FuncLogicLookupTable[func_base_name]
    if len(func_def_logic_object.outputs) > 0:
      # Get type of output
      output_type = func_def_logic_object.wire_to_c_type[RETURN_WIRE_NAME]
      # Set this type for the output if not set already? # This seems really hacky
      for output_driven_wire_name in output_driven_wire_names:
        if(not(output_driven_wire_name in parser_state.existing_logic.wire_to_c_type)):
          parser_state.existing_logic.wire_to_c_type[output_driven_wire_name] = output_type
  
  # Set type for outputs based on output port if possible
  output_wire_name=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
  if output_wire_name in parser_state.existing_logic.wire_to_c_type:
    output_type = parser_state.existing_logic.wire_to_c_type[output_wire_name]
    # Set this type for the driven wires if not set already? # This seems really hacky
    for output_driven_wire_name in output_driven_wire_names:
      if(not(output_driven_wire_name in parser_state.existing_logic.wire_to_c_type)):
        parser_state.existing_logic.wire_to_c_type[output_driven_wire_name] = output_type
  
  # Set mux type? Hacky wtf?
  if func_base_name==MUX_LOGIC_NAME:
    if output_wire_name not in parser_state.existing_logic.wire_to_c_type:
      parser_state.existing_logic.wire_to_c_type[output_wire_name] = input_driver_types[1] #[0] is cond for mux
    
  #print "func_base_name",func_base_name,"out",parser_state.existing_logic.wire_to_c_type[output_wire_name]
  
  # Is this a constant or reduceable func call?
  const_reduced_logic = TRY_CONST_REDUCE_C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            func_c_ast_node,
            func_base_name,
            base_name_is_name,
            input_drivers, # Wires or C ast nodes
            input_driver_types, # Might be none if not known
            input_port_names, # Port names on submodule
            output_driven_wire_names,
            parser_state)
  if const_reduced_logic is not None:
    return const_reduced_logic
    
  
  # Build func name
  output_type = "void"
  if output_wire_name in parser_state.existing_logic.wire_to_c_type:
    output_type = parser_state.existing_logic.wire_to_c_type[output_wire_name]
  func_name = BUILD_FUNC_NAME(func_base_name, output_type, input_driver_types, base_name_is_name)
  # Sub module inst
  parser_state.existing_logic.submodule_instances[func_inst_name] = func_name
  # C ast node
  parser_state.existing_logic.submodule_instance_to_c_ast_node[func_inst_name]=func_c_ast_node
  
  # Connect clock enable for this func if needed
  if func_name in parser_state.FuncLogicLookupTable:
    func_def_logic_object = parser_state.FuncLogicLookupTable[func_name]
    if LOGIC_NEEDS_CLOCK_ENABLE(func_def_logic_object, parser_state):
      ce_driver_wire = parser_state.existing_logic.clock_enable_wires[-1]
      func_ce_wire = func_inst_name+SUBMODULE_MARKER+CLOCK_ENABLE_NAME
      #print(func_ce_wire,"<=",ce_driver_wire)
      parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, ce_driver_wire,[func_ce_wire], prepend_text, func_c_ast_node)  

  # Record all input port names for this submodule
  # This might not be needed but not thinking about that now
  parser_state.existing_logic.submodule_instance_to_input_port_names[func_inst_name] = input_port_names[:]
  
  # Try to record input wire types, think this NEEDS to work here
  for i in range(0, len(input_drivers)):
    input_port_name = input_port_names[i]
    input_driver_type = input_driver_types[i]
    driven_input_wire_name = func_inst_name+SUBMODULE_MARKER+input_port_name

    # Sanity check types instead of relying on them
    # Check type for input based on func_name if possible
    if func_name in parser_state.FuncLogicLookupTable:
      func_def_logic_object = parser_state.FuncLogicLookupTable[func_name]
      # Get port name from driven wire
      func_port_type = func_def_logic_object.wire_to_c_type[input_port_name]
      if input_driver_type != func_port_type:
        print(func_inst_name, "port", input_port_name, "mismatched types per func def?",input_driver_type, func_port_type)
        sys.exit(-1)
      #parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = func_port_type
      
    ## Do we know the type as passed?
    #elif input_driver_type is not None:
    # # Great, save that if needed
    # if driven_input_wire_name not in parser_state.existing_logic.wire_to_c_type:
    #   parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = driving_wire_c_type
    
    if driven_input_wire_name in parser_state.existing_logic.wire_driven_by:
      # Set type for this wire by type of wire that drives this
      # Type of driving wire
      driving_wire = parser_state.existing_logic.wire_driven_by[driven_input_wire_name]
      if driving_wire in parser_state.existing_logic.wire_to_c_type:
        driving_wire_c_type = parser_state.existing_logic.wire_to_c_type[driving_wire]
        if input_driver_type != driving_wire_c_type:
          # Allow mismatching uint <= enum
          if VHDL.C_TYPE_IS_UINT_N(input_driver_type) and C_TYPE_IS_ENUM(driving_wire_c_type, parser_state):
            pass
          # Allow integer casting ... eventually think this through
          elif VHDL.C_TYPES_ARE_INTEGERS([input_driver_type,driving_wire_c_type]):
            #and VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state,driving_wire_c_type) >= VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state,input_driver_type) ):
            pass
          else:
            print("Input index:",i, "(total", len(input_drivers), ")", input_port_names, input_driver_types)
            print("driven_input_wire_name",driven_input_wire_name)
            print("driving_wire",driving_wire)
            print(func_inst_name, "port", input_port_name, "mismatched types?",input_driver_type, driving_wire_c_type)
            print(func_c_ast_node)
            print(0/0)
            sys.exit(-1)
        #if driven_input_wire_name not in parser_state.existing_logic.wire_to_c_type:
        # parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = driving_wire_c_type
    
    # SAVE TYPE
    parser_state.existing_logic.wire_to_c_type[driven_input_wire_name] = input_driver_type
    
  ################################# INPUTS DONE ##########################################
  
  # Outputs
  # Add wire even if below it ends up driving nothing
  # need this to see the unconnected wire and rip up form there
  #     ~~~ Akron/Family - Franny/You're Human ~~~
  parser_state.existing_logic.wires.add(output_wire_name)
  # Finally connect the output of this operation to each of the driven wires
  if len(output_driven_wire_names) > 0:
    parser_state.existing_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, output_wire_name, output_driven_wire_names, prepend_text, func_c_ast_node)
  
  return parser_state.existing_logic
    

def LOGIC_NEEDS_CLOCK_ENABLE(logic, parser_state):
  # Look for clock cross submodule ending in _READ() implying input 
  i_need = len(logic.state_regs) > 0 or logic.uses_nonvolatile_state_regs
  
  if SW_LIB.IS_CLOCK_CROSSING(logic):
    var = CLK_CROSS_FUNC_TO_VAR_NAME(logic.func_name)
    clk_cross_info = parser_state.clk_cross_var_info[var]
    i_need = clk_cross_info.flow_control
  
  # Check submodules too
  needs = i_need
  if needs:
    return True
  for inst in logic.submodule_instances:
    submodule_logic_name = logic.submodule_instances[inst]
    # If not in FuncLogicLookupTable then not parsed from C code, couldnt need clock enable
    if submodule_logic_name in parser_state.FuncLogicLookupTable:
      submodule_logic = parser_state.FuncLogicLookupTable[submodule_logic_name]
      needs = needs or LOGIC_NEEDS_CLOCK_ENABLE(submodule_logic, parser_state)
      if needs:
        return True
    
  return needs

def BUILD_FUNC_NAME(func_base_name, output_type, input_driver_types, base_name_is_name):
  # Build func name
  func_name = func_base_name
  if not base_name_is_name:
    types_str = ""
    # Output type
    types_str += "_" + output_type.replace("[","_").replace("]","")
    # Append input types to base name
    for input_driver_type in input_driver_types:
      if input_driver_type is None:
        print("oh no, now it is")
        sys.exit(-1)
      # Input could be array type with brackets so remove for safe C func name
      types_str += "_" + input_driver_type.replace("[","_").replace("]","")
    
    func_name = func_base_name + types_str
  
  return func_name  

# Base name only is different for built in ops
# OK to use only base name (no types)
# here since this inst name is only leaf, full inst name will be type specific
# Func name will be type specific
def BUILD_INST_NAME(prepend_text,func_base_name, c_ast_node):
  file_coord_str = C_AST_NODE_COORD_STR(c_ast_node)
  inst_name = prepend_text + func_base_name + "[" + file_coord_str + "]"
  return inst_name
  
def C_AST_VHDL_TEXT_FUNC_CALL_TO_LOGIC(c_ast_func_call,driven_wire_names,prepend_text,parser_state):
  #print c_ast_func_call.coord
  #casthelp(c_ast_func_call)
  #sys.exit(-1)
  
  # One vhdl text func call marks logic - hello future me?
  parser_state.existing_logic.is_vhdl_text_module = True
  
  # Mark as using globals, cant be sliced
  parser_state.existing_logic.uses_nonvolatile_state_regs = True
  
  func_name = str(c_ast_func_call.name.name)
  #print "FUNC CALL:",func_name,c_ast_func_call.coord
  func_base_name = func_name
  func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_func_call)
  
  # Return n arg func?
  # Can use same func name and use submodule_instance_to_c_ast_node to get text?
  
  base_name_is_name = True
  input_drivers = []
  input_driver_types = []
  input_port_names = []
  output_driven_wire_names = driven_wire_names
  
  # Record output port type as the to_type
  #output_wire_name=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
  #output_t = None
  #parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_t
  
  return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    c_ast_func_call,
    func_base_name,
    base_name_is_name,
    input_drivers,
    input_driver_types,
    input_port_names,
    output_driven_wire_names,
    parser_state)
  
def C_AST_FUNC_CALL_TO_LOGIC(c_ast_func_call,driven_wire_names,prepend_text,parser_state):
  FuncLogicLookupTable = parser_state.FuncLogicLookupTable
  func_name = str(c_ast_func_call.name.name)
  #print "FUNC CALL:",func_name,c_ast_func_call.coord
  func_base_name = func_name
  func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_func_call)
  if not(func_name in FuncLogicLookupTable):
    # Uhh.. lets check for some built in compiler things because
    # stacking complexity without real planning is like totally rad
    if func_name == VHDL_FUNC_NAME:
      return C_AST_VHDL_TEXT_FUNC_CALL_TO_LOGIC(c_ast_func_call,driven_wire_names,prepend_text,parser_state)
      
    # Ok panic
    print("C_AST_FUNC_CALL_TO_LOGIC Havent parsed func name '", func_name, "' yet. Where does that function come from?")
    print(c_ast_func_call.coord)
    #casthelp(c_ast_func_call)
    sys.exit(-1)
  not_inst_func_logic = FuncLogicLookupTable[func_name]
    
  # N input port names named by their arg name
  # Decompose inputs to N ARG FUNCTION
  input_drivers = [] # Wires or C ast nodes
  input_driver_types = [] # Might be none if not known
  input_port_names = [] # Port names on submodule
  
  # Helpful check
  if c_ast_func_call.args is not None:
    if len(c_ast_func_call.args.exprs) != len(not_inst_func_logic.inputs):
      print("The function definition for",func_name,"has",len(c_ast_func_call.args.exprs), "arguments.")
      print("as used at", c_ast_func_call.coord, "it has", len(not_inst_func_logic.inputs), "arguments.")
      sys.exit(-1)
  
  # Assume inputs are in arg order
  for i in range(0, len(not_inst_func_logic.inputs)):
    input_port_name = not_inst_func_logic.inputs[i]
    input_port_wire = func_inst_name+SUBMODULE_MARKER+input_port_name
    input_c_ast_node = c_ast_func_call.args.exprs[i]
    input_c_type = not_inst_func_logic.wire_to_c_type[input_port_name]  
    input_drivers.append(input_c_ast_node)
    input_driver_types.append(input_c_type)
    input_port_names.append(input_port_name)
    
    
  # Output is type of logic not_inst_func_logic output wire
  if len(not_inst_func_logic.outputs) > 0:
    if len(not_inst_func_logic.outputs) != 1:
      print("Whats going on here multiple outputs??")
      sys.exit(-1)
    output_port_name = not_inst_func_logic.outputs[0]
    output_c_type = not_inst_func_logic.wire_to_c_type[output_port_name]
    output_wire = func_inst_name+SUBMODULE_MARKER+output_port_name
    parser_state.existing_logic.wire_to_c_type[output_wire] = output_c_type
  
  # Before evaluating input nodes make sure type of port is there so constants can be evaluated
  # Get types from func defs
  func_def_logic_object = FuncLogicLookupTable[func_name]
  for input_port in func_def_logic_object.inputs:
    input_port_wire = func_inst_name + SUBMODULE_MARKER + input_port
    parser_state.existing_logic.wire_to_c_type[input_port_wire] = func_def_logic_object.wire_to_c_type[input_port]  

  # Decompose inputs to N ARG FUNCTION
  func_c_ast_node = c_ast_func_call
  func_base_name = func_name # Is C name so unique
  base_name_is_name = True
  parser_state.existing_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    driven_wire_names,
    parser_state)
  
  return parser_state.existing_logic
  
def C_AST_CAST_TO_LOGIC(c_ast_node,driven_wire_names,prepend_text, parser_state):
  # Need to evaluate input node/type first
  func_base_name = CAST_FUNC_NAME_PREFIX
  func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_node)
  input_port_name = "rhs"
  input_port_wire = func_inst_name + SUBMODULE_MARKER + input_port_name
  parser_state.existing_logic = C_AST_NODE_TO_LOGIC(c_ast_node.expr, [input_port_wire], prepend_text, parser_state)
  rhs_type = parser_state.existing_logic.wire_to_c_type[input_port_wire]
  rhs_driver_wire = parser_state.existing_logic.wire_driven_by[input_port_wire]
  
  # Return n arg func
  base_name_is_name = False # append types in name too
  input_drivers = [rhs_driver_wire]
  input_driver_types = [rhs_type]
  input_port_names = [input_port_name]
  output_driven_wire_names = driven_wire_names
  # Record output port type as the to_type
  output_wire_name=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
  #casthelp(c_ast_node.to_type.type.type.names[0])
  #sys.exit(-1)
  output_t = str(c_ast_node.to_type.type.type.names[0])
  parser_state.existing_logic.wire_to_c_type[output_wire_name] = output_t
  
  return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers,
    input_driver_types,
    input_port_names,
    output_driven_wire_names,
    parser_state)
    
def C_TYPE_SIZE(c_type, parser_state, allow_fail=False, c_ast_node=None):
  if C_TYPE_IS_ARRAY(c_type):
    elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_type)
    elem_size = C_TYPE_SIZE(elem_t, parser_state)
    byte_size = elem_size
    for dim in dims:
      byte_size = byte_size * dim
  elif C_TYPE_IS_STRUCT(c_type, parser_state):
    field_to_type_dict = parser_state.struct_to_field_type_dict[c_type]
    byte_size = 0;
    for field in field_to_type_dict:
      field_type = field_to_type_dict[field]
      field_size = C_TYPE_SIZE(field_type,parser_state)
      byte_size = byte_size + field_size
  elif VHDL.C_TYPES_ARE_INTEGERS([c_type]):
    bit_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(c_type)
    byte_size = int(math.ceil(float(bit_width)/float(8)))
  elif c_type == "float":
    return 4
  elif C_TYPE_IS_ENUM(c_type,parser_state):
    bit_width = VHDL.GET_WIDTH_FROM_C_TYPE_STR(parser_state,c_type)
    byte_size = int(math.ceil(float(bit_width)/float(8)))
  else:
    if not allow_fail:
      print("How to sizeof",c_type, "???")
      if c_ast_node:
        print(c_ast_node)
        print(c_ast_node.coord)
      else:
        print(0/0)
      #print("parser_state.struct_to_field_type_dict",parser_state.struct_to_field_type_dict)
      sys.exit(-1)
    byte_size = -1
  
  return byte_size
    
def C_AST_SIZEOF_TO_LOGIC(c_ast_node,driven_wire_names, prepend_text, parser_state):
  # This is weird - todo error check
  c_type_str = c_ast_node.expr.type.type.names[0];
  # Replace with constant
  size = C_TYPE_SIZE(c_type_str, parser_state, False, c_ast_node)
  value_str = str(size)
  is_negated = False
  return CONST_VALUE_STR_TO_LOGIC(value_str, c_ast_node, driven_wire_names, prepend_text, parser_state, is_negated)
  
def C_AST_UNARY_OP_TO_LOGIC(c_ast_unary_op,driven_wire_names, prepend_text, parser_state):
  # What op?
  c_ast_unary_op_str = str(c_ast_unary_op.op)
  
  # Apparently sizeof() is a unary op - cool
  if c_ast_unary_op_str == "sizeof":
    # Replace with constant
    return C_AST_SIZEOF_TO_LOGIC(c_ast_unary_op,driven_wire_names, prepend_text, parser_state)
  
  # Decompose to N arg func
  existing_logic = parser_state.existing_logic
  
  # Is this UNARY op negating a constant?
  if (c_ast_unary_op_str=="-") and (type(c_ast_unary_op.expr) == c_ast.Constant):
    # THis is just a constant wire with negative value
    return C_AST_CONSTANT_TO_LOGIC(c_ast_unary_op.expr,driven_wire_names, prepend_text, parser_state, is_negated=True)
  
  # Determine op string to use in func name
  if c_ast_unary_op_str == "!" or c_ast_unary_op_str == "~":
    c_ast_op_str = UNARY_OP_NOT_NAME
  else:
    print("Unsupported unary op '" + c_ast_unary_op_str + "'?", c_ast_unary_op.coord)
    sys.exit(-1)
    
  # Set port names based on func name
  func_base_name = UNARY_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
  base_name_is_name = False # No needs types attached
  input_drivers = [] # Wires or C ast nodes
  input_driver_types = [] # Might be none if not known
  input_port_names = [] # Port names on submodule
  
  
  # Get input wire type by evaluating input expressions
  func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_unary_op) 
  unary_op_input_port_name = c_ast_unary_op.children()[0][0]
  input_port_names.append(unary_op_input_port_name)
  unary_op_input = func_inst_name+SUBMODULE_MARKER+unary_op_input_port_name
  unary_op_output=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME

  # Inputs
  # Decompose inputs to N ARG FUNCTION
  # dict[c_ast_input_node] => [list of driven wire names]
  c_ast_node_2_driven_input_wire_names = OrderedDict()
  c_ast_node_2_driven_input_wire_names[c_ast_unary_op.expr] = [unary_op_input]
  
  # Before evaluating input nodes make sure type of port is there so constants can be evaluated
  # Input must be non const or wtf guys
  parser_state.existing_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
  if unary_op_input in parser_state.existing_logic.wire_to_c_type:
    input_type = parser_state.existing_logic.wire_to_c_type[unary_op_input]
  else:
    print(func_inst_name, "looks like a constant unary op, what's going on?")
    print("parser_state.existing_logic.wire_to_c_type")
    print(parser_state.existing_logic.wire_to_c_type)
    sys.exit(-1)
  
  expr_type = parser_state.existing_logic.wire_to_c_type[unary_op_input]
  input_driver_types.append(expr_type)
  in_driver_wire = parser_state.existing_logic.wire_driven_by[unary_op_input]
  input_drivers.append(in_driver_wire)
  
  # Determine output type based on operator or driving wire type
  driven_c_type_str = GET_C_TYPE_FROM_WIRE_NAMES(driven_wire_names, parser_state.existing_logic, allow_fail=True)
  if driven_c_type_str is not None:
    # Most unary ops use the type of the driven wire
    if c_ast_unary_op_str == "!" or c_ast_unary_op_str == "~":
      output_c_type = driven_c_type_str
    else:
      print("Output C type for c_ast_unary_op_str '" + c_ast_unary_op_str + "'?")
      sys.exit(-1) 
    # Set type for output wire
    parser_state.existing_logic.wire_to_c_type[unary_op_output] = output_c_type
  
  # Otherwise use input expr type?  
  if unary_op_output not in parser_state.existing_logic.wire_to_c_type:
    parser_state.existing_logic.wire_to_c_type[unary_op_output] = expr_type

  
  func_c_ast_node = c_ast_unary_op
  func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    driven_wire_names,
    parser_state)

  parser_state.existing_logic = func_logic
  

  return func_logic

def C_AST_BINARY_OP_TO_LOGIC(c_ast_binary_op,driven_wire_names,prepend_text, parser_state):
  #print c_ast_binary_op
  #print C_AST_NODE_COORD_STR(c_ast_binary_op)
  #print "=="
  
  # Decompose to N arg func
  c_ast_bin_op_str = str(c_ast_binary_op.op)
  
  # Determine op string to use in func name
  if c_ast_bin_op_str == ">":
    c_ast_op_str = BIN_OP_GT_NAME
  elif c_ast_bin_op_str == ">=":
    c_ast_op_str = BIN_OP_GTE_NAME
  elif c_ast_bin_op_str == "<":
    c_ast_op_str = BIN_OP_LT_NAME
  elif c_ast_bin_op_str == "<=":
    c_ast_op_str = BIN_OP_LTE_NAME
  elif c_ast_bin_op_str == "+":
    c_ast_op_str = BIN_OP_PLUS_NAME
  elif c_ast_bin_op_str == "-":
    c_ast_op_str = BIN_OP_MINUS_NAME
  elif c_ast_bin_op_str == "*":
    c_ast_op_str = BIN_OP_MULT_NAME
  elif c_ast_bin_op_str == "/":
    c_ast_op_str = BIN_OP_DIV_NAME
  elif c_ast_bin_op_str == "==":
    c_ast_op_str = BIN_OP_EQ_NAME
  elif c_ast_bin_op_str == "!=":
    c_ast_op_str = BIN_OP_NEQ_NAME
  elif c_ast_bin_op_str == "&":
    c_ast_op_str = BIN_OP_AND_NAME
  elif c_ast_bin_op_str == "|":
    c_ast_op_str = BIN_OP_OR_NAME
  elif c_ast_bin_op_str == "^":
    c_ast_op_str = BIN_OP_XOR_NAME
  elif c_ast_bin_op_str == "<<":
    c_ast_op_str = BIN_OP_SL_NAME
  elif c_ast_bin_op_str == ">>":
    c_ast_op_str = BIN_OP_SR_NAME
  elif c_ast_bin_op_str == "%":
    c_ast_op_str = BIN_OP_MOD_NAME
  elif c_ast_bin_op_str == "&&" or c_ast_bin_op_str == "||":
    print("No bool types, use bitwise operators, &,|, etc..", c_ast_binary_op.coord)
    sys.exit(-1)
  else:
    print("BIN_OP name for c_ast_bin_op_str '" + c_ast_bin_op_str + "'?")
    sys.exit(-1)
    
  # Set port names based on func name
  func_base_name = BIN_OP_LOGIC_NAME_PREFIX + "_" + c_ast_op_str
  base_name_is_name = False # Need types attached
  
  # Inputs
  # Decompose for SEQ_C_AST_NODES_TO_LOGIC 
  # dict[c_ast_input_node] => [list of driven wire names]
  # How to resolve type of () + () ?
  # Must evaluate in advance
  bin_op_left_input_port_name = c_ast_binary_op.children()[0][0]
  bin_op_right_input_port_name = c_ast_binary_op.children()[1][0]
  func_inst_name = BUILD_INST_NAME(prepend_text,func_base_name, c_ast_binary_op)
  bin_op_left_input = func_inst_name+SUBMODULE_MARKER+bin_op_left_input_port_name
  bin_op_right_input = func_inst_name+SUBMODULE_MARKER+bin_op_right_input_port_name
  c_ast_node_2_driven_input_wire_names = OrderedDict()
  c_ast_node_2_driven_input_wire_names[c_ast_binary_op.left] = [bin_op_left_input]
  c_ast_node_2_driven_input_wire_names[c_ast_binary_op.right] = [bin_op_right_input]
  parser_state.existing_logic = SEQ_C_AST_NODES_TO_LOGIC(c_ast_node_2_driven_input_wire_names, prepend_text, parser_state)
  
  # Was either input type evaluated?
  left_type = None
  if bin_op_left_input in parser_state.existing_logic.wire_to_c_type:
    left_type = parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
  right_type = None
  if bin_op_right_input in parser_state.existing_logic.wire_to_c_type:
    right_type = parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
  
  # Output is determined by funcitonality - NOT WHAT the functionality drives
  output_c_type = None
  
  # By now the input wires have been connected - CAST inserted as needed
  # From here on we can only adjust input wires in ways that can be resolved with
  #   VHDL 0 CLK CAST OPERATIONS ONLY - i.e. signed to unsigned, resize, enum to unsigned, etc
  
  #@@@@ CANT Resolve missing types SINCE other type could be anything - might not be resolvable in VHDL 0CLK
  
  # THIS IS OK SINCE CAN BE RESOLVED IN VHDL 0 CLK CAST
  # If types are integers then check signed/unsigned matches
  #   Change type from unsigned to sign by adding bit to type
  #   Never change signed to unsigned dumb
  if VHDL.C_TYPES_ARE_INTEGERS([left_type,right_type]):
    left_signed = VHDL.C_TYPE_IS_INT_N(left_type)
    right_signed = VHDL.C_TYPE_IS_INT_N(right_type)
    left_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_type)
    right_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_type)
    if left_signed != right_signed:
      if left_signed:
        # Update right
        right_type = "int" + str(right_width+1) + "_t"
        parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type 
      if right_signed:
        # Update left
        left_type = "int" + str(left_width+1) + "_t"
        parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
  
  # THIS IS OK SINCE CAN BE RESOLVED IN 0 CLK VHDL CAST
  # Replace ENUM with INT type of input wire so cast happens? :/?
  # Left
  if left_type in parser_state.enum_to_ids_dict:
    #print "left enum"
    # Set BIN OP input wire as UINT
    enum_type = left_type
    num_ids = len(parser_state.enum_to_ids_dict[enum_type])
    left_width = int(math.ceil(math.log(num_ids,2)))
    left_type = "uint" + str(left_width) + "_t"
    # Set driver of input as ENUM
    # This is really only necessary for constant driving wires
    # which wont have known type without this
    # works fine for non constant wires too though
    driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
    parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
    #print "driving_wire",driving_wire,enum_type  
    # If right type is unknown assume it also? Only OK for ENUMS?
    if right_type is None:
      right_type = left_type
      parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
      driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
      parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
  # Right
  if right_type in parser_state.enum_to_ids_dict:
    # Set BIN OP input wire as UINT
    enum_type = right_type
    num_ids = len(parser_state.enum_to_ids_dict[enum_type])
    right_width = int(math.ceil(math.log(num_ids,2)))
    right_type = "uint" + str(right_width) + "_t"
    # Set driver of input as ENUM
    # This is really only necessary for constant driving wires
    # which wont have known type without this
    # works fine for non constant wires too though
    driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
    parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
    #print "driving_wire",driving_wire,enum_type
    # If left type is unknown assume it also? Only OK for ENUMS?
    if left_type is None:
      left_type = right_type
      parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
      driving_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
      parser_state.existing_logic.wire_to_c_type[driving_wire] = enum_type
      
  # Same thing as ENUM (wanting bin op port to be int so cast happens)
  # Dont want bin op ports based on char type or enum types
  if left_type == 'char':
    left_type = "uint8_t"
  if right_type == 'char':
    right_type = "uint8_t"  
  
  # Prepare for N arg inst
  input_drivers = [] # Prefer wires
  left_driver_wire = parser_state.existing_logic.wire_driven_by[bin_op_left_input]
  input_drivers.append(left_driver_wire)
  right_driver_wire = parser_state.existing_logic.wire_driven_by[bin_op_right_input]
  input_drivers.append(right_driver_wire)
  input_port_names = []
  input_port_names.append(bin_op_left_input_port_name)
  input_port_names.append(bin_op_right_input_port_name)
  input_driver_types = []
  input_driver_types.append(left_type)
  input_driver_types.append(right_type)
  
    
  # Determine output type based on operator or driving wire type
  # Do bool operations first
  if c_ast_bin_op_str == ">":
    output_c_type = BOOL_C_TYPE
  elif c_ast_bin_op_str == ">=":
    output_c_type = BOOL_C_TYPE
  elif c_ast_bin_op_str == "<":
    output_c_type = BOOL_C_TYPE
  elif c_ast_bin_op_str == "<=":
    output_c_type = BOOL_C_TYPE
  elif c_ast_bin_op_str == "==":
    output_c_type = BOOL_C_TYPE
  elif c_ast_bin_op_str == "!=":
    output_c_type = BOOL_C_TYPE
  else:
    # Not bool operation
    # OUTPUT TYPE MUST BE DERIVED FROM FUNCITONALITY
    '''
    @BAAHHH<<<<<<<<<<<<<<<<<<<<<<<
    # Try to get output type from type of driven wire
    allow_fail = True
    driven_c_type_str = GET_C_TYPE_FROM_WIRE_NAMES(driven_wire_names, parser_state.existing_logic, allow_fail)
    if driven_c_type_str is None:
    '''
    # Which ones to use?
    if (left_type is None) and (right_type is None):
      print(func_inst_name, "doesn't have type information for either inputs OR OUTPUT? What's going on?")
      print("parser_state.existing_logic.wire_to_c_type")
      print("bin_op_left_input",bin_op_left_input)
      print("bin_op_right_input",bin_op_right_input)
      print("driven_wire_names",driven_wire_names)
      print("Know types:")
      print(parser_state.existing_logic.wire_to_c_type)
      sys.exit(-1)
    elif not(left_type is None) and (right_type is None):
      # Left type alone known
      print(func_inst_name, "Binary op with only left input type known?")
      sys.exit(-1)
      #parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = left_type
      #parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = left_type
    elif (left_type is None) and not(right_type is None):
      # Right type alone known
      print(func_inst_name, "Binary op with only right input type known?")
      sys.exit(-1)
      #parser_state.existing_logic.wire_to_c_type[bin_op_left_input] = right_type
      #parser_state.existing_logic.wire_to_c_type[bin_op_right_input] = right_type
    else:
      # Types for both left and right are known
      # Derive output
      # Floats yield floats
      if left_type == "float" or right_type == "float":
        output_c_type = "float"
      else:
        # Ints only
        if VHDL.C_TYPES_ARE_INTEGERS([left_type,right_type]):
          # Signed?
          signed = False
          # Left 
          left_unsigned_width = None
          if VHDL.C_TYPE_IS_INT_N(left_type):
            left_unsigned_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_type) - 1
            signed = True
          else:
            left_unsigned_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(left_type)
          # Right
          right_unsigned_width = None
          if VHDL. C_TYPE_IS_INT_N(right_type):
            right_unsigned_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_type) - 1
            signed = True
          else:
            right_unsigned_width = VHDL.GET_WIDTH_FROM_C_N_BITS_INT_TYPE_STR(right_type)
          # Max?
          max_unsigned_width = max(left_unsigned_width, right_unsigned_width) 
        else:
          print("Cannot do binary operation between two different types (explicit cast required for now):", left_type,right_type,c_ast_binary_op.coord)
          sys.exit(-1)
      
        # Operator determines output type
        # ADD
        if c_ast_bin_op_str == "+":
          # Result width is roughly max width + 1
          # Ex. int32 + uint32 , result need to hold uint33 and int33, thus int34 it is
          output_unsigned_width = max_unsigned_width + 1
          output_width = output_unsigned_width
          if signed:
            output_width = output_unsigned_width + 1
          output_c_type = "int"+str(output_width) + "_t"
          if not signed:
            output_c_type = "u" + output_c_type     
        # SUB
        elif c_ast_bin_op_str == "-":
          # uint - uint
          if VHDL.C_TYPE_IS_UINT_N(left_type) and VHDL.C_TYPE_IS_UINT_N(right_type):
            # Width doesnt increase - is equal to LHS size
            output_c_type = "uint"+str(left_unsigned_width) + "_t"
          # int - uint
          elif VHDL.C_TYPE_IS_INT_N(left_type) and VHDL.C_TYPE_IS_UINT_N(right_type):
            # Width doesnt increase - is equal to LHS signed size
            output_c_type = "int"+str(left_unsigned_width+1) + "_t"
          # uint - int
          # int - int
          else:
            # RHS is signed
            # Subtracting an int is like adding a uint
            # So width can increase
            # Do like + operation
            output_unsigned_width = max_unsigned_width + 1
            output_width = output_unsigned_width
            if signed:
              output_width = output_unsigned_width + 1
            output_c_type = "int"+str(output_width) + "_t"
            if not signed:
              output_c_type = "u" + output_c_type
        # MULT
        elif c_ast_bin_op_str == "*":
          # Similar to + but bit growth is more
          # Ex. int32 * uint32 , result need to hold int3 and int33, thus int34 it is
          output_unsigned_width = left_unsigned_width + right_unsigned_width
          output_width = output_unsigned_width
          if signed:
            output_width = output_unsigned_width + 1
          output_c_type = "int"+str(output_width) + "_t"
          if not signed:
            output_c_type = "u" + output_c_type     
        # DIV
        elif c_ast_bin_op_str == "/":
          # Signed or not, output width does not increase
          # Is based on LHS type
          output_unsigned_width = left_unsigned_width
          output_width = output_unsigned_width
          if signed:
            output_width = output_unsigned_width + 1
          output_c_type = "int"+str(output_width) + "_t"
          if not signed:
            output_c_type = "u" + output_c_type
        # BITWISE OPS
        elif ( 
             (c_ast_bin_op_str == "&") or
             (c_ast_bin_op_str == "|") or
             (c_ast_bin_op_str == "^")
           ):
          # Is sized to max
          output_unsigned_width = max_unsigned_width
          output_width = output_unsigned_width
          if signed:
            output_width = output_unsigned_width + 1
          output_c_type = "int"+str(output_width) + "_t"
          if not signed:
            output_c_type = "u" + output_c_type
        # Shifts
        elif c_ast_bin_op_str == "<<":
          # Shifting left returns type of left operand
          output_c_type = left_type
        elif c_ast_bin_op_str == ">>":
          # Shifting right returns type of left operand
          output_c_type = left_type
        else:
          print("Output C type for '" + c_ast_bin_op_str + "'?")
          sys.exit(-1)
  
  # Set type for output wire
  bin_op_output=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
  parser_state.existing_logic.wire_to_c_type[bin_op_output] = output_c_type
  #print " ----- ", bin_op_output, output_c_type
  func_c_ast_node = c_ast_binary_op
  func_logic = C_AST_N_ARG_FUNC_INST_TO_LOGIC(
    prepend_text,
    func_c_ast_node,
    func_base_name,
    base_name_is_name,
    input_drivers, # Wires or C ast nodes
    input_driver_types, # Might be none if not known
    input_port_names, # Port names on submodule
    driven_wire_names,
    parser_state)
  # Save c ast node of binary op
  
  parser_state.existing_logic = func_logic
  #print "AFTER:"
  #print "parser_state.existing_logic.wire_to_c_type[bin_op_left_input]",parser_state.existing_logic.wire_to_c_type[bin_op_left_input]
  #print "parser_state.existing_logic.wire_to_c_type[bin_op_right_input]",parser_state.existing_logic.wire_to_c_type[bin_op_right_input]
  return func_logic

  
def GET_C_TYPE_FROM_WIRE_NAMES(wire_names, logic, allow_fail=False):
  rv = None
  for wire_name in wire_names:
    if not(wire_name in logic.wire_to_c_type):
      if allow_fail:
        return None
      else:
        print("Cant GET_C_TYPE_FROM_WIRE_NAMES since", wire_name,"not in logic.wire_to_c_type")
        print("logic.wire_to_c_type",logic.wire_to_c_type)
        print(0/0)
        sys.exit(-1)
    c_type_str = logic.wire_to_c_type[wire_name]
    if rv is None:
      rv = c_type_str
    else:
      if rv != c_type_str:
        print("GET_C_TYPE_FROM_WIRE_NAMES multilpe types?")
        print("wire_name",wire_name)
        print(rv, c_type_str)
        print(0/0)
        sys.exit(-1)
      
  return rv

# Return None if wire is not driven by const (or anything)
def FIND_CONST_DRIVING_WIRE(wire, logic):
  if WIRE_IS_CONSTANT(wire):
    return wire
  else:
    if wire in logic.wire_driven_by:
      driving_wire = logic.wire_driven_by[wire]
      return FIND_CONST_DRIVING_WIRE(driving_wire, logic)
    else:
      return None   

#def SIMPLE_CONNECT_TO_LOGIC(driving_wire, driven_wire_names, c_ast_node, prepend_text, parser_state):
def APPLY_CONNECT_WIRES_LOGIC(parser_state, driving_wire, driven_wire_names, prepend_text, c_ast_node, check_types_do_cast=True): #print "driving_wire",driving_wire,"=>",driven_wire_names
  # Add wire
  parser_state.existing_logic.wires.add(driving_wire) 
  for driven_wire_name in driven_wire_names:
    parser_state.existing_logic.wires.add(driven_wire_name)
  
  
  if check_types_do_cast:
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~  
    # Look up that type and make sure if the driven wire names have types that they match
    # INSERT CAST FUNCTION if needed
    #print c_ast_id.coord
    if not(driving_wire in parser_state.existing_logic.wire_to_c_type):
      print("Looks like wire'",driving_wire,"'isn't declared? Doing weird stuff with types/enums maybe?")
      print(c_ast_node.coord)
      #print(0/0)
      sys.exit(-1)
    rhs_type = parser_state.existing_logic.wire_to_c_type[driving_wire]
    for driven_wire_name in driven_wire_names:
      # TODO implement look ahead for built in operators. Yairms - Real Time
      # Assume driven wire is same type as rhs -SHOULDNT NEED THIS FOR ANYTHING OTHER THAN BUILT IN OPERATION BUT NOT CHECK THAT NOW SINCE LIKE WHY WHAT IS LIFE ALL ABOUT?
      if driven_wire_name not in parser_state.existing_logic.wire_to_c_type:
        #print "Need to know type of wire",driven_wire_name," before connecting to it?"
        #print 0/0
        #sys.exit(-1)
        parser_state.existing_logic.wire_to_c_type[driven_wire_name] = rhs_type

      # CHECK TYPE, APPLY CASTY IF NEEDED
      driven_wire_type = parser_state.existing_logic.wire_to_c_type[driven_wire_name]
      if driven_wire_type != rhs_type:
        #######
        # Some C casts are handled in VHDL with resize or enum conversions
        # 
        # Integer promotion / slash supported truncation in C lets this be OK
        # Chars are essentially uint8_t
        if ( ( VHDL.WIRES_ARE_INT_N([driven_wire_name],parser_state.existing_logic) or VHDL.WIRES_ARE_UINT_N([driven_wire_name],parser_state.existing_logic))
          and 
           ( VHDL.C_TYPE_IS_INT_N(rhs_type) or VHDL.C_TYPE_IS_UINT_N(rhs_type) )   ):
             continue
        # Enum driving UINT is fine
        elif VHDL.WIRES_ARE_UINT_N([driven_wire_name],parser_state.existing_logic) and WIRE_IS_ENUM(driving_wire, parser_state.existing_logic, parser_state):
          continue
        # I'm dumb and C doesnt return arrays - I think this is only needed for internal code
        elif (
               ( SW_LIB.C_TYPE_IS_ARRAY_STRUCT(driven_wire_type,parser_state) and (SW_LIB.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(driven_wire_type,parser_state)==rhs_type) )
              or
               ( SW_LIB.C_TYPE_IS_ARRAY_STRUCT(rhs_type, parser_state) and (driven_wire_type==SW_LIB.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(rhs_type, parser_state)) )
             ):
          continue
        
        
        #######
        # At this point we have incompatible types that need special casting parser_state.existing_logic
        #     Build cast function to connect driving wire to driven wire
        # int = float
        # float = int
        # float = uint
        # DONT do uint = float since force int cast for now
        if  ( (VHDL.C_TYPE_IS_INT_N(rhs_type) and driven_wire_type == "float") or
            (rhs_type == "float" and VHDL.C_TYPE_IS_INT_N(driven_wire_type)) or
            (VHDL.C_TYPE_IS_UINT_N(rhs_type) and driven_wire_type == "float")
          ):
          # Return n arg func
          func_base_name = CAST_FUNC_NAME_PREFIX
          base_name_is_name = False # append types in name too
          input_drivers = [driving_wire]
          input_driver_types = [rhs_type]
          input_port_names = ["rhs"]
          output_driven_wire_names = driven_wire_names
          # Build instance name
          func_inst_name = BUILD_INST_NAME(prepend_text, func_base_name, c_ast_node)
          # Record output port type
          output_wire_name=func_inst_name+SUBMODULE_MARKER+RETURN_WIRE_NAME
          parser_state.existing_logic.wire_to_c_type[output_wire_name] = driven_wire_type
          
          return C_AST_N_ARG_FUNC_INST_TO_LOGIC(
            prepend_text,
            c_ast_node,
            func_base_name,
            base_name_is_name,
            input_drivers, 
            input_driver_types,
            input_port_names,
            output_driven_wire_names,
            parser_state)

        else:
          # Unhandled
          print("RHS",driving_wire,"drives",driven_wire_name,"with different types?", c_ast_node.coord)
          print(driven_wire_type, "!=", rhs_type)
          print("Implement nasty casty?") #Fat White Family - Tastes Good With The Money
          sys.exit(-1)
    
        
    # ^^^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^
      
  
  #########   Record connnnnections in the parser_state.existing_logic graph ######  
  # Record wire_drives
  all_driven_wire_names = set()
  # Start with existing driven wires
  if driving_wire in parser_state.existing_logic.wire_drives:
    all_driven_wire_names = parser_state.existing_logic.wire_drives[driving_wire]
  # Append the new wires
  for driven_wire_name in driven_wire_names:
      all_driven_wire_names.add(driven_wire_name)
  # Save
  if len(all_driven_wire_names) > 0:
    parser_state.existing_logic.wire_drives[driving_wire] = all_driven_wire_names
  # Record wire_driven_by
  for driven_wire_name in driven_wire_names:
    parser_state.existing_logic.wire_driven_by[driven_wire_name] = driving_wire   
  #print "parser_state.existing_logic.wire_drives", parser_state.existing_logic.wire_drives 
  #print "parser_state.existing_logic.wire_driven_by", parser_state.existing_logic.wire_driven_by 
    
  return parser_state.existing_logic
  
# int x[2]     returns "x", "int", 2
# int x[2][2]  returns "x", "int[2]", 2
def C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(array_decl, parser_state):
  #casthelp(array_decl)
  #print 
  #sys.exit(-1)
  
  # Will be N nested ArrayDecls with dimensions folowed by the element type
  children = array_decl.children()
  dims = []
  while len(children)>1 and children[1][0]=='dim':
    # Get the dimension with dummies
    dummy_parser_state = parser_state.DEEPCOPY() #ParserState() # too slow?
    dummy_parser_state.existing_logic = Logic()
    dummy_parser_state.existing_logic.func_name = "ARRAY_DECL"
    dummy_wire = "ARRAY_DECL_DIM"
    dummy_parser_state.existing_logic = C_AST_NODE_TO_LOGIC(children[1][1], [dummy_wire], "", dummy_parser_state)
    driving_wire = dummy_parser_state.existing_logic.wire_driven_by[dummy_wire]
    dim = int(GET_VAL_STR_FROM_CONST_WIRE(driving_wire,dummy_parser_state.existing_logic,dummy_parser_state))
    #dim = int(children[1][1].value)
    dims.append(dim)
    array_decl = children[0][1]
    children = array_decl.children()
    
  # Reverse order from parsing
  #dims = dims[::-1]
  
  # Get base type
  # Array decl is now holding the inner type
  type_decl = array_decl
  type_name = type_decl.type.names[0]
  #casthelp(type_decl)
  #print "type_decl^"
  
   
  
  # Append everything but last dim
  elem_type = type_name
  for dim_i in range(0, len(dims)-1):
    elem_type = elem_type + "[" + str(dims[dim_i]) + "]"
  
  dim = dims[len(dims)-1]
  #print elem_type
  #print dim
  #sys.exit(-1)
  return type_decl.declname, elem_type,dim
  
  
  
def C_AST_PARAM_DECL_OR_GLOBAL_DEF_TO_C_TYPE(param_decl, parser_state):
  # Need to get array type differently 
  #print "param decl or global?",param_decl
  if type(param_decl.type) == c_ast.ArrayDecl:
    name, elem_type, dim = C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(param_decl.type, parser_state)
    array_type = elem_type + "[" + str(dim) + "]"
    #print "array_type",array_type
    return array_type     
  else:
    # Non array decl
    #print "Non array decl", param_decl
    return param_decl.type.type.names[0]
  
_C_AST_FUNC_DEF_TO_LOGIC_cache = dict()
def C_AST_FUNC_DEF_TO_LOGIC(c_ast_funcdef, parser_state, parse_body = True):
  # Reset state for this func def
  parser_state.existing_logic = None

  # Since no existing logic, can cache entire existing logic here
  try:
    parser_state.existing_logic = _C_AST_FUNC_DEF_TO_LOGIC_cache[c_ast_funcdef.decl.name]
    return parser_state.existing_logic
  except:
    pass
    
  #print "FUNC_DEF",c_ast_funcdef.decl.name
  
  parser_state.existing_logic = Logic()
  # Save the c_ast node
  parser_state.existing_logic.c_ast_node = c_ast_funcdef
  
  # All func def logic has an output wire called "return"
  return_type = c_ast_funcdef.decl.type.type.type.names[0]
  if return_type != "void":
    return_wire_name = RETURN_WIRE_NAME
    parser_state.existing_logic.outputs.append(return_wire_name)
    parser_state.existing_logic.wires.add(return_wire_name)
    parser_state.existing_logic.wire_to_c_type[return_wire_name] = return_type

  # First get name of function from the declaration
  parser_state.existing_logic.func_name = c_ast_funcdef.decl.name
  
  # Then get input wire names from the function def
  #print "func def:",c_ast_funcdef
  if c_ast_funcdef.decl.type.args is not None:
    for param_decl in c_ast_funcdef.decl.type.args.params:
      input_wire_name = param_decl.name
      parser_state.existing_logic.inputs.append(input_wire_name)
      parser_state.existing_logic.wires.add(input_wire_name)
      parser_state.existing_logic.variable_names.add(input_wire_name)
      #print "Append input", input_wire_name
      c_type = C_AST_PARAM_DECL_OR_GLOBAL_DEF_TO_C_TYPE(param_decl, parser_state)
      parser_state.existing_logic.wire_to_c_type[input_wire_name] = c_type
  
  
  # Merge with logic from the body of the func def
  driven_wire_names=[]
  prepend_text=""
  if parse_body:
    body_logic = C_AST_NODE_TO_LOGIC(c_ast_funcdef.body, driven_wire_names, prepend_text, parser_state)   
    parser_state.existing_logic.MERGE_COMB_LOGIC(body_logic)
    
  # Connect globals at end of func logic
  parser_state.existing_logic = CONNECT_FINAL_STATE_WIRES(prepend_text, parser_state, c_ast_funcdef)
  
  # Sanity check for return wire
  if parse_body:
    if not parser_state.existing_logic.is_vhdl_text_module:
      if len(parser_state.existing_logic.submodule_instances) > 0:
        for out_wire in parser_state.existing_logic.outputs:
          if out_wire not in parser_state.existing_logic.wire_driven_by:
            print("Not all function outputs driven!?", parser_state.existing_logic.func_name, out_wire)
            print("(undeclared return value type is assumed 'int', declare as void instead)")
            sys.exit(-1)
            
            
  # Check for mixing volatile and not
  has_volatile = False
  for state_reg in parser_state.existing_logic.state_regs:
    if parser_state.existing_logic.state_regs[state_reg].is_volatile:
      has_volatile = True
      break
  for state_reg in parser_state.existing_logic.state_regs:
    if parser_state.existing_logic.state_regs[state_reg].is_volatile != has_volatile:
      print("Globals for func",parser_state.existing_logic.func_name, "do not match volatile usage for all globals!")
      sys.exit(-1)
  
  # Write cache
  _C_AST_FUNC_DEF_TO_LOGIC_cache[c_ast_funcdef.decl.name] = parser_state.existing_logic
  
  return parser_state.existing_logic


def GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE(logic, submodule_inst, input_port_name):
  #print "logic.func_name", logic.func_name
  name = submodule_inst+ SUBMODULE_MARKER + input_port_name
  #print " logic.wire_driven_by"
  #print logic.wire_driven_by
  driving_wire = logic.wire_driven_by[name]
  return driving_wire
  
def PRINT_DRIVER_WIRE_TRACE(start, logic, wires_driven_so_far=None):
  text = ""
  while not(start is None):
    if wires_driven_so_far is None:
      text += start + " <= "
    else:
      text += start + "(driven? " +  str(start in wires_driven_so_far) + ") <= "
      
    if start in logic.wire_driven_by:
      start = logic.wire_driven_by[start]
    else:
      text += "has no driver!!!!?"
      start = None
  print(text)
  return start
  
def TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(func_logic, parser_state):
  parser_state.existing_logic = func_logic
  # Some code creates logic that will optimize away
  # But actually the amount of generated VHDL can be too much
  # So manually prune logic
  # Look for wires that do not drive anything
  #   Note: submodule input ports are 
  #   the only wires that can stay and not drive anything to module
  #   Inputs for some faked funcs with no func body need to be saved too
  #   Original variable wires dont drive things because alias will drive instead; int x; x=1;
  for wire in set(func_logic.wires): # Copy for iter 
    debug = False
    if wire in func_logic.wires: # Changes during iter
      drives_nothing = (wire not in func_logic.wire_drives)
      must_drive_something = not func_logic.WIRE_ALLOW_NO_DRIVES(wire, parser_state.FuncLogicLookupTable)
      if drives_nothing and must_drive_something:
        if debug:
          print(func_logic.func_name, "Removing", wire)
        func_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(wire, parser_state.FuncLogicLookupTable)
      else:
        if debug:
          print("drives_nothing", drives_nothing)
          if not drives_nothing:
            print("Drives:",func_logic.wire_drives[wire])
          print("must_drive_something",must_drive_something)
    else:
      if debug:
        print(func_logic.func_name, "NOT Removing", wire)
        print("drives_nothing",drives_nothing)
        if not drives_nothing:
          #print(func_logic.wire_drives[wire])
          print("must_drive_something",must_drive_something)
      
      
  # Songs: Ohia - Farewell Transmission
  # Not all wires are necessary
  # In fact, any wire that is not a sub/module port is probably extra?
  # Use 'WIRE_DO_NOT_COLLAPSE' to collapse connections down to submodule port connections
  making_changes = True
  while making_changes:
    making_changes = False
    for wire in set(func_logic.wires): # Copy for iter
      if wire in func_logic.wires: # Changes during iter
        # Look for not special wires that have driving info
        if not func_logic.WIRE_DO_NOT_COLLAPSE(wire) and (wire in func_logic.wire_driven_by) and (wire in func_logic.wire_drives):
          # Get driving info
          driving_wire = func_logic.wire_driven_by[wire]        
          driven_wires = func_logic.wire_drives[wire]
          # Replacing wire with driving_wire, must have same type dummy
          types_match = True
          driving_wire_c_type = func_logic.wire_to_c_type[driving_wire]
          wire_c_type = func_logic.wire_to_c_type[wire]
          if driving_wire_c_type != wire_c_type:
            types_match = False
          for driven_wire in driven_wires:
            driven_wire_c_type = func_logic.wire_to_c_type[driven_wire]
            if driving_wire_c_type != driven_wire_c_type:
              types_match = False
          if not types_match:
            continue          
          # Do removal
          making_changes = True          
          # Remove record of this wire driving anything so removal doesnt progate forward, only backwards
          func_logic.wire_drives.pop(wire)
          # Make new connection before ripping up old wire
          func_logic = APPLY_CONNECT_WIRES_LOGIC(parser_state, driving_wire, driven_wires, None, None)
          # Totally remove old wire
          func_logic.REMOVE_WIRES_AND_SUBMODULES_RECURSIVE(wire, parser_state.FuncLogicLookupTable)
          #break # Needed?  Wanted?
        
        
  # Do for each submodule too
  for submodule_inst in func_logic.submodule_instances:
    submodule_func_name = func_logic.submodule_instances[submodule_inst]
    # Skip vhdl
    if submodule_func_name == VHDL_FUNC_NAME:
      continue
    # Skip clock crossings too
    submodule_logic = parser_state.FuncLogicLookupTable[submodule_func_name]
    if SW_LIB.IS_CLOCK_CROSSING(submodule_logic):
      continue   
    
    parser_state = TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(submodule_logic, parser_state)
    
  return parser_state
  

def DEL_ALL_CACHES():
  # Clear all caches after parsing is done
  global _other_partial_logic_cache
  global _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache
  global _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache
  global _REDUCE_REF_TOKS_OR_STRS_cache
  global _TRIM_VAR_REF_TOKS_cache
  global _REF_TOKS_COVERED_BY_cache
  global _REMOVE_COVERED_REF_TOK_BRANCHES_cache
  global _C_AST_REF_TOKS_TO_C_TYPE_cache
  global _C_AST_NODE_COORD_STR_cache
  global _C_AST_FUNC_DEF_TO_LOGIC_cache
  global _GET_ZERO_CLK_PIPELINE_MAP_cache
  
  _other_partial_logic_cache                = dict()
  _REF_TOKS_TO_OWN_BRANCH_REF_TOKS_cache    = dict()
  _REF_TOKS_TO_ENTIRE_TREE_REF_TOKS_cache   = dict()
  _REDUCE_REF_TOKS_OR_STRS_cache            = dict()
  _TRIM_VAR_REF_TOKS_cache                  = dict()
  _REF_TOKS_COVERED_BY_cache                = dict()
  _REMOVE_COVERED_REF_TOK_BRANCHES_cache    = dict()
  _C_AST_REF_TOKS_TO_C_TYPE_cache           = dict()
  _C_AST_NODE_COORD_STR_cache               = dict()
  _C_AST_FUNC_DEF_TO_LOGIC_cache            = dict()
  _GET_ZERO_CLK_PIPELINE_MAP_cache          = dict()

  
# This class hold all the state obtained by parsing a single C file
class ParserState:
  def __init__(self):
    # Parsed from pre-prepreprocessed text
    
    # From parsed preprocessed text   
    # The file of parsed C code
    self.c_file_ast = None # Single C file tree
    
    # Parsed pre func defintions
    # Build map just of func names and where there are used
    self.func_name_to_calls = dict() # dict[func_name] = set(called_func_names)
    self.func_names_to_called_from = dict() # dict[func_name] = set(calling_func_names)
    self.struct_to_field_type_dict = dict()
    self.enum_to_ids_dict = dict()
    self.global_state_regs = dict() # name->state reg info
    
    # Parsed from function defintions
    self.existing_logic = None # Temp working copy of current func logic, probably should not be here?
    # Function definitons as logic
    self.FuncLogicLookupTable=dict() #dict[func_name]=Logic() <--
    # Elaborated to instances
    self.LogicInstLookupTable=dict() #dict[inst_name]=Logic()  (^ same logic object as above)
    self.FuncToInstances=dict() #dict[func_name]=set([instance, name, usages, of , func)
    
    # Pragma info
    self.main_mhz = dict() # dict[main_func_name]=mhz
    self.func_marked_wires = set()
    self.part = None
    
    # Clock crossing info
    self.clk_cross_var_info = dict() # var name -> clk cross var info

  def DEEPCOPY(self):
    # Fuck me how many times will I get caught with objects getting copied incorrectly?
    rv = ParserState()
    
    rv.FuncLogicLookupTable = dict()
    for fname in self.FuncLogicLookupTable:
      rv.FuncLogicLookupTable[fname] = self.FuncLogicLookupTable[fname].DEEPCOPY()

    rv.LogicInstLookupTable = dict()
    for inst_name in self.LogicInstLookupTable:
      func_name = self.LogicInstLookupTable[inst_name].func_name
      rv_func_logic = rv.FuncLogicLookupTable[func_name]
      rv.LogicInstLookupTable[inst_name] = rv_func_logic
    
    rv.FuncToInstances=copy.deepcopy(self.FuncToInstances)
    
    rv.existing_logic = None
    if self.existing_logic is not None:
      rv.existing_logic = self.existing_logic.DEEPCOPY()
    
    rv.struct_to_field_type_dict = dict(self.struct_to_field_type_dict)
    rv.enum_to_ids_dict = dict(self.enum_to_ids_dict)
    rv.global_state_regs = dict(self.global_state_regs)
    
    rv.func_name_to_calls = dict(self.func_name_to_calls)
    rv.func_names_to_called_from = dict(self.func_name_to_calls)
    
    rv.main_mhz = dict(self.main_mhz)
    rv.func_marked_wires = set(self.func_marked_wires)
    rv.part = self.part
    
    self.clk_cross_var_info = dict(self.clk_cross_var_info)
    
    return rv
    

def GET_PARSER_STATE_CACHE_FILEPATH(c_filename):
  key = c_filename 
  output_directory = SYN.SYN_OUTPUT_DIRECTORY
  filepath = output_directory + "/" + key + ".parsed"
  return filepath

def WRITE_PARSER_STATE_CACHE(parser_state, c_filename):
  # Write dir first if needed
  output_directory = SYN.SYN_OUTPUT_DIRECTORY
  if not os.path.exists(output_directory):
    os.makedirs(output_directory)
    
  # Write file
  filepath = GET_PARSER_STATE_CACHE_FILEPATH(c_filename)
  if not os.path.exists(os.path.dirname(filepath)):
    os.makedirs(os.path.dirname(filepath)) 
  with open(filepath, 'wb') as output:
    pickle.dump(parser_state, output, pickle.HIGHEST_PROTOCOL)

def GET_PARSER_STATE_CACHE(c_filename):
  filepath = GET_PARSER_STATE_CACHE_FILEPATH(c_filename)
  if os.path.exists(filepath):
    with open(filepath, 'rb') as input:
      parser_state = pickle.load(input)
      return parser_state
  return None
  
# dict[func_name] = set(called_func_names)
# dict[func_name] = set(calling_func_names)
# func_name_to_calls, func_names_to_called_from = 
def GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state):
  func_name_to_calls = dict()
  func_names_to_called_from = dict()
  # Do this by manually recursing through all nodes in each func def
  c_ast_func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
  for c_ast_func_def in c_ast_func_defs:
    func_name = c_ast_func_def.decl.name
    #print "c_ast_func_def",c_ast_func_def.decl.name
    func_call_c_ast_nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_func_def, c_ast.FuncCall, parser_state)
    #print "Called",len(func_call_c_ast_nodes)
    for func_call_c_ast_node in func_call_c_ast_nodes:
      called_func_name = func_call_c_ast_node.name.name
      #print " called_func_name",called_func_name
      # Record
      # Calls
      if func_name not in func_name_to_calls:
        func_name_to_calls[func_name] = set()
      func_name_to_calls[func_name].add(called_func_name)
      # Called from
      if called_func_name not in func_names_to_called_from:
        func_names_to_called_from[called_func_name] = set()
      func_names_to_called_from[called_func_name].add(func_name)
    #if func_name in func_name_to_calls:
    #  print "func_name",func_name,func_name_to_calls[func_name]
    #  print "SCOO"
  
  #print("func_name_to_calls",func_name_to_calls)
  
  # Reduce data down to funcs as used by main funcs (trying to avoid regular C code)
  main_func_name_to_calls = dict()
  main_func_names_to_called_from = dict()
  submodule_func_names = set(parser_state.main_mhz.keys())
  while len(submodule_func_names) > 0:
    next_submodule_func_names = set()
    
    # Every func in level
    for func_name in submodule_func_names:
      if func_name in func_name_to_calls:
        called_func_names = func_name_to_calls[func_name]
        
        # Calls
        if func_name not in main_func_name_to_calls:
          main_func_name_to_calls[func_name] = set()
        main_func_name_to_calls[func_name].update(called_func_names)
        # Called from
        for called_func_name in called_func_names:
          if called_func_name not in main_func_names_to_called_from:
            main_func_names_to_called_from[called_func_name] = set()
          main_func_names_to_called_from[called_func_name].add(func_name)
          
        next_submodule_func_names.update(called_func_names)
    
    
    # Next level of 'recursion' into submodules
    submodule_func_names = set(next_submodule_func_names)
    
  #print("main_func_name_to_calls",main_func_name_to_calls)
  #print("main_func_names_to_called_from",main_func_names_to_called_from)
  return main_func_name_to_calls, main_func_names_to_called_from


def C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast_type, parser_state, nodes=None):
  if nodes is None:
    nodes = []
  if type(c_ast_node) == c_ast_type:
    nodes.append(c_ast_node)
  children_tuples = c_ast_node.children()
  for children_tuple in children_tuples:
    child_node = children_tuple[1]
    nodes = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(child_node, c_ast_type, parser_state, nodes)
  return nodes

def RECURSIVE_FIND_MAIN_FUNC(func_name, func_name_to_calls, func_names_to_called_from, main_funcs):
  # Is it main?
  if func_name in main_funcs:
    return func_name
  # Where called from?
  if func_name in func_names_to_called_from:
    called_from_funcs = func_names_to_called_from[func_name]
    # Should only be called once?
    if len(called_from_funcs) == 1:
      called_from_func = list(called_from_funcs)[0]
      return RECURSIVE_FIND_MAIN_FUNC(called_from_func, func_name_to_calls, func_names_to_called_from, main_funcs)
    else:
      print("Expected single main func for func, but is called from?",func_name,called_from_func)
      sys.exit(-1)
      
  return None


# Returns ParserState
# TODO make as ParserState then 
def PARSE_FILE(c_filename):
  # Do we have a cached parser state?
  cached_parser_state = GET_PARSER_STATE_CACHE(c_filename)
  if cached_parser_state is not None:
    print("Already parsed C code for",c_filename,", using cache...")
    return cached_parser_state
  
  # Otherwise do for real
  
  # Catch pycparser exceptions
  try:
    
    def parse_pass(parser_state, gen_empty=False, post_preprocess_gen=False, c_ast_nonfuncdefs=False, post_preprocess_wnonfuncdefs=False, old_autogen_funclookup=False):
      if gen_empty:
        # Use cpp --MM --MG to parse the #include tree and get all files
        # that need to be code gen'd again
        all_code_files = GET_INCLUDED_FILES(c_filename)
        
        # Code generate empty to-be-generated header files 
        # so initial preprocessing can happen
        # Then do repeated re-parsing as code gen continues
        SW_LIB.GEN_EMPTY_GENERATED_HEADERS(all_code_files)
      
      if post_preprocess_gen:
        # Preprocess the main file to get single block of text
        preprocessed_c_text = preprocess_file(c_filename)
        #print(preprocessed_c_text)
        # Code gen based purely on preprocessed C text
        SW_LIB.WRITE_POST_PREPROCESS_GEN_CODE(preprocessed_c_text)
        
      if c_ast_nonfuncdefs:
        # Preprocess the main file to get single block of text
        preprocessed_c_text = preprocess_file(c_filename)
        
        # Get the C AST
        parser_state.c_file_ast = GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(preprocessed_c_text, c_filename)
        # Parse pragmas
        parse_state = APPEND_PRAGMA_INFO(parser_state)
        # Parse definitions first before code structure
        print("Parsing non-function definitions...", flush=True)
        # Get the parsed enum info
        parser_state.enum_to_ids_dict = GET_ENUM_IDS_DICT(parser_state.c_file_ast)
        # Get the parsed struct def info
        parser_state = APPEND_STRUCT_FIELD_TYPE_DICT(parser_state.c_file_ast, parser_state)
        # Get global state regs (global regs, volatile globals) info
        parser_state = GET_GLOBAL_STATE_REG_INFO(parser_state)
        # Build primative map of function use
        parser_state.func_name_to_calls, parser_state.func_names_to_called_from = GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state)
        # Elborate what the clock crossings look like
        parser_state = GET_CLK_CROSSING_INFO(preprocessed_c_text, parser_state)
      
      
      if post_preprocess_wnonfuncdefs:
        # Preprocess the main file to get single block of text
        preprocessed_c_text = preprocess_file(c_filename)
        
        # Do code gen based on preprocessed C text and non-function definitions
        # This is the newer better way
        SW_LIB.WRITE_POST_PREPROCESS_WITH_NONFUNCDEFS_GEN_CODE(preprocessed_c_text, parser_state)
        
      
      if old_autogen_funclookup:
        # Preprocess the file again to pull in generated code
        preprocessed_c_text = preprocess_file(c_filename)
        #print "preprocessed_c_text",preprocessed_c_text
        # Get the C AST again to reflect new generated code
        parser_state.c_file_ast = GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(preprocessed_c_text, c_filename)
        # Update primative map of function use
        parser_state.func_name_to_calls, parser_state.func_names_to_called_from = GET_FUNC_NAME_TO_FROM_FUNC_CALLS_LOOKUPS(parser_state)
        # This is the old more hacky way
        # Get SW existing logic for this c file
        parser_state.FuncLogicLookupTable = SW_LIB.GET_AUTO_GENERATED_FUNC_NAME_LOGIC_LOOKUP_FROM_PREPROCESSED_TEXT(preprocessed_c_text, parser_state)
    
    
    
    # Begin parsing/generating code
    parser_state = ParserState()
    # Need to do multiple passes 
    parse_pass(parser_state, gen_empty=True, post_preprocess_gen=True, c_ast_nonfuncdefs=True, post_preprocess_wnonfuncdefs=True)
    parse_pass(parser_state,                 post_preprocess_gen=True, c_ast_nonfuncdefs=True, post_preprocess_wnonfuncdefs=True, old_autogen_funclookup=True)
    #parse_pass(parser_state,                 post_preprocess_gen=True, c_ast_nonfuncdefs=True, post_preprocess_wnonfuncdefs=True, old_autogen_funclookup=True) 
    #parse_pass(parser_state, post_preprocess_wnonfuncdefs=True)
    #print "Temp stop"
    #sys.exit(-1)
    
    
    
    # Parse the function definitions for code structure
    print("Parsing function logic...", flush=True)
    parser_state.FuncLogicLookupTable = GET_FUNC_NAME_LOGIC_LOOKUP_TABLE(parser_state)
    # Sanity check main funcs are there
    for main_func in list(parser_state.main_mhz.keys()):
      if main_func not in parser_state.FuncLogicLookupTable:
        print("Main function:", main_func, "does not exist?")
        sys.exit(-1)   
    
    #print "WHHY SLO?"
    #sys.exit(-1)
    
    # Code gen based on pre elborated logic
    # TODO SW_LIB.WRITE_PRE_ELAB_GEN_CODE(preprocessed_c_text, parser_state)
    # Preprocess the text again to pull in generated code
    # preprocessed_c_text = preprocess_text(text)
    # Get the C AST again to reflect new generated code
    # parser_state.c_file_ast = GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(preprocessed_c_text, c_filename)
    
    # Need to add array struct for old internal C code parsing?
    parser_state = APPEND_ARRAY_STRUCT_INFO(parser_state)
    
    # Elaborate the logic down to raw vhdl modules
    print("Elaborating pipeline hierarchies down to raw HDL logic...", flush=True)
    for main_func in list(parser_state.main_mhz.keys()):
      adjusted_containing_logic_inst_name=""
      main_func_logic = parser_state.FuncLogicLookupTable[main_func]
      c_ast_node_when_used = parser_state.FuncLogicLookupTable[main_func].c_ast_node
      parser_state = RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(main_func, main_func, parser_state, adjusted_containing_logic_inst_name, c_ast_node_when_used)
      
    #from guppy import hpy
    #h = hpy()
    #print h.heap()
    #print "TEMP STOP"
    #sys.exit(-1)
    
    # Code gen based on fully elaborated logic
    # Write c code
    print("Writing generated PipelineC code from elaboration to output directories...", flush=True)
    for func_name in parser_state.FuncLogicLookupTable:
      func_logic = parser_state.FuncLogicLookupTable[func_name]
      if not(func_logic.c_code_text is None):
        # Fake name
        fake_filename = func_name + ".c"
        out_dir = SYN.GET_OUTPUT_DIRECTORY(func_logic)
        outpath = out_dir + "/" + fake_filename
        if not os.path.exists(out_dir):
          os.makedirs(out_dir)
        f=open(outpath,"w")
        f.write(func_logic.c_code_text)
        f.close() 
    
    #print "Skipping user code trimming for debug..."
    # Remove excess user code
    if TRIM_COLLAPSE_LOGIC:
      print("Doing obvious logic trimming/collapsing...")
      for main_func in list(parser_state.main_mhz.keys()):
        main_func_logic = parser_state.FuncLogicLookupTable[main_func]
        parser_state = TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE(main_func_logic, parser_state)
        
    # Check for double use of globals+volatiles the dumb way to print useful info
    for func_name1 in parser_state.FuncLogicLookupTable:
      func1_logic = parser_state.FuncLogicLookupTable[func_name1]
      for func_name2 in parser_state.FuncLogicLookupTable:
        if func_name2 == func_name1:
          continue
        func2_logic = parser_state.FuncLogicLookupTable[func_name2]
        for func1_state_reg in func1_logic.state_regs:
          if func1_state_reg in func2_logic.state_regs and func1_state_reg in parser_state.global_state_regs:
            print("Heyo can't use global state regs in more than one function!")
            print(func1_state_reg, "used in", func_name1, "and", func_name2)
            sys.exit(-1)
            
    # Write cache
    print("Writing cache of parsed information to file...")
    WRITE_PARSER_STATE_CACHE(parser_state, c_filename)
    
    # Clear in memory caches
    DEL_ALL_CACHES()
    
    return parser_state

  except c_parser.ParseError as pe:
    print("PARSE_FILE pycparser says you messed up here:",pe)
    sys.exit(-1)
    
# Global list of these in parser_state + lists per function in logic for locally delclared
class StateRegInfo:
  def __init__(self):
    self.name = None
    self.type_name = None
    self.init = None # c ast node
    self.is_volatile = False
    self.is_static = False

def GET_GLOBAL_STATE_REG_INFO(parser_state):
  # Read in file with C parser and get function def nodes
  parser_state.global_state_regs = dict()
  global_decls = GET_C_AST_GLOBAL_DECLS(parser_state.c_file_ast)
  for global_decl in global_decls:
    state_reg_info = StateRegInfo()
    state_reg_info.name = str(global_decl.name)
    c_type = C_AST_PARAM_DECL_OR_GLOBAL_DEF_TO_C_TYPE(global_decl, parser_state)
    state_reg_info.type_name = c_type
    state_reg_info.init = global_decl.init
        
    # Save flags
    if 'volatile' in global_decl.quals:
      state_reg_info.is_volatile = True
        
    # Save info
    parser_state.global_state_regs[state_reg_info.name] = state_reg_info
      
  return parser_state


# Fuck me add struct info for array wrapper
def APPEND_ARRAY_STRUCT_INFO(parser_state):
  # Loop over all C types and find the array structs
  for func_name in parser_state.FuncLogicLookupTable:
    func_logic = parser_state.FuncLogicLookupTable[func_name]
    for wire in func_logic.wire_to_c_type:
      c_type  = func_logic.wire_to_c_type[wire]
      if SW_LIB.C_TYPE_IS_ARRAY_STRUCT(c_type,parser_state):
        c_array_type = SW_LIB.C_ARRAY_STRUCT_TYPE_TO_ARRAY_TYPE(c_type, parser_state)
        elem_t, dims = C_ARRAY_TYPE_TO_ELEM_TYPE_AND_DIMS(c_array_type)
        data_array_type = elem_t
        for dim in dims:
          data_array_type += "[" + str(dim) + "]"
        
        # Append to dict
        field_type_dict = dict()
        field_type_dict["data"] = data_array_type 
        parser_state.struct_to_field_type_dict[c_type] = field_type_dict
        
  return parser_state
  
  
class ClkCrossVarInfo():
  def __init__(self):
    self.write_read_main_funcs = (None,None)
    self.write_read_sizes = (None,None)
    self.write_read_funcs = (None,None)
    self.flow_control = False
        
def GET_CLK_CROSSING_INFO(preprocessed_c_text, parser_state): 
  # Regex search c_text for pair of write and read funcs
  write_func_calls = []
  r="\w+" + "_WRITE" + "\s?\("
  write_func_calls += SW_LIB.FIND_REGEX_MATCHES(r, preprocessed_c_text)
  r="\w+" + "_WRITE_[0-9]+" + "\s?\("
  write_func_calls += SW_LIB.FIND_REGEX_MATCHES(r, preprocessed_c_text)
  write_func_names = []
  for write_func_call in write_func_calls:
    write_func_names.append(write_func_call.strip("(").strip())
  read_func_calls = []
  r="\w+" + "_READ" + "\s?\("
  read_func_calls += SW_LIB.FIND_REGEX_MATCHES(r, preprocessed_c_text)
  r="\w+" + "_READ_[0-9]+" + "\s?\("
  read_func_calls += SW_LIB.FIND_REGEX_MATCHES(r, preprocessed_c_text)
  read_func_names = []
  for read_func_call in read_func_calls:
    read_func_names.append(read_func_call.strip("(").strip())
  
  # Find pairs that are global or volatile global vars
  var_to_read_func = dict()
  var_to_write_func = dict()
  all_var_names = set()
  for func_name in (write_func_names+read_func_names):
    if "_WRITE" in func_name:
      var_name = CLK_CROSS_FUNC_TO_VAR_NAME(func_name) 
      all_var_names.add(var_name)
      var_to_write_func[var_name] = func_name
    if "_READ" in func_name:
      var_name = CLK_CROSS_FUNC_TO_VAR_NAME(func_name) 
      all_var_names.add(var_name)
      var_to_read_func[var_name] = func_name
  var_names = []
  for var_name in all_var_names:
    if var_name in parser_state.global_state_regs:
      if var_name not in var_to_write_func:
        print("Missing clock cross write function for clock crossing named:",var_name)
        sys.exit(-1)
      # Make up a read func if needed (unconnected output)
      if var_name not in var_to_read_func:
        var_to_read_func[var_name] = var_to_write_func[var_name].replace("_WRITE","_READ")
      var_names.append(var_name)    
  
  # Find and read and write main funcs
  var_to_rw_main_funcs = dict()
  for var_name in var_names:
    read_func_name = None
    if var_name in var_to_read_func:
      read_func_name = var_to_read_func[var_name]
    write_func_name = None
    if var_name in var_to_write_func:
      write_func_name = var_to_write_func[var_name]
    read_containing_func = None
    write_containing_func = None
    # Search for container
    for func_name in parser_state.func_name_to_calls:
      called_funcs = parser_state.func_name_to_calls[func_name]
      #print func_name,"called_funcs",called_funcs
      # Read
      if read_func_name in called_funcs:
        if read_containing_func is not None:
          if read_containing_func != func_name:
            print("Multiple uses of",read_func_name,"?",read_containing_func,func_name)
            sys.exit(-1)
        read_containing_func = func_name
      # Write
      if write_func_name in called_funcs:
        if write_containing_func is not None:
          if write_containing_func != func_name:
            print("Multiple uses of",write_func_name,"?",write_containing_func,func_name)
            sys.exit(-1)
        write_containing_func = func_name
      if write_containing_func is not None and read_containing_func is not None:
        break
        
    # Recursively lookup main_func
    read_main_func = RECURSIVE_FIND_MAIN_FUNC(read_containing_func, parser_state.func_name_to_calls, parser_state.func_names_to_called_from, list(parser_state.main_mhz.keys()))
    write_main_func = RECURSIVE_FIND_MAIN_FUNC(write_containing_func, parser_state.func_name_to_calls, parser_state.func_names_to_called_from, list(parser_state.main_mhz.keys()))
    if write_main_func is None:
      print("Problem finding main functions for",var_name,"clock crossing: write, read:", write_containing_func,",",read_containing_func)
      print("Missing or incorrect #pragma MAIN_MHZ ?")
      sys.exit(-1)
    var_to_rw_main_funcs[var_name] = (read_main_func,write_main_func)
    
    
  # Do infer loop slow thing for now
  inferring = True
  while inferring:
    inferring = False
    for var_name in var_to_rw_main_funcs:
      read_main_func,write_main_func = var_to_rw_main_funcs[var_name]
      if read_main_func is None or write_main_func is None:
        continue
      read_func_name = var_to_read_func[var_name]
      write_func_name = var_to_write_func[var_name]
      read_mhz = None
      if read_main_func in parser_state.main_mhz:
        read_mhz = parser_state.main_mhz[read_main_func]
      write_mhz = None
      if write_main_func in parser_state.main_mhz:
        write_mhz = parser_state.main_mhz[write_main_func]
      # Infer freqs to match if possible
      if read_mhz is None and write_mhz is not None:
        print("Matching clock domain for",read_main_func,"(",read_func_name,")","to clock domain for",write_func_name, "(",write_main_func,"@",write_mhz,"MHz)")
        read_mhz = write_mhz
        parser_state.main_mhz[read_main_func] = read_mhz
        inferring = True
      elif read_mhz is not None and write_mhz is None:
        print("Matching clock domain for",write_main_func,"(",write_func_name,")","to clock domain for",read_func_name, "(", read_main_func,"@",read_mhz,"MHz)")
        write_mhz = read_mhz
        parser_state.main_mhz[write_main_func] = write_mhz
        inferring = True
    
  for var_name in var_names:
    # Get main funcs and mhz
    read_main_func,write_main_func = None,None
    read_mhz,write_mhz = None,None
    if var_name in var_to_rw_main_funcs:
      read_main_func,write_main_func = var_to_rw_main_funcs[var_name]
      if read_main_func is not None:
        read_mhz = parser_state.main_mhz[read_main_func]
      write_mhz = parser_state.main_mhz[write_main_func]
    # Match mhz for disconnected read side
    if write_mhz is not None and read_mhz is None:
      read_mhz = write_mhz
    # Sanity check
    if read_mhz is None and write_mhz is None:
        print("No clock frequencies asssociated with each side of the clock crossing for",var_name,"clock crossing: read, write:", read_main_func,",",write_main_func)
        print("Missing or incorrect #pragma MAIN_MHZ ?")
        sys.exit(-1)
    
    # Async fifo with flow control uses sized READ and WRITE
    flow_control = False
    read_func_name = var_to_read_func[var_name]
    write_func_name = var_to_write_func[var_name]
    if not read_func_name.endswith("_READ") or not write_func_name.endswith("_WRITE"):
      # Async sized read and write
      read_size = int(read_func_name.split("_READ_")[1])
      write_size = int(write_func_name.split("_WRITE_")[1])
      flow_control = True
    else:
      # Sync or async not user sized read and write
      ratio = 0
      write_size = 0
      read_size = 0
      if write_mhz > read_mhz:
        # Write side is faster
        ratio = int(math.ceil(write_mhz/read_mhz))
        write_size = 1
        read_size = ratio
      else:
        # Read side is faster
        ratio = int(math.ceil(read_mhz/write_mhz))
        read_size = 1
        write_size = ratio
        
      # Check that non volatile crosses are identical freq
      if var_name in parser_state.global_state_regs and not parser_state.global_state_regs[var_name].is_volatile:
        if ratio != 1.0:
          print("Non-volatile clock crossing", var_name, "is used like volatile clock crossing from different clocks",write_func_name,"(",write_main_func,")","to",read_func_name,"(",read_main_func,")",write_mhz,"MHz ->", read_mhz, "MHz")
          sys.exit(-1)
          
      # For now check that volatile crossings are integer ratios (assumed synch / same clock src)
      if write_mhz >= read_mhz:
        clk_ratio = write_mhz / read_mhz
      else:
        clk_ratio = read_mhz / write_mhz
      if int(clk_ratio) != clk_ratio:
        print("TODO: Volatile non integer ratio clock crossings like:",write_func_name,write_mhz,"MHz","->",read_func_name,read_mhz,"MHz")
        sys.exit(-1)
      
    
    # Record
    parser_state.clk_cross_var_info[var_name] = ClkCrossVarInfo()
    parser_state.clk_cross_var_info[var_name].flow_control = flow_control
    parser_state.clk_cross_var_info[var_name].write_read_funcs = (write_func_name,read_func_name)
    parser_state.clk_cross_var_info[var_name].write_read_main_funcs = (write_main_func,read_main_func)
    parser_state.clk_cross_var_info[var_name].write_read_sizes = (write_size, read_size)

  '''
  # Loop over all funcs and get instances 
  clk_cross_to_modulest_containing_inst_set = set()
  for func_name in parser_state.FuncLogicLookupTable:
    logic = parser_state.FuncLogicLookupTable[func_name]
    if not SW_LIB.IS_CLOCK_CROSSING(logic):
      continue
    # Should only be one instance:
    insts = parser_state.FuncToInstances[func_name]
    if len(insts) > 1:
      print "More than one clock crossing instance?", func_name, insts
      print "Screwed - Janelle Monae"
      sys.exit(-1)
    inst_name = list(insts)[0]
    # And one containing instance
    if len(logic.containing_funcs) > 1:
      print "More than one continer func for clock crossing instance?", func_name, insts
      sys.exit(-1)
    containing_func_name = list(logic.containing_funcs)[0]
    containing_insts = parser_state.FuncToInstances[containing_func_name]
    if len(containing_insts) > 1:
      print "More than one continer func instance for clock crossing instance?", func_name, insts
      sys.exit(-1)
    containing_inst = list(containing_insts)[0]
    clk_cross_to_modulest_containing_inst_set.add((inst_name,containing_inst))
    '''   

  return parser_state
  
def CLK_CROSS_FUNC_TO_VAR_NAME(func_name):
  if "_READ" in func_name:
    var_name = func_name.split("_READ")[0]
  elif "_WRITE" in func_name: 
    var_name = func_name.split("_WRITE")[0]
    
  return var_name

def GET_ENUM_IDS_DICT(c_file_ast):
  # Read in file with C parser and get function def nodes
  rv = dict()
  enum_defs = GET_C_AST_ENUM_DEFS(c_file_ast)
  for enum_def in enum_defs:
    #casthelp(enum_def)
    #sys.exit(-1)
    enum_name = str(enum_def.name)
    #print "struct_name",struct_name
    rv[enum_name] = []
    #casthelp(enum_def.values)
    #sys.exit(-1)
    for child in enum_def.values.enumerators:
      if len(child.children()) > 0:
        child.show()
        print("Don't assign enums values for now OK?")
        sys.exit(-1)     
      
      #sys.exit(-1)
      id_str = str(child.name)
      #print id_str
      rv[enum_name].append(id_str)
      
      '''
      type_name = str(child.children()[0][1].children()[0][1].names[0])
      rv[struct_name][field_name] = type_name
      
      if struct_def.name is None:
        sys.exit(-1)
      '''
  #print(rv)
  #sys.exit(-1)
  return rv

_printed_GET_STRUCT_FIELD_TYPE_DICT = False
def APPEND_STRUCT_FIELD_TYPE_DICT(c_file_ast, parser_state):
  # Read in file with C parser and get function def nodes
  struct_defs = GET_C_AST_STRUCT_DEFS(c_file_ast)
  for struct_def in struct_defs:
    if struct_def.name is None:
      global _printed_GET_STRUCT_FIELD_TYPE_DICT
      if not _printed_GET_STRUCT_FIELD_TYPE_DICT:
        print("WARNING: Must use tag_name and struct_alias in struct definitions... for now... Ex.")
        print('''typedef struct tag_name {
  type member1;
  type member2;
} struct_alias;''')
        _printed_GET_STRUCT_FIELD_TYPE_DICT = True
      continue
          
    #casthelp(struct_def)
    struct_name = str(struct_def.name)
    #print "struct_name",struct_name
    parser_state.struct_to_field_type_dict[struct_name] = OrderedDict()
    for child in struct_def.decls:
      # Assume type decl  
      field_name = str(child.name)
      if type(child.type) == c_ast.ArrayDecl:
        field_name, base_type, dim = C_AST_ARRAYDECL_TO_NAME_ELEM_TYPE_DIM(child.type, parser_state)
        #dim = int(child.type.dim.value)
        #base_type = child.type.type.type.names[0]
        type_name = base_type + "[" + str(dim) + "]"  
      else:
        # Non array
        type_name = str(child.children()[0][1].children()[0][1].names[0])
      parser_state.struct_to_field_type_dict[struct_name][field_name] = type_name
      
  return parser_state
  

# This will likely be called multiple times when loading multiple C files
def GET_FUNC_NAME_LOGIC_LOOKUP_TABLE(parser_state, parse_body = True):
  existing_func_name_2_logic = parser_state.FuncLogicLookupTable
  
  # Build function name to logic from func defs from files
  FuncLogicLookupTable = dict(existing_func_name_2_logic) # Was deep copy # Needed?
  
  # Each func def needs existing logic func name lookup
  # Read in file with C parser and get function def nodes
  func_defs = GET_C_AST_FUNC_DEFS(parser_state.c_file_ast)
  for func_def in func_defs:
    # Skip functions that are not found in the initial from-main hierarchy mapping
    if ( (func_def.decl.name not in parser_state.func_name_to_calls) and
         (func_def.decl.name not in parser_state.func_names_to_called_from) and 
         (func_def.decl.name not in parser_state.main_mhz) ):
      print("Function skipped:",func_def.decl.name)
      continue
    else:
      print("Parsing function:",func_def.decl.name)
    # Each func def produces a single logic item
    parser_state.existing_logic=None
    driven_wire_names=[]
    prepend_text=""
    logic = C_AST_FUNC_DEF_TO_LOGIC(func_def, parser_state, parse_body)
    # Final chance for SW_LIB generated code to do stuff to func logic
    # Hah wtf this is hacky
    logic = SW_LIB.GEN_CODE_POST_PARSE_LOGIC_ADJUST(logic)
    FuncLogicLookupTable[logic.func_name] = logic 
    parser_state.FuncLogicLookupTable = FuncLogicLookupTable
    
  # Do dumb? loops to find containing func
  for func_logic in list(FuncLogicLookupTable.values()):
    for submodule_inst in func_logic.submodule_instances:
      submodule_func_name = func_logic.submodule_instances[submodule_inst]
      if submodule_func_name in FuncLogicLookupTable:
        FuncLogicLookupTable[submodule_func_name].containing_funcs.add(func_logic.func_name)
              
  return FuncLogicLookupTable
  
      
def RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(func_name, local_inst_name, parser_state, containing_logic_inst_name="", c_ast_node_when_used=None):
  # Use prepend text to contruct full instance names
  new_inst_name_prepend_text = containing_logic_inst_name + SUBMODULE_MARKER
  if func_name in parser_state.main_mhz:
    # Main never gets prepend text
    if containing_logic_inst_name != "":
      print("Woah there, are you calling a top level main funciton from within another funciton!?",func_name,containing_logic_inst_name)
      sys.exit(-1)
    # Override
    new_inst_name_prepend_text = ""
  
  # Is this a function who logic is already known? (Parsed from C code? Or evaluated already?)
  if func_name in parser_state.FuncLogicLookupTable:
    orig_func_logic = parser_state.FuncLogicLookupTable[func_name]
  else:
    # C built in logic (not parsed from function definitions)
    # Build an original instance logic (has instance name but not prepended with full hierarchy yet)
        
    # Look up containing func logic for this submodule isnt
    containing_func_logic = None
    # Try to use full inst name of containing module
    containing_func_logic = parser_state.LogicInstLookupTable[containing_logic_inst_name]
    #if containing_func_logic is not None:      
    orig_func_logic = BUILD_C_BUILT_IN_SUBMODULE_FUNC_LOGIC(containing_func_logic, local_inst_name, parser_state)
    orig_func_logic.containing_funcs.add(containing_func_logic.func_name)
    # Update FuncLogicLookupTable with this new func logic
    parser_state.FuncLogicLookupTable[orig_func_logic.func_name] = orig_func_logic
    
    
  # Record this instance of func logic
  inst_name = new_inst_name_prepend_text + local_inst_name
  parser_state.LogicInstLookupTable[inst_name] = orig_func_logic
  if func_name not in parser_state.FuncToInstances:
    parser_state.FuncToInstances[func_name] = set()
  parser_state.FuncToInstances[func_name].add(inst_name)
  
  # Then recursively do submodules
  # USING local names from orig_func_logic
  for submodule_inst in orig_func_logic.submodule_instances:
    submodule_func_name = orig_func_logic.submodule_instances[submodule_inst]
    submodule_inst_name = inst_name + SUBMODULE_MARKER + submodule_inst
    submodule_c_ast_node_when_used = orig_func_logic.submodule_instance_to_c_ast_node[submodule_inst]
    submodule_containing_logic_inst_name = inst_name    
    parser_state = RECURSIVE_ADD_LOGIC_INST_LOOKUP_INFO(submodule_func_name, submodule_inst, parser_state, submodule_containing_logic_inst_name, submodule_c_ast_node_when_used)

  return parser_state

def APPEND_PRAGMA_INFO(parser_state):
  # Get all pragmas in ast
  pragmas = C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(parser_state.c_file_ast, c_ast.Pragma, parser_state)
  
  # Parse some stuff
  parser_state.main_mhz = dict() # MAIN_MHZ
  parser_state.main_marked_debug = set()
  
  # Loop over all pragmas
  for pragma in pragmas:
    toks = pragma.string.split(" ")
    name = toks[0]
    
    # MAIN (None MHz)
    if name=="MAIN":
      main_func = toks[1]
      mhz = None
      parser_state.main_mhz[main_func] = mhz
    
    # MAIN_MHZ
    if name=="MAIN_MHZ":
      toks = pragma.string.split(" ")
      main_func = toks[1]
      mhz_tok = toks[2]
      # Allow float MHz or name of another main func
      try:
          mhz = float(mhz_tok)
          parser_state.main_mhz[main_func] = mhz
      except ValueError:
          #"Not a float"
          if mhz_tok in parser_state.main_mhz:
            parser_state.main_mhz[main_func] = parser_state.main_mhz[mhz_tok]
          else:
            print("Error in MAIN_MHZ:",main_func, mhz_tok)
            sys.exit(-1)
  
    # MAIN_MARK_DEBUG
    if name=="MAIN_MARK_DEBUG":
      toks = pragma.string.split(" ")
      main_func = toks[1]
      parser_state.main_marked_debug.add(main_func)
      
    # FUNC_WIRES
    if name=="FUNC_WIRES":
      toks = pragma.string.split(" ")
      main_func = toks[1]
      parser_state.func_marked_wires.add(main_func)
  
    # PART
    if name=="PART":
      toks = pragma.string.split(" ")
      part = toks[1].strip('"').strip()
      #print("part",part)
      #sys.exit(0)
      if parser_state.part is not None and parser_state.part != part:
        print("Already set part to:",parser_state.part,"!=",part)
        sys.exit(-1)
      parser_state.part = part
  
  
  # Sanity checks
  # MAIN_MHZ
  if len(parser_state.main_mhz) == 0:
    print("No main function specified?")
    print("Ex. #pragma MAIN_MHZ main 100.0")
    sys.exit(-1)

def GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(text, fake_filename):
  ast = GET_C_FILE_AST_FROM_C_CODE_TEXT(text, fake_filename)
  func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, ast.ext)
  #if len(func_defs) > 0:
  # print "Coord of func def", func_defs[0].coord
    
  #print "========="
  return func_defs

def GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(c_text, c_filename):
    #print "========="
    #print "fake_filename",fake_filename
    #print "preprocessed text",c_text
    
    # Hacky because somehow parser.parse() getting filename from cpp output?
    c_text = c_text.replace("<stdin>",c_filename)
    parser = c_parser.CParser()
    ast = parser.parse(c_text,filename=c_filename)
    #ast.show()
    return ast
    
    
def GET_C_FILE_AST_FROM_C_CODE_TEXT(text, c_filename):
  # Use C parser to do some lifting
  # See https://github.com/eliben/pycparser/blob/master/examples/explore_ast.py
  try:
    # Use preprocessor function
    c_text = preprocess_text(text)
    return GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(c_text, c_filename)
  except c_parser.ParseError as pe:
    print("Parsed fake file name:",c_filename)
    print("Parsed text:")
    print(c_text)
    print("pycparser says you messed up here:",pe)
    #casthelp(pe)
    sys.exit(-1)
  

def GET_C_AST_FUNC_DEFS(c_file_ast):
  #c_file_ast.show()
  # children are "external declarations",
  # and are stored in a list called ext[]
  func_defs = GET_TYPE_FROM_LIST(c_ast.FuncDef, c_file_ast.ext)
  return func_defs
  
def GET_C_AST_STRUCT_DEFS(c_file_ast):
  # Get type defs
  type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
  struct_defs = []
  for type_def in type_defs:
    #casthelp(type_def)
    thing = type_def.children()[0][1].children()[0][1]
    if type(thing) == c_ast.Struct:
      struct_defs.append(thing)
      
  return struct_defs
  
def GET_C_AST_ENUM_DEFS(c_file_ast):
  # Get type defs
  type_defs = GET_TYPE_FROM_LIST(c_ast.Typedef, c_file_ast.ext)
  enum_defs = []
  for type_def in type_defs:
    #casthelp(type_def)
    thing = type_def.children()[0][1].children()[0][1]
    if type(thing) == c_ast.Enum:
      enum_defs.append(thing)
  #print enum_defs
  #sys.exit(-1)    
  return enum_defs
  
def GET_C_AST_GLOBAL_DECLS(c_file_ast):  
  # Get type defs
  variable_defs = GET_TYPE_FROM_LIST(c_ast.Decl, c_file_ast.ext)
    
  return variable_defs

'''
def GET_C_AST_VOLATILE_GLOBALS(c_file_ast):
  #c_file_ast.show()
  #print c_file_ast.ext
  #sys.exit(-1)
  # Get type defs
  variable_defs = GET_TYPE_FROM_LIST(c_ast.Decl, c_file_ast.ext)
  
  # Filter TO volatile
  volatile_global_defs = []
  for variable_def in variable_defs:
    #print variable_def
    #print variable_def.quals
    if 'volatile' in variable_def.quals:
      volatile_global_defs.append(variable_def)
    
  #sys.exit(-1)
  
  #print variable_defs
  #sys.exit(-1)
    
  return volatile_global_defs
'''


# Filter out a certain type from a list
# Im dumb at python
def GET_TYPE_FROM_LIST(py_type, l):
  rv = []
  for i in l:
    if type(i) == py_type:
      rv.append(i)
  return rv
