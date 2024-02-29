import numpy as np
from matplotlib import pyplot as plt
import SoapySDR
import sys
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CS16

############################################################################################
# Settings
############################################################################################
# Data transfer settings
rx_chan = 1           # Second channel is for debug # RX1 = 0, RX2 = 1
fs = 125e6            # Radio sample Rate (input to custom block)
N = int(250e3*4)               # Number of complex samples per transfer
freq = 93.3e6           # LO tuning frequency in Hz  # Big peak at ~100.7? ~103.5? ~107.9? 93.3?
use_agc = False          # Use or don't use the AGC
timeout_us = int(5e6)
rx_bits = 16            # The AIR-T's ADC is 16 bits

############################################################################################
# Receive Signal
############################################################################################
#  Initialize the AIR-T receiver using SoapyAIRT
print(f"Init radio chan={rx_chan} freq MHz={freq/1e6} use_agc={use_agc}...")
sdr = SoapySDR.Device(dict(driver="SoapyAIRT"))       # Create AIR-T instance
# SDR data is from radio chan0, but received dma ch1
# Configure both channels just to be sure
sdr.setSampleRate(SOAPY_SDR_RX, 0, fs)          # Set sample rate
sdr.setSampleRate(SOAPY_SDR_RX, 1, fs)          # Set sample rate
sdr.setGainMode(SOAPY_SDR_RX, 0, use_agc)       # Set the gain mode
sdr.setGainMode(SOAPY_SDR_RX, 1, use_agc)       # Set the gain mode
if not use_agc:
  gain = 0.0
  print("gain",gain)
  sdr.setGain(SOAPY_SDR_RX, 0, gain)
  sdr.setGain(SOAPY_SDR_RX, 1, gain)
sdr.setFrequency(SOAPY_SDR_RX, 0, freq)         # Tune the LO
sdr.setFrequency(SOAPY_SDR_RX, 1, freq)         # Tune the LO

# Create data buffer and start streaming samples to it
rx_buff = np.empty(2 * N, np.int16)                 # Create memory buffer for data stream
rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, [rx_chan])  # Setup data stream
sdr.activateStream(rx_stream)  # this turns the radio on

# Read the samples from the data buffer
sr = sdr.readStream(rx_stream, [rx_buff], N, timeoutUs=timeout_us)
rc = sr.ret # number of samples read or the error code
assert rc == N, 'Error Reading Samples from Device (error code = %d)!' % rc

#print("yay samples...")
#sys.exit(0)

# Stop streaming
sdr.deactivateStream(rx_stream)
sdr.closeStream(rx_stream)

############################################################################################
# Plot Signal
############################################################################################
# Convert interleaved shorts (received signal) to numpy.complex64 normalized between [-1, 1]
s0 = rx_buff.astype(float) / np.power(2.0, rx_bits-1)
s = (s0[::2] + 1j*s0[1::2])

def plot_signal(s, fs, freq, title=""):
  N=len(s)

  is_complex = True
  if type(s[0]) is not np.complex128:
    is_complex = False
    s = s.real

  # Take the fourier transform of the signal and perform FFT Shift
  S = np.fft.fftshift(np.fft.fft(s, N) / N)

  # Time Domain Plot
  plt.figure(figsize=(12.95, 7.8), dpi=150)
  plt.subplot(211)
  plt.title(f"Time domain {N} samples " + title)
  t_us = np.arange(N) / fs / 1e-6
  if is_complex:
    plt.plot(t_us, s.real, 'k', label='I')
    plt.plot(t_us, s.imag, 'r', label='Q')
  else:
    plt.plot(t_us, s, 'k', label='s')
  plt.xlim(t_us[0], t_us[-1])
  plt.xlabel('Time (us)')
  plt.ylabel('Amplitude')

  # Frequency Domain Plot
  plt.subplot(212)
  #plt.title("Freq domain " + title)
  #f_mhz = (freq + (np.arange(0, fs, fs/N) - (fs/2) + (fs/N))) / 1e6
  #plt.plot(f_mhz, 20*np.log10(np.abs(S)))
  #plt.xlim(f_mhz[0], f_mhz[-1])
  #plt.xlim(0.1011, 0.1031)
  #plt.ylim(-100, 0)
  #plt.xlabel('Frequency (MHz)')
  #plt.ylabel('Amplitude (dBFS)')
  #plt.show()

  #plt.figure()
  #plt.title("PSD " + title)
  #plt.psd(s, NFFT=1024, Fs=fs, Fc=freq)
  #plt.show()
  plt.title("Spectrogram " + title)
  plt.specgram(s, NFFT=1024, Fs=fs, Fc=freq)

from numpy import cos, sin, pi, absolute, arange, array, zeros, max, abs, round, int16, exp, arctan2, diff, unwrap, imag, real, complex_
from scipy.signal import kaiserord, lfilter, firwin, freqz, decimate, resample_poly
from pylab import figure, clf, plot, xlabel, ylabel, xlim, ylim, title, grid, axes, show, subplot, tight_layout, legend
from os import path


