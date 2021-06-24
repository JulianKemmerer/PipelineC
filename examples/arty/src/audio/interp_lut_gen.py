import math 
import sys

# Representation Qm.n numbers
INPUT_M = 0
INPUT_N = 23
OUTPUT_M = 0
OUTPUT_N = 23

# The function to make a LUT for
def f(x):
  sign =  1.0
  if x < 0.0:
    sign = -1.0
  return sign * (1.0 - math.exp(-abs(x)))
# LUT Params
LOG2_NUM_ENTIRES = 7

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
    print("Float",f,"doesnt fit in Q", OUTPUT_M, OUTPUT_N, "fixed point")
    sys.exit(-1)
  q = int(f * (2**OUTPUT_N))
  return q  

# Determine the lookup points (x fixed, y fixed, m floating point) with increment through input i24 range
# Convert to float, eval f(x), convert back to output LUT entry Q format
NUM_ENTRIES = 2**LOG2_NUM_ENTIRES
INPUT_RANGE_SIZE = INPUT_MAX-INPUT_MIN
INTERP_SIZE = INPUT_RANGE_SIZE / NUM_ENTRIES
INTERP_FIXED_BITS = INPUT_FIXED_BITWIDTH - LOG2_NUM_ENTIRES
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
print("m_int_bitwidth",m_int_bitwidth)
print("Slope: Q" + str(M_M) + "." + str(M_N))

def float_to_q_m(f):
  q = int(f * (2**M_N))
  return q
  
def q_m_to_float(q):
  f = q * (2.0**(-1.0*M_N))
  return f

m_ints = []
for m_float in m_floats:
  m_ints.append(float_to_q_m(m_float))
  
  
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
  
y_text = ""
m_text = "" 
for i,x_int in enumerate(x_ints):
  interp_points_mask = (2**INTERP_FIXED_BITS)-1 << 0
  lut_addr_bits_mask = (2**LOG2_NUM_ENTIRES)-1 << INTERP_FIXED_BITS;
  interp_point_bits = x_ints[i] & interp_points_mask;
  lut_addr_bits = (x_ints[i] & lut_addr_bits_mask) >> INTERP_FIXED_BITS
  x_float = q_in_to_float(x_ints[i])
  y_float = q_out_to_float(y_ints[i])
  m_float = q_m_to_float(m_ints[i])
  if i<10:
    print("x_float",x_float, "x_int", hex(x_ints[i]), "lut_addr_bits", hex(lut_addr_bits), "interp_point_bits", hex(interp_point_bits))
    print("y_float", y_float, "y_int", hex(y_ints[i]))
    print("m_float", m_float, "m_int",hex(m_ints[i]))
  
  y_text += "Y_VALUES[" + str(lut_addr_bits) + "].qmn = " + str(hex(y_ints[i])) + ";\n"
  m_text += "M_VALUES[" + str(lut_addr_bits) + "].qmn = " + str(hex(m_ints[i])) + ";\n"

print(y_text)
print(m_text)
