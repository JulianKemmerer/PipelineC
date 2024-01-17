from numpy import cos, sin, pi, absolute, arange, array, zeros, max, abs, round, int16, exp, arctan2, diff, unwrap, imag, real
from scipy.signal import kaiserord, lfilter, firwin, freqz
from pylab import figure, clf, plot, xlabel, ylabel, xlim, ylim, title, grid, axes, show
from os import path

# Helpers to convert float to-from i16
i16_max = (2**15)-1
def to_int16(f):
  return round(f*i16_max).astype(int16)
def to_float(i16):
  return i16.astype(float)/i16_max
# and how to write C arrays
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
# Convert to IQ samples
def real_to_iq(t, s, fc):
  # Could do IQ separate real values:
  #   I=s*np.cos(2 * pi * fc * t)
  #   Q=s*np.sin(2 * pi * fc * t)
  # Typically do as imaginary:
  #   e^(j*theta) = cos(theta) + j * sin(theta)
  iq = s * exp(1.0j * 2 * pi * fc * t)
  return iq


#------------------------------------------------
# Create a signal for demonstration.
#------------------------------------------------

def make_fir_demo_samples(sample_rate, nsamples_in):
  # FIR stuff from
  # https://scipy-cookbook.readthedocs.io/items/FIRFilter.html
  t = arange(nsamples_in) / sample_rate
  s = cos(2*pi*0.5*t) + 0.2*sin(2*pi*2.5*t+0.1) + \
          0.2*sin(2*pi*15.3*t) + 0.1*sin(2*pi*16.7*t + 0.1) + \
              0.1*sin(2*pi*23.45*t+.8)

  # Normalize to between -1.0 and +1.0
  s /= max(abs(s),axis=0)
  # For now make same signal on both I(real) and Q(imaginary) channels
  s_i = array(s)
  s_q = array(s)
  return s_i,s_q
#sample_rate = 100.0
#nsamples_in = 250
#s_i,s_q = make_fir_demo_samples(sample_rate,nsamples_in)

def make_fm_test_input(Fs, fc):
  # FM Modulation Python Script
  # https://www.rfwireless-world.com/source-code/Python/FM-modulation-demodulation-python-code.html
  # Setting up FM modulation simulation parameters
  t = arange(0,0.2,1/Fs)
  fm1 = 30 # Signal frequency-1 to construct message signal
  fm2 = 45 # Signal frequency-2 to construct message signal
  b = 1 # modulation index
  m_signal = sin(2*pi*fm1*t) + sin(2*pi*fm2*t)
  #carrier_signal = sin(2 * pi * fc * t)
  # Generate Frequency modulated signal
  fmd = sin(2*pi*fc*t + b*m_signal)
  return t,fmd
fc = 100 # carrier frequency
sample_rate = 2000
t,fmd = make_fm_test_input(sample_rate, fc)
nsamples_in = len(fmd)
fmd_iq = real_to_iq(t, fmd, fc)
s_i = fmd_iq.real
s_q = fmd_iq.imag


# Write samples as a C int16 array input for simulation
f=open("samples.h","w")
f.write(i16_c_array_txt(s_i,"I_SAMPLES"))
f.write(i16_c_array_txt(s_q,"Q_SAMPLES"))
f.close()


#------------------------------------------------
# Create a filter and apply it to s.
#------------------------------------------------
#return sample_rate_out,filtered_s_i,filtered_s_q
def example_fir_dsp(sample_rate, s_i, s_q): 
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

  # Use lfilter to filter s with the FIR filter.
  filtered_s_i = lfilter(taps, 1.0, s_i)
  filtered_s_q = lfilter(taps, 1.0, s_q)
  sample_rate_out = sample_rate # No sample rate change
  return sample_rate_out,filtered_s_i,filtered_s_q

