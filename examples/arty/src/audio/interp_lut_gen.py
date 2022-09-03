import math
import sys

# Representation Qm.n numbers
INPUT_M = 0
INPUT_N = 23
OUTPUT_M = 0
OUTPUT_N = 23

# The function to make a LUT for
func_name="distortion_mono"
def f(x):
  gain = 15.0
  sign =  1.0
  if x < 0.0:
    sign = -1.0
  return sign * (1.0 - math.exp(gain*-abs(x)))
  
# LUT Params
LOG2_NUM_ENTRIES = 8

# ==============================================================================

print("Input: Q" + str(INPUT_M) + "." + str(INPUT_N))
print("Output: Q" + str(OUTPUT_M) + "." + str(OUTPUT_N))

def q_in_to_float(q):
  f = q * (2.0**(-1.0*INPUT_N))
  return f
  
def q_out_to_float(q):
  f = q * (2.0**(-1.0*OUTPUT_N))
  return f

INPUT_FIXED_BITWIDTH = INPUT_M + INPUT_N + 1 # Q0.23 24b
INPUT_INT_MIN = -1 * 2**(INPUT_FIXED_BITWIDTH-1)
INPUT_INT_MAX = 2**(INPUT_FIXED_BITWIDTH-1) - 1
INPUT_MIN = q_in_to_float(INPUT_INT_MIN)
INPUT_MAX = q_in_to_float(INPUT_INT_MAX)

OUTPUT_FIXED_BITWIDTH = OUTPUT_M + OUTPUT_N + 1 # Q0.23 24b
OUTPUT_INT_MIN = -1 * 2**(OUTPUT_FIXED_BITWIDTH-1)
OUTPUT_INT_MAX = 2**(OUTPUT_FIXED_BITWIDTH-1) - 1
OUTPUT_MIN = q_out_to_float(OUTPUT_INT_MIN)
OUTPUT_MAX = q_out_to_float(OUTPUT_INT_MAX)

print("INPUT_FIXED_BITWIDTH",INPUT_FIXED_BITWIDTH)
print("INPUT_INT_MIN",hex(INPUT_INT_MIN), INPUT_MIN)
print("INPUT_INT_MAX",hex(INPUT_INT_MAX), INPUT_MAX)
print("OUTPUT_FIXED_BITWIDTH",OUTPUT_FIXED_BITWIDTH)
print("OUTPUT_INT_MIN",hex(OUTPUT_INT_MIN), OUTPUT_MIN)
print("OUTPUT_INT_MAX",hex(OUTPUT_INT_MAX), OUTPUT_MAX)
  
def float_to_q_out(f):
  if f > OUTPUT_MAX:
    print("Output float",f,"doesnt fit in Q", OUTPUT_M, OUTPUT_N, "fixed point")
    sys.exit(-1)
  q = int(f * (2**OUTPUT_N))
  return q  

# Determine the lookup points (x fixed, y fixed, m floating point) with increment through input i24 range
# Convert to float, eval f(x), convert back to output LUT entry Q format
NUM_ENTRIES = 2**LOG2_NUM_ENTRIES
INPUT_RANGE_SIZE = INPUT_MAX-INPUT_MIN
INTERP_SIZE = INPUT_RANGE_SIZE / NUM_ENTRIES
INTERP_FIXED_BITS = INPUT_FIXED_BITWIDTH - LOG2_NUM_ENTRIES
INTERP_SIZE_FIXED = 2**INTERP_FIXED_BITS
print("NUM_ENTRIES",NUM_ENTRIES)
print("INPUT_RANGE_SIZE",INPUT_RANGE_SIZE)
print("INTERP_SIZE",INTERP_SIZE)
print("INTERP_FIXED_BITS",INTERP_FIXED_BITS)
print("INTERP_SIZE_FIXED",INTERP_SIZE_FIXED)