sdr_fs_out = 250e3
print("sdr_fs_out",sdr_fs_out)
if sdr_fs_out==125e6:
  plot_signal(s, fs, freq, "125MSPS IQ")
  #plt.show()
  # Decimate by 500 to 250KSPS
  #sdecim = decimate(s, decim_fac, zero_phase=True)
  #sdecim = decimate(s, 5, zero_phase=True)
  #sdecim = decimate(sdecim, 10, zero_phase=True)
  #sdecim = decimate(sdecim, 10, zero_phase=True)
  sdecim = resample_poly(s, 1, 5)
  sdecim = resample_poly(sdecim, 1, 10)
  sdecim = resample_poly(sdecim, 1, 10)
  decim_fac = 5*10*10
  fs_decim = fs / decim_fac # 250e3
elif sdr_fs_out==250e3:
  sdecim = s # Already decimated
  decim_fac = 5*10*10
  fs_decim = fs / decim_fac # 250e3
elif sdr_fs_out==1.25e6:
  sdecim = s # Already decimated
  decim_fac = 10*10
  fs_decim = fs / decim_fac
N_decim = len(sdecim)
plot_signal(sdecim, fs_decim, freq, f"{fs_decim/1e3}KSPS IQ")
#plt.show()

# Try to demod fm
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

# demod_test matching what hardware implemented
def imul16(a,b):
    # doing output scaling here doesnt help
    result = (np.int32(a) * np.int32(b)) >> 15
    if max(abs(result)) > (1<<15):
       raise Exception("overflow")
    return np.int16(result)

def f2i(x):
    if max(abs(x)) > 1.0:
       raise Exception("overflow")
    return np.int16(x * ((1<<15)-1))

def i2f(x):
    if max(abs(x)) > (1<<15):
       raise Exception("overflow")
    return np.float32(x / ((1<<15)-1))

def demod_test(samples, df):
    use_in_scale = False
    if use_in_scale:
      in_scale_f = 2.0 #2.0 for 0db gain 32.0 #4.0 # 8.0 just starts to clip with AGC on
      print(f"demod_test in {in_scale_f} scale")
      samples *= in_scale_f #Scaley?
    
    samples_i16_I = f2i(samples.real)
    samples_i16_Q = f2i(samples.imag)

    #i_dot = samples_i16_I[:-2] - samples_i16_I[2:]
    #q_dot = samples_i16_Q[:-2] - samples_i16_Q[2:]
    # INVERTED sounds same/think just flips output sign+-
    # i16 data
    i_dot = samples_i16_I[2:] - samples_i16_I[:-2]
    q_dot = samples_i16_Q[2:] - samples_i16_Q[:-2]
    # imul16 does mult and fixed point >>15 adjust
    demod = imul16(samples_i16_I[1:-1], q_dot) - imul16(samples_i16_Q[1:-1], i_dot)
    
    #demod_scaled = (np.int32(samples_i16_I[1:-1]) * np.int32(q_dot)) - (np.int32(samples_i16_Q[1:-1]) * np.int32(i_dot))
    #demod = demod_scaled >> (15-2) # scale by 4


    pre_out = i2f(demod)

    use_out_scale = False
    if use_out_scale:
      #FM_DEV_HZ=150e3
      #SAMPLE_RATE_HZ=250e3
      #df = FM_DEV_HZ/SAMPLE_RATE_HZ
      #scale_factor_f = 1.0 / (2.0 * 3.14 * df)#; // 1/(2 pi df)
      scale_factor_f = 4 #8 # 16.0 just starts to clip
      print("demod_test out scale_factor_f",scale_factor_f)
      scaled_out = pre_out * scale_factor_f
    else:
      scaled_out = pre_out  

    return scaled_out

# Demod
#use_demod_test = False
#print("use_demod_test",use_demod_test)
freq_deviation = 150e3 # +- 75Khz says internet, = 150e3
df = freq_deviation/fs_decim # df Deviation(Hz) / SampleRate(Hz)
fc = 0.0 # baseband IQ
#if use_demod_test:
demod_test_fm_raw = demod_test(sdecim, df)
#else:
py_fm_raw = fm_demod(sdecim, df, fc)
# fm_demod uses diff differentiation which has delay of 1 sample
# Preprend a zero to still have [0] sample alignment in time
# Still wanted/needed?
#fm_raw = array(([0] + list(fm_raw)))

# Plot 250KSPS raw FM
plot_signal(demod_test_fm_raw, fs_decim, 0.0, f"demod_test {fs_decim/1e3}KSPS Raw demodulated")
plot_signal(py_fm_raw, fs_decim, 0.0, f"numpy {fs_decim/1e3}KSPS Raw demodulated")
#plt.show()

if fs_decim!=250e3:
   print("Not writing audio")
   plt.show()
   sys.exit(0)

# Resample to 48KHz with 24/125
mono_demod_test = resample_poly(demod_test_fm_raw, 24, 125)
mono_py = resample_poly(py_fm_raw, 24, 125)
audio_fs = int(fs_decim * (24/125)) #48e3
from scipy.io.wavfile import write
#if use_demod_test:
write("demod_test_fm_radio_audio.wav", audio_fs, f2i(mono_demod_test))
#else:
write("scipynumpy_fm_radio_audio.wav", audio_fs, f2i(mono_py))
  
print("Plotting...")
plot_signal(mono_demod_test, audio_fs, 0.0, "demod_test 48KHz Audio")
plot_signal(mono_py, audio_fs, 0.0, "scipy 48KHz Audio")
plt.show()