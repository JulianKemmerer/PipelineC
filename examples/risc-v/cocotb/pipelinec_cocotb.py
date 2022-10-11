
def halt(dut, val_input=None):
  if val_input:
    dut.halt_DEBUG_return_output = val_input
  else:
    return dut.halt_DEBUG_return_output
          
def main_return(dut, val_input=None):
  if val_input:
    dut.main_return_DEBUG_return_output = val_input
  else:
    return dut.main_return_DEBUG_return_output
          
def unknown_op(dut, val_input=None):
  if val_input:
    dut.unknown_op_DEBUG_return_output = val_input
  else:
    return dut.unknown_op_DEBUG_return_output

def mem_out_of_range(dut, val_input=None):
  if val_input:
    dut.mem_out_of_range_DEBUG_return_output = val_input
  else:
    return dut.mem_out_of_range_DEBUG_return_output
          
def DUMP_PIPELINEC_DEBUG(dut):
  print("halt =", halt(dut), flush=True)
  print("main_return =", main_return(dut), flush=True)
  print("unknown_op =", unknown_op(dut), flush=True)

risc_v_LATENCY = 0
reg_file_SPLIT3_LATENCY = 0
halt_DEBUG_LATENCY = 0
main_return_DEBUG_LATENCY = 0
mem_SPLIT2_LATENCY = 0
unknown_op_DEBUG_LATENCY = 0
