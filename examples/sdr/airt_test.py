# Tune radio to FM station, receive audio samples

import numpy as np
from matplotlib import pyplot as plt
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CS16 
import sys

# Fixed hardware info
AUDIO_SAMPLE_RATE_HZ = 48000
fs = 125e6              # Fixed for FPGA dev kit, Radio sample Rate
rx_bits = 16            # The AIR-T's ADC is 16 bits
rx_chan = 0             # Only first RX channel has FM radio, RX1 = 0, RX2 = 1

############################################################################################
# Settings
############################################################################################
# Data transfer settings
freq = 93.3e6  # FM station, LO tuning frequency in Hz 
audio_seconds = 10
N = int(audio_seconds * AUDIO_SAMPLE_RATE_HZ) # Number of i16 audio samples per read
use_agc = False         # Use or don't use the AGC
timeout_us = int((audio_seconds+3) * 1e6) 

############################################################################################
# Receive Signal
############################################################################################
#  Initialize the AIR-T receiver using SoapyAIRT
print(f"Init radio chan={rx_chan} freq MHz={freq/1e6} use_agc={use_agc}...")
sdr = SoapySDR.Device(dict(driver="SoapyAIRT"))       # Create AIR-T instance
sdr.setSampleRate(SOAPY_SDR_RX, rx_chan, fs)          # Set sample rate
sdr.setGainMode(SOAPY_SDR_RX, rx_chan, use_agc)       # Set the gain mode
if not use_agc:
	sdr.setGain(SOAPY_SDR_RX, rx_chan, 0.0)
sdr.setFrequency(SOAPY_SDR_RX, rx_chan, freq)         # Tune the LO

# Create data buffer and start streaming samples to it
print("Setup stream...")
rx_buff = np.empty(N, np.int16)                 # Create memory buffer for data stream
rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CS16, [rx_chan])  # Setup data stream
print("Activate stream...")
sdr.activateStream(rx_stream)  # this turns the radio on

# Read the samples from the data buffer
print("Read stream...")
sr = sdr.readStream(rx_stream, [rx_buff], int(N/2), timeoutUs=timeout_us)
rc = sr.ret # number of samples read or the error code
assert rc == int(N/2), 'Error Reading Samples from Device (error code = %d)!' % rc

# Stop streaming
print("Stopping...")
sdr.deactivateStream(rx_stream)
sdr.closeStream(rx_stream)

############################################################################################
# Plot Signal
############################################################################################
# Write to 16-bit PCM, Mono.
from scipy.io.wavfile import write
write("fm_radio_audio.wav", AUDIO_SAMPLE_RATE_HZ, rx_buff)
print("Plotting...")
# Convert shorts (received signal) to floats [-1, 1]
s0 = rx_buff.astype(float) / np.power(2.0, rx_bits-1)
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
  plt.title("PSD " + title)
  plt.psd(s, NFFT=1024, Fs=fs, Fc=freq)
  #plt.show()
plot_signal(s0, AUDIO_SAMPLE_RATE_HZ, 0.0, "48KHz Audio")
plt.show()

