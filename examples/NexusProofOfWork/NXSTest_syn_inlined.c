#include "uintN_t.h"
#include "arrays.h"

#define ROTL64(x, y) rotl64_##y(x) // PipelineC built in bit manip

#define SKEIN_KS_PARITY     0x5555555555555555ULL

#define RotateSkeinKey(h) \
{ \
  uint64_t RotateSkeinKey_tmp = h[0]; \
  uint32_t RotateSkeinKey_i; \
  for(RotateSkeinKey_i = 0; RotateSkeinKey_i < 16; RotateSkeinKey_i+=1) h[RotateSkeinKey_i] = h[RotateSkeinKey_i + 1]; \
  h[16] = RotateSkeinKey_tmp; \
}

#define SkeinInjectKey(p, h, t, s) \
{ \
  uint32_t SkeinInjectKey_i; \
  for(SkeinInjectKey_i = 0; SkeinInjectKey_i < 16; SkeinInjectKey_i+=1) p[SkeinInjectKey_i] += h[SkeinInjectKey_i]; \
  p[13] += t[s % 3]; \
  p[14] += t[(s + 1) % 3]; \
  p[15] += s; \
}

#define SkeinMix8(pv0, pv1, RC0, RC1, RC2, RC3, RC4, RC5, RC6, RC7) \
{ \
  uint64_t SkeinMix8_Temp[8]; \
   \
  uint32_t SkeinMix8_i; \
  for(SkeinMix8_i = 0; SkeinMix8_i < 8; SkeinMix8_i+=1) pv0[SkeinMix8_i] += pv1[SkeinMix8_i]; \
   \
  pv1[0] = ROTL64(pv1[0], RC0); \
  pv1[1] = ROTL64(pv1[1], RC1); \
  pv1[2] = ROTL64(pv1[2], RC2); \
  pv1[3] = ROTL64(pv1[3], RC3); \
  pv1[4] = ROTL64(pv1[4], RC4); \
  pv1[5] = ROTL64(pv1[5], RC5); \
  pv1[6] = ROTL64(pv1[6], RC6); \
  pv1[7] = ROTL64(pv1[7], RC7); \
   \
  for(SkeinMix8_i = 0; SkeinMix8_i < 8; SkeinMix8_i+=1) pv1[SkeinMix8_i] ^= pv0[SkeinMix8_i]; \
   \
  ARRAY_COPY(SkeinMix8_Temp, pv0, 8) /*memcpy(Temp, pv0, 64);*/ \
   \
  pv0[0] = SkeinMix8_Temp[0]; \
  pv0[1] = SkeinMix8_Temp[1]; \
  pv0[2] = SkeinMix8_Temp[3]; \
  pv0[3] = SkeinMix8_Temp[2]; \
  pv0[4] = SkeinMix8_Temp[5]; \
  pv0[5] = SkeinMix8_Temp[6]; \
  pv0[6] = SkeinMix8_Temp[7]; \
  pv0[7] = SkeinMix8_Temp[4]; \
   \
  ARRAY_COPY(SkeinMix8_Temp, pv1, 8) /*memcpy(Temp, pv1, 64);*/  \
  \
  pv1[0] = SkeinMix8_Temp[4]; \
  pv1[1] = SkeinMix8_Temp[6]; \
  pv1[2] = SkeinMix8_Temp[5]; \
  pv1[3] = SkeinMix8_Temp[7]; \
  pv1[4] = SkeinMix8_Temp[3]; \
  pv1[5] = SkeinMix8_Temp[1]; \
  pv1[6] = SkeinMix8_Temp[2]; \
  pv1[7] = SkeinMix8_Temp[0]; \
}

#define SkeinEvenRound(p) \
{ \
  uint64_t SkeinEvenRound_pv0[8]; \
  uint64_t SkeinEvenRound_pv1[8]; \
  uint32_t SkeinEvenRound_i; \
  for(SkeinEvenRound_i = 0; SkeinEvenRound_i < 16; SkeinEvenRound_i+=1) \
  { \
    if(SkeinEvenRound_i & 1) SkeinEvenRound_pv1[SkeinEvenRound_i >> 1] = p[SkeinEvenRound_i]; \
    else SkeinEvenRound_pv0[SkeinEvenRound_i >> 1] = p[SkeinEvenRound_i]; \
  } \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 55, 43, 37, 40, 16, 22, 38, 12) \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 25, 25, 46, 13, 14, 13, 52, 57) \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 33, 8, 18, 57, 21, 12, 32, 54) \
 \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 34, 43, 25, 60, 44, 9, 59, 34) \
   \
  for(SkeinEvenRound_i = 0; SkeinEvenRound_i < 16; SkeinEvenRound_i+=1) \
  { \
    if(SkeinEvenRound_i & 1) p[SkeinEvenRound_i] = SkeinEvenRound_pv1[SkeinEvenRound_i >> 1]; \
    else p[SkeinEvenRound_i] = SkeinEvenRound_pv0[SkeinEvenRound_i >> 1]; \
  } \
}

