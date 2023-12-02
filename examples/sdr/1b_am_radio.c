// Trying to copy:
// https://github.com/alberto-grl/1bitSDR/blob/master/impl1/source/top.v

// Running at 'osc_clk' = 83MHz
#pragma MAIN_MHZ top 83.0

typedef struct SinCos_t{
  uint13_t Sine;
  uint13_t Cosine;
}SinCos_t;
SinCos_t SinCos(uint8_t Theta){
  // TODO Just a lookup table?
  // WTF Verilog is 1000 lines of structural code gen?
}

typedef struct nco_sig_t{
  uint1_t sin_out;
  uint1_t cos_out;
  uint64_t phase_accum;
}nco_sig_t;
nco_sig_t nco_sig(uint64_t phase_inc_carr){
  //TODO
}

typedef struct Mixer_t{
  uint1_t RFOut;
  int12_t MixerOutSin;
  int12_t MixerOutCos;
}Mixer_t;
Mixer_t Mixer(
 int12_t sin_in,
 int12_t cos_in,
 uint1_t RFIn
){
  //TODO
}

typedef struct CIC_t{
  int12_t d_out;
  uint1_t d_clk;
}CIC_t;
// #(.width(72), .decimation_ratio(4096))
CIC_t CIC(uint8_t gain, int12_t d_in){
  //TODO
}

typedef struct AMDemodulator_t{
  uint12_t d_out;
}AMDemodulator_t;
AMDemodulator_t AMDemodulator(
  int12_t I_in,
  int12_t Q_in
){
  //TODO
}

typedef struct PWM_t{
  uint1_t PWMOut;
}PWM_t;
PWM_t PWM(
  uint12_t DataIn
){
}


typedef struct outputs_t {
  uint1_t DiffOut;
  uint1_t PWMOut;
  //uint1_t sinGen;
  //uint1_t sin_out;
  //uint1_t CIC_out_clkSin;
}outputs_t;
outputs_t top(uint1_t RFIn)
{
  outputs_t o;

  SinCos_t SinCos1 = SinCos(
    phase_accum(63,56)
  );
  uint13_t LOSine = SinCos1.Sine;
  uint13_t LOCosine = SinCos1.Cosine;

  nco_sig_t ncoGen = nco_sig(
    phase_inc_carrGen1
  );
  uint64_t phase_accum = ncoGen.phase_accum;
  uint1_t sinGen = ncoGen.sin_out; 
  uint1_t cosGen = ncoGen.cos_out;

  Mixer_t Mixer1 = Mixer(
    LOSine(12,1),
    LOCosine(12,1),
    RFIn
  );
  uint1_t DiffOut = Mixer1.RFOut;
  int12_t MixerOutSin = Mixer1.MixerOutSin;
  int12_t MixerOutCos = Mixer1.MixerOutCos;

  CIC_t CIC1Sin = CIC(
    CICGain,
    MixerOutSin
  );
  int12_t CIC1_outSin = CIC1Sin.d_out;
  uint1_t CIC1_out_clkSin = CIC1Sin.d_clk;
  
  CIC_t CIC1Cos = CIC( 
    CICGain,
    MixerOutCos
  );
  int12_t CIC1_outCos = CIC1Cos.d_out;
  uint1_t CIC1_out_clkCos = CIC1Cos.d_clk;

  // Doesnt use osc_clk ? clk=CIC1_out_clkSin instead?
  AMDemodulator_t AMDemodulator1 = AMDemodulator(
    CIC1_outSin,
    CIC1_outCos
  );
  uint12_t DemodOut = AMDemodulator1.d_out;

  PWM_t PWM1 = PWM(
    DemodOut
  );
  uint1_t PWMOut = PWM1.PWMOut;

  o.DiffOut = DiffOut;
  o.PWMOut = PWMOut;
  return o;
}