x_int = INPUT_INT_MIN
x_ints = []
y_ints = []
m_floats = []
while x_int < INPUT_INT_MAX:
  x_float = q_in_to_float(x_int)
  x_next_float = x_float + INTERP_SIZE
  y_float = f(x_float)
  y_next_float = f(x_next_float)
  y_int = float_to_q_out(y_float)
  m_float = (y_next_float-y_float)/(x_next_float-x_float)
  #m_float_scaled = m_float / (2**INPUT_FIXED_BITWIDTH)
  x_ints.append(x_int)
  y_ints.append(y_int)
  m_floats.append(m_float)
  x_int += INTERP_SIZE_FIXED
  
# Determine fixed point size for slope fixed point values
m_max = max(abs(min(m_floats)),max(m_floats))
m_int_max = int(math.floor(m_max))
m_int_bitwidth = m_int_max.bit_length()
M_M = m_int_bitwidth # great names...
# At least as many frac bits as in or out request?
M_N = max(INPUT_N, OUTPUT_N)
M_FIXED_BITWIDTH = M_M + M_N + 1
print("m_max",m_max)
print("m_int_max",m_int_max)
#print("m_int_bitwidth",m_int_bitwidth)
#print("Slope: Q" + str(M_M) + "." + str(M_N))

# Scale to fit into inputs and outputs bit widths
# M_N total bits
M_scaled_M = max(INPUT_M, OUTPUT_M)
M_scaled_N = max(INPUT_N, OUTPUT_N)
m_right_shift_scale = M_M - M_scaled_M
M_scaled_FIXED_BITWIDTH = M_scaled_M + M_scaled_N + 1
print("m_right_shift_scale",m_right_shift_scale)
print("Scaling slope down by 2^"+str(m_right_shift_scale)+" to fit in IO bitwidths")
print("Scaled slope type: Q" + str(M_scaled_M) + "." + str(M_scaled_N))

def float_to_m_scaled(f):
  return f / (2**m_right_shift_scale) # Right shift int value by n
  
def m_scaled_to_float(m):
  return m * (2**m_right_shift_scale)
  
def float_to_q_m_scaled(f):
  q = int(f * (2**M_scaled_N))
  return q
  
def q_m_scaled_to_float(q):
  f = q * (2.0**(-1.0*M_scaled_N))
  return f

# Scaled slope value
m_ints = []
for m_float in m_floats:
  m_float_scaled = float_to_m_scaled(m_float)
  m_ints.append(float_to_q_m_scaled(m_float_scaled))
  
# Determine fixed point size for dy=slope*dx
dy_max = m_max * INTERP_SIZE
dy_int_max = int(math.floor(dy_max))
dy_int_bitwidth = dy_int_max.bit_length()
dy_M = dy_int_bitwidth # great names...
# At least as many frac bits as in or out request?
dy_N = max(M_N, OUTPUT_N)
dy_FIXED_BITWIDTH = dy_M + dy_N + 1
print("dy_max",dy_max)
print("dy_int_max",dy_int_max)
print("dy_int_bitwidth",dy_int_bitwidth)
print("dy: Q" + str(dy_M) + "." + str(dy_N))
# TODO scaled dy?
  
y_text = ""
m_text = "" 
for i,x_int in enumerate(x_ints):
  interp_points_mask = (2**INTERP_FIXED_BITS)-1 << 0
  lut_addr_bits_mask = (2**LOG2_NUM_ENTRIES)-1 << INTERP_FIXED_BITS;
  interp_point_bits = x_ints[i] & interp_points_mask;
  lut_addr_bits = (x_ints[i] & lut_addr_bits_mask) >> INTERP_FIXED_BITS
  x_float = q_in_to_float(x_ints[i])
  y_float = q_out_to_float(y_ints[i])
  m_float = q_m_scaled_to_float(m_ints[i])
  #if i<10:
  #  print("x_float",x_float, "x_int", hex(x_ints[i]), "lut_addr_bits", hex(lut_addr_bits), "interp_point_bits", hex(interp_point_bits))
  #  print("y_float", y_float, "y_int", hex(y_ints[i]))
  #  print("m_float", m_float, "m_int",hex(m_ints[i]))
  y_text += "Y_VALUES[" + str(lut_addr_bits) + "].qmn = " + str(hex(y_ints[i])) + ";\n"
  m_text += "M_VALUES[" + str(lut_addr_bits) + "].qmn = " + str(hex(m_ints[i])) + ";\n"