def decim_5x(sample_rate, s_i, s_q): 
  taps_int16 = [ -165, \
  -284, \
  -219, \
  -303, \
  -190, \
  -102, \
  98,   \
  268,  \
  430,  \
  482,  \
  420,  \
  207,  \
  -117, \
  -498, \
  -835, \
  -1022,\
  -957, \
  -576, \
  135,  \
  1122, \
  2272, \
  3429, \
  4419, \
  5086, \
  5321, \
  5086, \
  4419, \
  3429, \
  2272, \
  1122, \
  135,  \
  -576, \
  -957, \
  -1022,\
  -835, \
  -498, \
  -117, \
  207,  \
  420,  \
  482,  \
  430,  \
  268,  \
  98,   \
  -102, \
  -190, \
  -303, \
  -219, \
  -284, \
  -165]
  taps_int16 = array(taps_int16)
  taps = to_float(taps_int16)
 
  # Use lfilter to filter s with the FIR filter.
  filtered_s_i = lfilter(taps, 1.0, s_i)
  filtered_s_q = lfilter(taps, 1.0, s_q)

  # Decimate by 5, Drop 4/5 samples
  decim_fac = 5
  sample_rate_out = sample_rate/decim_fac
  dec_filt_s_i = []
  dec_filt_s_q = []
  i = decim_fac-1
  list_filtered_s_i = list(filtered_s_i)
  list_filtered_s_q = list(filtered_s_q)
  while i < len(filtered_s_i):
    # Take sample
    dec_filt_s_i.append(list_filtered_s_i[i])
    dec_filt_s_q.append(list_filtered_s_q[i])
    # Skip samples
    i += decim_fac
  return sample_rate_out,array(dec_filt_s_i),array(dec_filt_s_q)

def fm_demod(x, df=1.0, fc=0.0):
    ''' Perform FM demodulation of complex carrier.

    Args:
        x (array):  FM modulated complex carrier.
        df (float): Normalized frequency deviation [Hz/V].
        fc (float): Normalized carrier frequency.

    Returns:
        Array of real modulating signal.
    '''
    # https://stackoverflow.com/questions/60193112/python-fm-demod-implementation

    # Remove carrier.
    n = arange(len(x)) 
    rx = x*exp(-1j*2*pi*fc*n) #Not needed?

    # Extract phase of carrier.
    phi = arctan2(imag(rx), real(rx))

    # Calculate frequency from phase.
    y = diff(unwrap(phi)/(2*pi*df))

    return y



# Get expected output by applying some DSP
# FIR decim example:
#sample_rate_out,filtered_s_i,filtered_s_q = decim_5x(sample_rate, s_i, s_q)
#nsamples_out = min(len(filtered_s_i),len(filtered_s_q))
#t_out = arange(nsamples_out) / sample_rate_out
# FM demod example
sample_rate_out = sample_rate
nsamples_out = nsamples_in-1 #? Why one less?
t_out = t[1:] #? Why one less?
df = 1.0 # ?1.0 / sample_rate_out #? What is norm freq dev?
filtered_s_i = fm_demod(fmd_iq, df, fc) 
filtered_s_q = array([0]*len(filtered_s_i)) # no output second channel



#------------------------------------------------
# # Read simulation filtered output, start with zeros
#------------------------------------------------
sim_filtered_s_i = array([0]*nsamples_out)
sim_filtered_s_q = array([0]*nsamples_out)
fname = "sim_output.log"
if path.isfile(fname):
  # Parse samples values
  list_sim_filtered_s_i = list(sim_filtered_s_i)
  list_sim_filtered_s_q = list(sim_filtered_s_q)
  i16_values = []
  f = open(fname,"r")
  lines = f.readlines()
  i = 0
  for line in lines:
    tok = "Sample IQ ="
    if tok in line and i < nsamples_out:
      toks = line.split(",")
      i_int_val = int(toks[2])
      i_f_val = float(i_int_val)/float(i16_max)
      q_int_val = int(toks[3])
      q_f_val = float(q_int_val)/float(i16_max)
      #print("Sample =", i, int_val, f_val)
      #i16_values.append(int_val)
      list_sim_filtered_s_i[i] = i_f_val
      list_sim_filtered_s_q[i] = q_f_val
      i+=1
      #print("sim_filtered_x",sim_filtered_x)
  sim_filtered_s_i = array(list_sim_filtered_s_i)
  sim_filtered_s_q = array(list_sim_filtered_s_q)
else:
  # No sim output yet to compare, just stop
  #exit(0)
  pass



#------------------------------------------------
# Plot the original and filtered signals.
#------------------------------------------------
# Plot the original signal.
figure(1)
title('IQ Input')
plot(t, s_i, 'k', label='I')
#xlabel('t')
#grid(True)
#figure(2)
#title('Q - Input')
plot(t, s_q, 'r', label='Q')
xlabel('t')
grid(True)


# Plot the expected output vs simulation output
figure(2)
title('I (or single channel) - Expected (green) vs. Sim (blue)')
plot(t_out, filtered_s_i, 'g', linewidth=4)
plot(t_out, sim_filtered_s_i, 'b')
xlabel('t')
grid(True)
figure(3)
title('Q - Expected (green) vs. Sim (blue)')
plot(t_out, filtered_s_q, 'g', linewidth=4)
plot(t_out, sim_filtered_s_q, 'b')
xlabel('t')
grid(True)


show()