#define SkeinOddRound(p) \
{ \
  uint64_t SkeinOddRound_pv0[8]; \
  uint64_t SkeinOddRound_pv1[8]; \
  uint32_t SkeinOddRound_i; \
  for(SkeinOddRound_i = 0; SkeinOddRound_i < 16; SkeinOddRound_i+=1) \
  { \
    if(SkeinOddRound_i & 1) SkeinOddRound_pv1[SkeinOddRound_i >> 1] = p[SkeinOddRound_i]; \
    else SkeinOddRound_pv0[SkeinOddRound_i >> 1] = p[SkeinOddRound_i]; \
  } \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 28, 7, 47, 48, 51, 9, 35, 41) \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 17, 6, 18, 25, 43, 42, 40, 15) \
 \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 58, 7, 32, 45, 19, 18, 2, 56) \
   \
  SkeinMix8(SkeinEvenRound_pv0, SkeinEvenRound_pv1, 47, 49, 27, 58, 37, 48, 53, 56) \
   \
  for(SkeinOddRound_i = 0; SkeinOddRound_i < 16; SkeinOddRound_i+=1) \
  { \
    if(SkeinOddRound_i & 1) p[SkeinOddRound_i] = SkeinOddRound_pv1[SkeinOddRound_i >> 1]; \
    else p[SkeinOddRound_i] = SkeinOddRound_pv0[SkeinOddRound_i >> 1]; \
  } \
}

#define SkeinRoundTest(State, Key, T0, T1, T2) \
{ \
  uint64_t SkeinRoundTest_T[3]; \
  SkeinRoundTest_T[0] = T0; \
  SkeinRoundTest_T[1] = T1; \
  SkeinRoundTest_T[2] = T2; \
  \
  uint32_t SkeinRoundTest_i; \
  for(SkeinRoundTest_i = 0; SkeinRoundTest_i < 20; SkeinRoundTest_i += 2)\
  {\
    SkeinInjectKey(State, Key, SkeinRoundTest_T, SkeinRoundTest_i) \
    \
    /*printf("\nState after key injection %d:\n", i);*/ \
    \
    SkeinEvenRound(State) \
    RotateSkeinKey(Key) \
    \
    /*printf("\nState after round %d:\n", i);*/ \
    \
    /*printf("\nKey after rotation:\n");*/ \
    \
    SkeinInjectKey(State, Key, SkeinRoundTest_T, (SkeinRoundTest_i + 1)) \
    \
    /*printf("\nState after key injection %d:\n", i + 1);*/ \
    \
    SkeinOddRound(State) \
    RotateSkeinKey(Key) \
    \
    /*printf("\nState after round %d:\n", i + 1);*/ \
    \
    /*printf("\nKey after rotation:\n");*/ \
  } \
  \
  SkeinInjectKey(State, Key, SkeinRoundTest_T, 20) \
  \
  /*for(int i = 0; i < 16; ++i) State[i] ^= StateBak[i];*/ \
  \
  /* I am cheap and dirty. x.x */ \
  RotateSkeinKey(Key) \
  RotateSkeinKey(Key) \
  RotateSkeinKey(Key) \
  RotateSkeinKey(Key) \
  RotateSkeinKey(Key) \
}

