
# FIR stuff from
# https://scipy-cookbook.readthedocs.io/items/FIRFilter.html

from numpy import cos, sin, pi, absolute, arange, array, zeros, max, abs, round, int16
from scipy.signal import kaiserord, lfilter, firwin, freqz
from pylab import figure, clf, plot, xlabel, ylabel, xlim, ylim, title, grid, axes, show
from os import path


#------------------------------------------------
# Create a signal for demonstration.
#------------------------------------------------

sample_rate = 100.0
nsamples = 250
t = arange(nsamples) / sample_rate
x = cos(2*pi*0.5*t) + 0.2*sin(2*pi*2.5*t+0.1) + \
        0.2*sin(2*pi*15.3*t) + 0.1*sin(2*pi*16.7*t + 0.1) + \
            0.1*sin(2*pi*23.45*t+.8)
 
# Normalize to between -1.0 and +1.0
x /= max(abs(x),axis=0)

# Convert float to-from i16
i16_max = (2**15)-1
def to_int16(f):
  return round(f*i16_max).astype(int16)
def to_float(i16):
  return i16.astype(float)/i16_max

def i16_c_array_txt(x, name):
  x_i16 = to_int16(x)
  c_txt = ""
  c_txt += f"#define {name}_SIZE {len(x)}\n"
  c_txt += f"#define {name}" + " {\\\n"
  for i,xi in enumerate(x_i16):
    c_txt += f"{xi}"
    if i!=len(x_i16)-1:
      c_txt += f",\\\n"
    else:
      c_txt += "\\\n}\n"
  return c_txt

# Write samples as a C int16 array
f=open("samples.h","w")
f.write(i16_c_array_txt(x,"SAMPLES"))
f.close()


#------------------------------------------------
# Create a FIR filter and apply it to x.
#------------------------------------------------

# The Nyquist rate of the signal.
nyq_rate = sample_rate / 2.0

# The desired width of the transition from pass to stop,
# relative to the Nyquist rate.  We'll design the filter
# with a 5 Hz transition width.
width = 5.0/nyq_rate

# The desired attenuation in the stop band, in dB.
ripple_db = 60.0

# Compute the order and Kaiser parameter for the FIR filter.
N, beta = kaiserord(ripple_db, width)

# The cutoff frequency of the filter.
cutoff_hz = 10.0

# Use firwin with a Kaiser window to create a lowpass FIR filter.
taps = firwin(N, cutoff_hz/nyq_rate, window=('kaiser', beta))
#print("taps",taps)
#print(i16_c_array_txt(taps, "TAPS"))
#print("conv",to_float(to_int16(taps)))

# Use lfilter to filter x with the FIR filter.
filtered_x = lfilter(taps, 1.0, x)


# Read simulation filtered output, start with zeros
sim_filtered_x = array([0]*len(filtered_x))
fname = "sim_output.log"
if path.isfile(fname):
  # Parse samples values
  i16_values = []
  f = open(fname,"r")
  lines = f.readlines()
  i = 0
  for line in lines:
    tok = "Sample ="
    if tok in line and i < len(filtered_x):
      int_val = int(line.split(tok)[1])
      f_val = float(int_val)/float(i16_max)
      #print("Sample =", i, int_val, f_val)
      #i16_values.append(int_val)
      #sim_filtered_x[i] = f_val # WTF doesnt work?
      list_sim_filtered_x = list(sim_filtered_x)
      list_sim_filtered_x[i] = f_val
      sim_filtered_x = array(list_sim_filtered_x)
      i+=1
      #print("sim_filtered_x",sim_filtered_x)
  #sim_filtered_x = to_float(array(i16_values))


#------------------------------------------------
# Plot the FIR filter coefficients.
#------------------------------------------------
"""
figure(1)
plot(taps, 'bo-', linewidth=2)
title('Filter Coefficients (%d taps)' % N)
grid(True)
"""
#------------------------------------------------
# Plot the magnitude response of the filter.
#------------------------------------------------
"""
figure(2)
clf()
w, h = freqz(taps, worN=8000)
plot((w/pi)*nyq_rate, absolute(h), linewidth=2)
xlabel('Frequency (Hz)')
ylabel('Gain')
title('Frequency Response')
ylim(-0.05, 1.05)
grid(True)

# Upper inset plot.
ax1 = axes([0.42, 0.6, .45, .25])
plot((w/pi)*nyq_rate, absolute(h), linewidth=2)
xlim(0,8.0)
ylim(0.9985, 1.001)
grid(True)

# Lower inset plot
ax2 = axes([0.42, 0.25, .45, .25])
plot((w/pi)*nyq_rate, absolute(h), linewidth=2)
xlim(12.0, 20.0)
ylim(0.0, 0.0025)
grid(True)
"""
#------------------------------------------------
# Plot the original and filtered signals.
#------------------------------------------------

# The phase delay of the filtered signal.
delay = 0.5 * (N-1) / sample_rate
"""
figure(3)
# Plot the original signal.
plot(t, x)
# Plot the filtered signal, shifted to compensate for the phase delay.
plot(t-delay, filtered_x, 'r-')
# Plot just the "good" part of the filtered signal.  The first N-1
# samples are "corrupted" by the initial conditions.
plot(t[N-1:]-delay, filtered_x[N-1:], 'g', linewidth=4)

xlabel('t')
grid(True)
"""


# Plot the expected output vs simulation output
# NO DELAY?
delay = 0.0
figure(1)
title('Expected (green) vs. Sim (blue)')
# Plot the filtered signal, shifted to compensate for the phase delay.
plot(t-delay, filtered_x, 'r-')
# Plot just the "good" part of the filtered signal.  The first N-1
# samples are "corrupted" by the initial conditions.
plot(t[N-1:]-delay, filtered_x[N-1:], 'g', linewidth=4)
# Plot the simulated signal, shifted to compensate for the phase delay.
plot(t-delay, sim_filtered_x, 'b')

xlabel('t')
grid(True)




show()