print("")
print('#include "lib/fixed/q'+str(INPUT_M)+"_"+str(INPUT_N) + '.h"')
print('#include "lib/fixed/q'+str(M_scaled_M)+"_"+str(M_scaled_N) + '.h"')
print('#include "lib/fixed/q'+str(dy_M)+"_"+str(dy_N) + '.h"')
print('#include "lib/fixed/q'+str(OUTPUT_M)+"_"+str(OUTPUT_N) + '.h"')
print("q"+str(OUTPUT_M)+"_"+str(OUTPUT_N) + "_t " + func_name + "(" + "q"+str(INPUT_M)+"_"+str(INPUT_N) + "_t x)")
print("{")
print("// Get lookup addr from top bits of value")
print("uint" + str(LOG2_NUM_ENTRIES) + "_t lut_addr = int" + str(INPUT_FIXED_BITWIDTH) + "_" + str(INPUT_FIXED_BITWIDTH-1) + "_" + str(INPUT_FIXED_BITWIDTH-LOG2_NUM_ENTRIES) + "(x.qmn);")
print("// And interpolation bits from lsbs")
print("uint"+str(INTERP_FIXED_BITS)+"_t interp_point = int" + str(INPUT_FIXED_BITWIDTH) + "_" + str(INTERP_FIXED_BITS-1) + "_0(x.qmn);")
print("// Generated lookup values:")
print("q"+str(OUTPUT_M)+"_"+str(OUTPUT_N) + "_t Y_VALUES["+str(NUM_ENTRIES) + "];")
print(y_text)
print("// M Scaled down by 2^"+str(m_right_shift_scale))
print("q"+str(M_scaled_M)+"_"+str(M_scaled_N) + "_t M_VALUES["+str(NUM_ENTRIES) + "];")
print(m_text)
print("// Do lookup")
print("q"+str(OUTPUT_M)+"_"+str(OUTPUT_N) + "_t y = Y_VALUES[lut_addr];")
print("q"+str(M_scaled_M)+"_"+str(M_scaled_N) + "_t m = M_VALUES[lut_addr];")
print("")
print("// Do linear interp, dy = dx * m")
print("// Not using fixed point mult funcs since")
print("// need intermediates to do different scaling than normal");
print("q"+str(INPUT_M)+"_"+str(INPUT_N) + "_t dxi; // Fractional bits of input x")
print("dxi.qmn = interp_point;");
assert(INPUT_M==M_scaled_M)
assert(INPUT_N==M_scaled_N)
print("int"+str(INPUT_FIXED_BITWIDTH+M_scaled_FIXED_BITWIDTH)+"_t temp = dxi.qmn * m.qmn;")
print("int"+str(INPUT_FIXED_BITWIDTH+M_scaled_FIXED_BITWIDTH)+"_t temp_rounded = temp + (1 << ("+str(INPUT_N)+" - 1));")
print('''// Shift right by ''' + str(INPUT_N) + " for normal Q mult, then shift left by " + str(m_right_shift_scale) + ''' to account for slope scaling''')
print("q"+str(dy_M)+"_"+str(dy_N) + "_t dy;")
print('''dy.qmn = temp >> ''' + str(INPUT_N-m_right_shift_scale) + ''';''')
print("// Interpolate")
assert(dy_M==OUTPUT_M)
assert(dy_N==OUTPUT_N)
print("q"+str(OUTPUT_M)+"_"+str(OUTPUT_N) + "_t yi = q"+str(dy_M) + "_" + str(dy_N) + "_add(y, dy);")
print("return yi;")
print("}")