#define keccakf(st) \
{ \
    uint64_t keccakf_rnd_consts[24]; \
    keccakf_rnd_consts[ 0 ]= 0x0000000000000001ULL ; \
    keccakf_rnd_consts[ 1 ]= 0x0000000000008082ULL ; \
    keccakf_rnd_consts[ 2 ]= 0x800000000000808AULL ; \
    keccakf_rnd_consts[ 3 ]= 0x8000000080008000ULL ; \
    keccakf_rnd_consts[ 4 ]= 0x000000000000808BULL ; \
    keccakf_rnd_consts[ 5 ]= 0x0000000080000001ULL ; \
    keccakf_rnd_consts[ 6 ]= 0x8000000080008081ULL ; \
    keccakf_rnd_consts[ 7 ]= 0x8000000000008009ULL ; \
    keccakf_rnd_consts[ 8 ]= 0x000000000000008AULL ; \
    keccakf_rnd_consts[ 9 ]= 0x0000000000000088ULL ; \
    keccakf_rnd_consts[ 10 ]= 0x0000000080008009ULL ; \
    keccakf_rnd_consts[ 11 ]= 0x000000008000000AULL ; \
    keccakf_rnd_consts[ 12 ]= 0x000000008000808BULL ; \
    keccakf_rnd_consts[ 13 ]= 0x800000000000008BULL ; \
    keccakf_rnd_consts[ 14 ]= 0x8000000000008089ULL ; \
    keccakf_rnd_consts[ 15 ]= 0x8000000000008003ULL ; \
    keccakf_rnd_consts[ 16 ]= 0x8000000000008002ULL ; \
    keccakf_rnd_consts[ 17 ]= 0x8000000000000080ULL ; \
    keccakf_rnd_consts[ 18 ]= 0x000000000000800AULL ; \
    keccakf_rnd_consts[ 19 ]= 0x800000008000000AULL ; \
    keccakf_rnd_consts[ 20 ]= 0x8000000080008081ULL ; \
    keccakf_rnd_consts[ 21 ]= 0x8000000000008080ULL ; \
    keccakf_rnd_consts[ 22 ]= 0x0000000080000001ULL ; \
    keccakf_rnd_consts[ 23 ]= 0x8000000080008008ULL ; \
    \
    uint32_t keccakf_i; \
    for(keccakf_i = 0; keccakf_i < 24; keccakf_i+=1)  \
    { \
      uint64_t keccakf_bc[5]; \
      uint64_t keccakf_tmp; \
       \
      keccakf_bc[0] = st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24] ^ ROTL64(st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21], 1);  \
      keccakf_bc[1] = st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20] ^ ROTL64(st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22], 1);  \
      keccakf_bc[2] = st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21] ^ ROTL64(st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23], 1);  \
      keccakf_bc[3] = st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22] ^ ROTL64(st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24], 1);  \
      keccakf_bc[4] = st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23] ^ ROTL64(st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20], 1);  \
      st[0] ^= keccakf_bc[0];  \
       \
      keccakf_tmp = ROTL64(st[ 1] ^ keccakf_bc[1], 1);  \
      st[ 1] = ROTL64(st[ 6] ^ keccakf_bc[1], 44);  \
      st[ 6] = ROTL64(st[ 9] ^ keccakf_bc[4], 20);  \
      st[ 9] = ROTL64(st[22] ^ keccakf_bc[2], 61);  \
      st[22] = ROTL64(st[14] ^ keccakf_bc[4], 39);  \
      st[14] = ROTL64(st[20] ^ keccakf_bc[0], 18);  \
      st[20] = ROTL64(st[ 2] ^ keccakf_bc[2], 62);  \
      st[ 2] = ROTL64(st[12] ^ keccakf_bc[2], 43); \
      st[12] = ROTL64(st[13] ^ keccakf_bc[3], 25); \
      st[13] = ROTL64(st[19] ^ keccakf_bc[4],  8); \
      st[19] = ROTL64(st[23] ^ keccakf_bc[3], 56); \
      st[23] = ROTL64(st[15] ^ keccakf_bc[0], 41); \
      st[15] = ROTL64(st[ 4] ^ keccakf_bc[4], 27); \
      st[ 4] = ROTL64(st[24] ^ keccakf_bc[4], 14); \
      st[24] = ROTL64(st[21] ^ keccakf_bc[1],  2); \
      st[21] = ROTL64(st[ 8] ^ keccakf_bc[3], 55); \
      st[ 8] = ROTL64(st[16] ^ keccakf_bc[1], 45); \
      st[16] = ROTL64(st[ 5] ^ keccakf_bc[0], 36); \
      st[ 5] = ROTL64(st[ 3] ^ keccakf_bc[3], 28); \
      st[ 3] = ROTL64(st[18] ^ keccakf_bc[3], 21); \
      st[18] = ROTL64(st[17] ^ keccakf_bc[2], 15); \
      st[17] = ROTL64(st[11] ^ keccakf_bc[1], 10); \
      st[11] = ROTL64(st[ 7] ^ keccakf_bc[2],  6); \
      st[ 7] = ROTL64(st[10] ^ keccakf_bc[0],  3); \
      st[10] = keccakf_tmp;  \
       \
      keccakf_bc[0] = st[ 0]; keccakf_bc[1] = st[ 1]; st[ 0] ^= (~keccakf_bc[1]) & st[ 2]; st[ 1] ^= (~st[ 2]) & st[ 3]; st[ 2] ^= (~st[ 3]) & st[ 4]; st[ 3] ^= (~st[ 4]) & keccakf_bc[0]; st[ 4] ^= (~keccakf_bc[0]) & keccakf_bc[1];  \
      keccakf_bc[0] = st[ 5]; keccakf_bc[1] = st[ 6]; st[ 5] ^= (~keccakf_bc[1]) & st[ 7]; st[ 6] ^= (~st[ 7]) & st[ 8]; st[ 7] ^= (~st[ 8]) & st[ 9]; st[ 8] ^= (~st[ 9]) & keccakf_bc[0]; st[ 9] ^= (~keccakf_bc[0]) & keccakf_bc[1]; \
      keccakf_bc[0] = st[10]; keccakf_bc[1] = st[11]; st[10] ^= (~keccakf_bc[1]) & st[12]; st[11] ^= (~st[12]) & st[13]; st[12] ^= (~st[13]) & st[14]; st[13] ^= (~st[14]) & keccakf_bc[0]; st[14] ^= (~keccakf_bc[0]) & keccakf_bc[1]; \
      keccakf_bc[0] = st[15]; keccakf_bc[1] = st[16]; st[15] ^= (~keccakf_bc[1]) & st[17]; st[16] ^= (~st[17]) & st[18]; st[17] ^= (~st[18]) & st[19]; st[18] ^= (~st[19]) & keccakf_bc[0]; st[19] ^= (~keccakf_bc[0]) & keccakf_bc[1]; \
      keccakf_bc[0] = st[20]; keccakf_bc[1] = st[21]; st[20] ^= (~keccakf_bc[1]) & st[22]; st[21] ^= (~st[22]) & st[23]; st[22] ^= (~st[23]) & st[24]; st[23] ^= (~st[24]) & keccakf_bc[0]; st[24] ^= (~keccakf_bc[0]) & keccakf_bc[1]; \
       \
      st[0] ^= keccakf_rnd_consts[keccakf_i]; \
      \
      /*printf("\nState after round %d:\n", keccakf_i);*/ \
       \
    }\
}

