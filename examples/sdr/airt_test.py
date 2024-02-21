# Tune radio to FM station, receive audio samples

import numpy as np
from matplotlib import pyplot as plt
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_S16 

# Fixed hardware info
AUDIO_SAMPLE_RATE_HZ = 48000
fs = 125e6              # Fixed for FPGA dev kit, Radio sample Rate
rx_bits = 16            # The AIR-T's ADC is 16 bits
rx_chan = 0             # Only first RX channel has FM radio, RX1 = 0, RX2 = 1

############################################################################################
# Settings
############################################################################################
# Data transfer settings
freq = 102.1e6          # FM station, LO tuning frequency in Hz
audio_seconds = 5
N = int(audio_seconds * AUDIO_SAMPLE_RATE_HZ) # Number of i16 audio samples per read
use_agc = False         # Use or don't use the AGC
timeout_us = int(audio_seconds * 1e6) * 2

############################################################################################
# Receive Signal
############################################################################################
#  Initialize the AIR-T receiver using SoapyAIRT
sdr = SoapySDR.Device(dict(driver="SoapyAIRT"))       # Create AIR-T instance
sdr.setSampleRate(SOAPY_SDR_RX, rx_chan, fs)          # Set sample rate
sdr.setGainMode(SOAPY_SDR_RX, rx_chan, use_agc)       # Set the gain mode
sdr.setFrequency(SOAPY_SDR_RX, rx_chan, freq)         # Tune the LO

# Create data buffer and start streaming samples to it
rx_buff = np.empty(N, np.int16)                 # Create memory buffer for data stream
rx_stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_S16, [rx_chan])  # Setup data stream
sdr.activateStream(rx_stream)  # this turns the radio on

# Read the samples from the data buffer
sr = sdr.readStream(rx_stream, [rx_buff], N, timeoutUs=timeout_us)
rc = sr.ret # number of samples read or the error code
assert rc == N, 'Error Reading Samples from Device (error code = %d)!' % rc

# Stop streaming
sdr.deactivateStream(rx_stream)
sdr.closeStream(rx_stream)

############################################################################################
# Plot Signal
############################################################################################
# Convert shorts (received signal) to floats [-1, 1]
#s0 = rx_buff.astype(float) / np.power(2.0, rx_bits-1)
# Write to 16-bit PCM, Mono.
from scipy.io.wavfile import write
write("fm_radio_audio.wav", AUDIO_SAMPLE_RATE_HZ, rx_buff)