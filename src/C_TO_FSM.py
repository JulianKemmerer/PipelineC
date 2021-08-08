import sys
import copy
from pycparser import c_parser, c_ast, c_generator

import C_TO_LOGIC

def PARSE_FILE(c_filename):
  c_text = open(c_filename).read()
  c_ast_func_defs = C_TO_LOGIC.GET_C_AST_FUNC_DEFS_FROM_C_CODE_TEXT(c_text, c_filename)
  for c_ast_func_def in c_ast_func_defs:
    C_AST_FUNC_DEF_TO_FSM_LOGIC(c_ast_func_def)
  sys.exit(0) 

class FsmStateInfo:
  def __init__(self):
    self.name = None
    self.c_ast_nodes = [] # C ast nodes
    # Todo other flags?
    self.mux_nodes = []
    
  def print(self):
    print("Name: " + str(self.name))
    print("c_ast_nodes: ",self.c_ast_nodes)
    print("mux_nodes: ",self.mux_nodes)

# Storing per func dict of state_name -> FsmStateInfo
class FsmLogic:
  def __init__(self):
    #self.state_to_info = dict()
    self.states_list = []


def C_AST_FUNC_DEF_TO_FSM_LOGIC(c_ast_func_def):
  if c_ast_func_def.body.block_items is None:
    return
  fsm_logic = FsmLogic()
  curr_state_info = FsmStateInfo()
  
  # Do pass collecting chunks of comb logic
  for block_item in c_ast_func_def.body.block_items:
    chunks = COLLECT_COMB_LOGIC(block_item)
    #print("chunks",chunks)
    # Chunks are list of comb cast nodes that go into one state
    # Or individual nodes that need additional handling, returns list of one of more states
    for chunk in chunks:
      if type(chunk) == list:
        curr_state_info.c_ast_nodes += chunk
      else:
        # This cuts off the current state adding it to return list
        ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(chunk, curr_state_info)
        fsm_logic.states_list.append(copy.copy(curr_state_info))
        curr_state_info = FsmStateInfo()
        fsm_logic.states_list += ctrl_flow_states
    # Final comb logic chunk
    if len(curr_state_info.c_ast_nodes) > 0:
      fsm_logic.states_list.append(copy.copy(curr_state_info))
    
      
  for state_info in fsm_logic.states_list:
    print("State:")
    state_info.print()
  
  sys.exit(0)
  '''
  # All func def logic has an output wire called "return"
  return_type = c_ast_funcdef.decl.type.type.type.names[0]
  if return_type != "void":
    return_wire_name = RETURN_WIRE_NAME
    parser_state.existing_logic.outputs.append(return_wire_name)
    parser_state.existing_logic.wires.add(return_wire_name)
    #print("return_type",return_type)
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
      c_type,input_var_name = C_AST_DECL_TO_C_TYPE_AND_VAR_NAME(param_decl, parser_state)
      parser_state.existing_logic.wire_to_c_type[input_wire_name] = c_type
  
  
  # Merge with logic from the body of the func def
  driven_wire_names=[]
  prepend_text=""
  if parse_body:
    body_logic = C_AST_NODE_TO_LOGIC(c_ast_funcdef.body, driven_wire_names, prepend_text, parser_state)   
    parser_state.existing_logic.MERGE_COMB_LOGIC(body_logic)
    
  # Connect globals at end of func logic
  parser_state.existing_logic = CONNECT_FINAL_STATE_WIRES(prepend_text, parser_state, c_ast_funcdef)
  '''
  
  
def C_AST_CTRL_FLOW_NODE_TO_STATES(c_ast_node, curr_state_info):
  if type(c_ast_node) == c_ast.If:
    return C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_node, curr_state_info)
  elif type(c_ast_node) is c_ast.FuncCall and c_ast_node.name.name=="__clk":
    return C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_node, curr_state_info)
  else:
    raise Exception(f"Unknown ctrl flow node: {c_ast_node} {c_ast_node.coord}")