#pragma MAIN_MHZ DoNXSTest 850.0 // Timing goal
// Two input port u64 arrays, and one u64 output
uint64_t DoNXSTest(uint64_t State[26], uint64_t Key[17])
{
  uint64_t Nonce = 0x00000001FCAFC045ULL;
  uint64_t P[16];
  
  // loads low 8 qwords
  //memcpy(P, State + 16, 64);
  uint32_t i;
  for(i = 0; i < 8; i+=1) P[i] = State[i+2];
  
  P[8] = State[24];
	P[9] = State[25];
	P[10] = Nonce;
  
  for(i = 11; i < 16; i+=1) P[i] = 0ULL;
  
  // T constants inside func
  SkeinRoundTest(P, Key, 0xD8ULL, 0xB000000000000000ULL, 0xB0000000000000D8ULL)
  
  for(i = 0; i < 8; i+=1) Key[i] = P[i] ^ State[16 + i];
  
  Key[8] = P[8] ^ State[24];
	Key[9] = P[9] ^ State[25];
	Key[10] = P[10] ^ Nonce;
	
	for(i = 11; i < 16; i+=1) Key[i] = P[i];
  
  // Clear P, the state argument to the final block is zero.
	//memset(P, 0x00, 128);
  ARRAY_SET(P, 0x00, 16)
  Key[16] = SKEIN_KS_PARITY;
  for(i = 0; i < 16; i+=1) Key[16] ^= Key[i];

  // T constants inside func
  SkeinRoundTest(P, Key, 0x08ULL, 0xFF00000000000000ULL, 0xFF00000000000008ULL)

  uint64_t KeccakState[25];
  // memset(KeccakState, 0x00, 200);
  ARRAY_SET(KeccakState, 0x00, 25)
  // Copying qwords 0 - 8 (inclusive, so 9 qwords).
  // Note this is technically an XOR operation, just
  // with zero in this instance.
  // memcpy(KeccakState, P, 72);
  ARRAY_COPY(KeccakState, P, 9) 
  
  keccakf(KeccakState)
  
  for(i = 0; i < 7; i+=1) KeccakState[i] ^= P[i + 9];

  KeccakState[7] ^= 0x0000000000000005ULL;
  KeccakState[8] ^= 0x8000000000000000ULL;
  
  keccakf(KeccakState)
  
  keccakf(KeccakState)
  
  return(KeccakState[6]);
}
