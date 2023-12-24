# `The Design`:
```
Radio tuned center on FM station -> IQ from radio -> 
FIR w/ decim by D: ~300KHz band-> ~300KSPS IQ ->
  In this case D is large and needs to be broken into stages:
    D = d0 * d1 * d2 etc 
FM DEMOD differentiator -> ~300KSPS 16b Raw FM signal (has mono+stereo+etc)
FIR w/ decim by (N/M): 15KHz band low pass for mono audio 
  Interpolate by N w/ FIR
  Decim by M w/ FIR
  -> 48KSPS 16b audio samples (noisey)
FM deemphasis (flatten noise) -> 48KSPS 16b audio samples .wav file
```

# `Future Radio Platform`:
IQ from radio 125MSPS
125MSPS decim by D=500 = 250KSPS (~300KSPS requirement)
  FIR transition width ~= 1/3 of band
  Stopband + transition width should all fall WITHIN the Nyquist freq
  fs = 125e6
  for d in [5,10,10]:
    bw_in = fs/2
    fs_out = fs/d
    bw_out = fs_out/2
    tw = bw_out/3
    pass_width = bw_out-tw
    stop = bw_out
    print(fs,"Hz decim by",d)
    print("pass",0,"Hz->",pass_width,"Hz","tw",tw)
    print("stop",stop,"Hz->",bw_in,"Hz")
    fs = fs_out
250KSPS upsample by N=24 = 6MSPS
then downsample by M=125 = 48KSPS


# `Simulation`:

IIRC there was a `--sim --cocotb --ghdl` based approach

Do we want to setup some way of injecting a signal into that sim? ex. some script to gen input samples as C array, run sim, and some script to parse the output of sim (which you already have something like I think)


# `Hardware Test`:

Hear audio? :)