def C_AST_CTRL_FLOW_CLK_FUNC_CALL_TO_STATES(c_ast_clk_func_call, curr_state_info):
  states = [] 
  # Single state doing nothing for the clock
  clk_state = FsmStateInfo()
  clk_state.name = "CLOCK_STATE"
  states.append(clk_state)
  return states
  

'''
def C_AST_CTRL_FLOW_COMPOUND_TO_STATES(c_ast_compound, curr_state_info):
  states = [] 
  
  for block_item in :
    # Create a state for true logic and insert it into return list of states
    true_state = FsmStateInfo()
    # Do pass collecting chunks of comb logic
    chunks = COLLECT_COMB_LOGIC(c_ast_if.iftrue)
    # Chunks are list of comb cast nodes that go into one state
    # Or individual nodes that need additional handling, returns list of one of more states
    for chunk in chunks:
      if type(chunk) == list:
        true_state.c_ast_nodes += chunk
      else:
        # This cuts off the current state adding it to return list
        ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(chunk, true_state)
        states.append(copy.copy(true_state))
        states += ctrl_flow_states
'''
    
def C_AST_CTRL_FLOW_IF_TO_STATES(c_ast_if, curr_state_info):
  states = [] 
  
  # Add mux sel calculation, and jumping to true or false states 
  # to current state after comb logic
  curr_state_info.mux_nodes.append(c_ast_if)
  
  # Create a state for true logic and insert it into return list of states
  true_state = FsmStateInfo()
  true_state.name = "TRUE_STATE"
  # Do pass collecting chunks of comb logic
  chunks = COLLECT_COMB_LOGIC(c_ast_if.iftrue)
  # Chunks are list of comb cast nodes that go into one state
  # Or individual nodes that need additional handling, returns list of one of more states
  for chunk in chunks:
    if type(chunk) == list:
      true_state.c_ast_nodes += chunk
    else:
      # This cuts off the current state adding it to return list
      ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(chunk, true_state)
      states.append(copy.copy(true_state))
      states += ctrl_flow_states
  # Final comb logic chunk
  if len(true_state.c_ast_nodes) > 0:
    states.append(copy.copy(true_state))
      
  # Same for false
  false_state = FsmStateInfo()
  false_state.name = "FALSE_STATE"
  # Do pass collecting chunks of comb logic
  chunks = COLLECT_COMB_LOGIC(c_ast_if.iffalse)
  # Chunks are list of comb cast nodes that go into one state
  # Or individual nodes that need additional handling, returns list of one of more states
  for chunk in chunks:
    if type(chunk) == list:
      false_state.c_ast_nodes += chunk
    else:
      # This cuts off the current state adding it to return list
      ctrl_flow_states = C_AST_CTRL_FLOW_NODE_TO_STATES(chunk, false_state)
      states.append(copy.copy(false_state))
      states += ctrl_flow_states
  # Final comb logic chunk
  if len(false_state.c_ast_nodes) > 0:
    states.append(copy.copy(false_state))

  return states

def C_AST_NODE_USES_FSM_CLK(c_ast_node):
  func_call_nodes = C_TO_LOGIC.C_AST_NODE_RECURSIVE_FIND_NODE_TYPE(c_ast_node, c_ast.FuncCall)
  for func_call_node in func_call_nodes:
    if func_call_node.name.name == "__clk":
      return True
  return False 

def COLLECT_COMB_LOGIC(c_ast_node_in):
  chunks = []
  comb_logic_nodes = []
  c_ast_nodes = [c_ast_node_in]
  if type(c_ast_node_in) is c_ast.Compound:
    if c_ast_node_in.block_items is not None:
      c_ast_nodes = c_ast_node_in.block_items[:]
      
  for c_ast_node in c_ast_nodes:
    if not C_AST_NODE_USES_FSM_CLK(c_ast_node):
      comb_logic_nodes.append(c_ast_node)
    else:
      chunks.append(c_ast_node)
      chunks.append(comb_logic_nodes[:])
      comb_logic_nodes = []
  
  # Need final chunk of comb logic
  if len(comb_logic_nodes) > 0:
    chunks.append(comb_logic_nodes[:])
  
  return chunks
  
  

  

  
