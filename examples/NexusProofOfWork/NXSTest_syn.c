#include "uintN_t.h"
#include "arrays.h"

//#define ROTL64(x, y)      (((x) << (y)) | ((x) >> (64 - (y))))
#define ROTL64(x, y) rotl64_##y(x) // PipelineC built in bit manip

#define SKEIN_KS_PARITY     0x5555555555555555ULL

/*
uint64_t keccakf_rnd_consts[24] = 
{
    0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808AULL,
    0x8000000080008000ULL, 0x000000000000808BULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008AULL,
    0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000AULL,
    0x000000008000808BULL, 0x800000000000008BULL, 0x8000000000008089ULL,
    0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL, 
    0x000000000000800AULL, 0x800000008000000AULL, 0x8000000080008081ULL,
    0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL
};
*/

// Make a macro to inline?
typedef struct RotateSkeinKey_t
{
  uint64_t h[17];
}RotateSkeinKey_t;
RotateSkeinKey_t RotateSkeinKey(uint64_t h[17])
{
  uint64_t tmp = h[0];
  uint32_t i;
  for(i = 0; i < 16; i+=1) h[i] = h[i + 1];

  h[16] = tmp;
  RotateSkeinKey_t rv;
  rv.h = h;
  return rv;
}

//void SkeinInjectKey(uint64_t *p, const uint64_t *h, const uint64_t *t, int s)
#define SkeinInjectKey(p, h, t, s) \
{ \
  uint32_t SkeinInjectKey_i; \
  for(SkeinInjectKey_i = 0; SkeinInjectKey_i < 16; SkeinInjectKey_i+=1) p[SkeinInjectKey_i] += h[SkeinInjectKey_i]; \
  p[13] += t[s % 3]; \
  p[14] += t[(s + 1) % 3]; \
  p[15] += s; \
}

typedef struct SkeinMix8_t
{
  uint64_t pv0[8];
  uint64_t pv1[8];
}SkeinMix8_t;
#define SkeinMix8WConsts(SkeinMix8Name, RC0, RC1, RC2, RC3, RC4, RC5, RC6, RC7) \
SkeinMix8_t SkeinMix8Name(uint64_t pv0[8], uint64_t pv1[8]) \
{ \
  uint64_t Temp[8]; \
   \
  uint32_t i; \
  for(i = 0; i < 8; i+=1) pv0[i] += pv1[i]; \
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
  for(i = 0; i < 8; i+=1) pv1[i] ^= pv0[i]; \
   \
  ARRAY_COPY(Temp, pv0, 8) /*memcpy(Temp, pv0, 64);*/ \
   \
  pv0[0] = Temp[0]; \
  pv0[1] = Temp[1]; \
  pv0[2] = Temp[3]; \
  pv0[3] = Temp[2]; \
  pv0[4] = Temp[5]; \
  pv0[5] = Temp[6]; \
  pv0[6] = Temp[7]; \
  pv0[7] = Temp[4]; \
   \
  ARRAY_COPY(Temp, pv1, 8) /*memcpy(Temp, pv1, 64);*/  \
  \
  pv1[0] = Temp[4]; \
  pv1[1] = Temp[6]; \
  pv1[2] = Temp[5]; \
  pv1[3] = Temp[7]; \
  pv1[4] = Temp[3]; \
  pv1[5] = Temp[1]; \
  pv1[6] = Temp[2]; \
  pv1[7] = Temp[0]; \
  \
  SkeinMix8_t rv; \
  rv.pv0 = pv0; \
  rv.pv1 = pv1; \
  return rv; \
}
SkeinMix8WConsts(SkeinMix8Even0, 55, 43, 37, 40, 16, 22, 38, 12)
SkeinMix8WConsts(SkeinMix8Even1, 25, 25, 46, 13, 14, 13, 52, 57)
SkeinMix8WConsts(SkeinMix8Even2, 33, 8, 18, 57, 21, 12, 32, 54)
SkeinMix8WConsts(SkeinMix8Even3, 34, 43, 25, 60, 44, 9, 59, 34)
//
SkeinMix8WConsts(SkeinMix8Odd0, 28, 7, 47, 48, 51, 9, 35, 41)
SkeinMix8WConsts(SkeinMix8Odd1, 17, 6, 18, 25, 43, 42, 40, 15)
SkeinMix8WConsts(SkeinMix8Odd2, 58, 7, 32, 45, 19, 18, 2, 56)
SkeinMix8WConsts(SkeinMix8Odd3, 47, 49, 27, 58, 37, 48, 53, 56)

typedef struct State_t
{
  uint64_t State[16];
}State_t;
State_t SkeinEvenRound(uint64_t p[16])
{
  uint64_t pv0[8];
  uint64_t pv1[8];
  uint32_t i;
  for(i = 0; i < 16; i+=1)
  {
    if(i & 1) pv1[i >> 1] = p[i];
    else pv0[i >> 1] = p[i];
  }
  
  SkeinMix8_t sm8 = SkeinMix8Even0(pv0, pv1); // Consts in func
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  sm8 = SkeinMix8Even1(pv0, pv1); // Consts in func
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  sm8 = SkeinMix8Even2(pv0, pv1); // Consts in func
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  sm8 = SkeinMix8Even3(pv0, pv1); // Consts in func
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  for(i = 0; i < 16; i+=1)
  {
    if(i & 1) p[i] = pv1[i >> 1];
    else p[i] = pv0[i >> 1];
  }
  
  State_t rv;
  rv.State = p;
  return rv;
}

State_t SkeinOddRound(uint64_t p[16])
{
  uint64_t pv0[8];
  uint64_t pv1[8];
  uint32_t i;
  for(i = 0; i < 16; i+=1)
  {
    if(i & 1) pv1[i >> 1] = p[i];
    else pv0[i >> 1] = p[i];
  }
  
  SkeinMix8_t sm8 = SkeinMix8Odd0(pv0, pv1); // Consts in func
  pv0 = sm8.pv0;
  pv1 = sm8.pv1; 
  
  sm8 = SkeinMix8Odd1(pv0, pv1); // Consts in func 
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;

  sm8 = SkeinMix8Odd2(pv0, pv1); // Consts in func 
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  sm8 = SkeinMix8Odd3(pv0, pv1); // Consts in func 
  pv0 = sm8.pv0;
  pv1 = sm8.pv1;
  
  for(i = 0; i < 16; i+=1)
  {
    if(i & 1) p[i] = pv1[i >> 1];
    else p[i] = pv0[i >> 1];
  }
  
  State_t rv;
  rv.State = p;
  return rv;
}

// MAKE Skein innner loop its own func?

typedef struct SkeinRoundTest_t{
  uint64_t State[16];
  uint64_t Key[17];
}SkeinRoundTest_t;
#define SkeinRoundTestWType(SkeinRoundTestName, T0, T1, T2) \
SkeinRoundTest_t SkeinRoundTestName(uint64_t State[16], uint64_t Key[17])\
{ \
  uint64_t T[3]; \
  T[0] = T0; \
  T[1] = T1; \
  T[2] = T2; \
  \
  uint32_t i; \
  for(i = 0; i < 20; i += 2)\
  {\
    SkeinInjectKey(State, Key, T, i) \
    \
    /*printf("\nState after key injection %d:\n", i);*/ \
    \
    State_t sre = SkeinEvenRound(State); \
    State = sre.State; \
    RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
    Key = rsk.h; \
    \
    /*printf("\nState after round %d:\n", i);*/ \
    \
    /*printf("\nKey after rotation:\n");*/ \
    \
    SkeinInjectKey(State, Key, T, (i + 1)) \
    \
    /*printf("\nState after key injection %d:\n", i + 1);*/ \
    \
    State_t sor = SkeinOddRound(State); \
    State = sor.State; \
    RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
    Key = rsk.h; \
    \
    /*printf("\nState after round %d:\n", i + 1);*/ \
    \
    /*printf("\nKey after rotation:\n");*/ \
  } \
  \
  SkeinInjectKey(State, Key, T, 20) \
  \
  /*for(int i = 0; i < 16; ++i) State[i] ^= StateBak[i];*/ \
  \
  /* I am cheap and dirty. x.x */ \
  RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
  Key = rsk.h; \
  RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
  Key = rsk.h; \
  RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
  Key = rsk.h; \
  RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
  Key = rsk.h; \
  RotateSkeinKey_t rsk = RotateSkeinKey(Key); \
  Key = rsk.h; \
  \
  SkeinRoundTest_t rv; \
  rv.State = State; \
  rv.Key = Key; \
  return rv; \
}
SkeinRoundTestWType(SkeinRoundTest0, 0xD8ULL, 0xB000000000000000ULL, 0xB0000000000000D8ULL)
SkeinRoundTestWType(SkeinRoundTest1, 0x08ULL, 0xFF00000000000000ULL, 0xFF00000000000008ULL)

typedef struct keccackf_t{
  uint64_t st[25];
}keccackf_t;
#define DEF_KECCAKF_ITER(i) \
keccackf_t keccakf_iter_##i(uint64_t st[25]) /*uint64_t KeccakState[25]*/ \
{ \
      uint64_t bc[5]; \
      uint64_t tmp; \
       \
      bc[0] = st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24] ^ ROTL64(st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21], 1);  \
      bc[1] = st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20] ^ ROTL64(st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22], 1);  \
      bc[2] = st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21] ^ ROTL64(st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23], 1);  \
      bc[3] = st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22] ^ ROTL64(st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24], 1);  \
      bc[4] = st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23] ^ ROTL64(st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20], 1);  \
      st[0] ^= bc[0];  \
       \
      tmp = ROTL64(st[ 1] ^ bc[1], 1);  \
      st[ 1] = ROTL64(st[ 6] ^ bc[1], 44);  \
      st[ 6] = ROTL64(st[ 9] ^ bc[4], 20);  \
      st[ 9] = ROTL64(st[22] ^ bc[2], 61);  \
      st[22] = ROTL64(st[14] ^ bc[4], 39);  \
      st[14] = ROTL64(st[20] ^ bc[0], 18);  \
      st[20] = ROTL64(st[ 2] ^ bc[2], 62);  \
      st[ 2] = ROTL64(st[12] ^ bc[2], 43); \
      st[12] = ROTL64(st[13] ^ bc[3], 25); \
      st[13] = ROTL64(st[19] ^ bc[4],  8); \
      st[19] = ROTL64(st[23] ^ bc[3], 56); \
      st[23] = ROTL64(st[15] ^ bc[0], 41); \
      st[15] = ROTL64(st[ 4] ^ bc[4], 27); \
      st[ 4] = ROTL64(st[24] ^ bc[4], 14); \
      st[24] = ROTL64(st[21] ^ bc[1],  2); \
      st[21] = ROTL64(st[ 8] ^ bc[3], 55); \
      st[ 8] = ROTL64(st[16] ^ bc[1], 45); \
      st[16] = ROTL64(st[ 5] ^ bc[0], 36); \
      st[ 5] = ROTL64(st[ 3] ^ bc[3], 28); \
      st[ 3] = ROTL64(st[18] ^ bc[3], 21); \
      st[18] = ROTL64(st[17] ^ bc[2], 15); \
      st[17] = ROTL64(st[11] ^ bc[1], 10); \
      st[11] = ROTL64(st[ 7] ^ bc[2],  6); \
      st[ 7] = ROTL64(st[10] ^ bc[0],  3); \
      st[10] = tmp;  \
       \
      bc[0] = st[ 0]; bc[1] = st[ 1]; st[ 0] ^= (~bc[1]) & st[ 2]; st[ 1] ^= (~st[ 2]) & st[ 3]; st[ 2] ^= (~st[ 3]) & st[ 4]; st[ 3] ^= (~st[ 4]) & bc[0]; st[ 4] ^= (~bc[0]) & bc[1];  \
      bc[0] = st[ 5]; bc[1] = st[ 6]; st[ 5] ^= (~bc[1]) & st[ 7]; st[ 6] ^= (~st[ 7]) & st[ 8]; st[ 7] ^= (~st[ 8]) & st[ 9]; st[ 8] ^= (~st[ 9]) & bc[0]; st[ 9] ^= (~bc[0]) & bc[1]; \
      bc[0] = st[10]; bc[1] = st[11]; st[10] ^= (~bc[1]) & st[12]; st[11] ^= (~st[12]) & st[13]; st[12] ^= (~st[13]) & st[14]; st[13] ^= (~st[14]) & bc[0]; st[14] ^= (~bc[0]) & bc[1]; \
      bc[0] = st[15]; bc[1] = st[16]; st[15] ^= (~bc[1]) & st[17]; st[16] ^= (~st[17]) & st[18]; st[17] ^= (~st[18]) & st[19]; st[18] ^= (~st[19]) & bc[0]; st[19] ^= (~bc[0]) & bc[1]; \
      bc[0] = st[20]; bc[1] = st[21]; st[20] ^= (~bc[1]) & st[22]; st[21] ^= (~st[22]) & st[23]; st[22] ^= (~st[23]) & st[24]; st[23] ^= (~st[24]) & bc[0]; st[24] ^= (~bc[0]) & bc[1]; \
       \
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
      st[0] ^= keccakf_rnd_consts[i]; \
      \
      /*printf("\nState after round %d:\n", i);*/ \
       \
    keccackf_t rv; \
    rv.st = st; \
    return rv; \
}
DEF_KECCAKF_ITER(0)
DEF_KECCAKF_ITER(1)
DEF_KECCAKF_ITER(2)
DEF_KECCAKF_ITER(3)
DEF_KECCAKF_ITER(4)
DEF_KECCAKF_ITER(5)
DEF_KECCAKF_ITER(6)
DEF_KECCAKF_ITER(7)
DEF_KECCAKF_ITER(8)
DEF_KECCAKF_ITER(9)
DEF_KECCAKF_ITER(10)
DEF_KECCAKF_ITER(11)
DEF_KECCAKF_ITER(12)
DEF_KECCAKF_ITER(13)
DEF_KECCAKF_ITER(14)
DEF_KECCAKF_ITER(15)
DEF_KECCAKF_ITER(16)
DEF_KECCAKF_ITER(17)
DEF_KECCAKF_ITER(18)
DEF_KECCAKF_ITER(19)
DEF_KECCAKF_ITER(20)
DEF_KECCAKF_ITER(21)
DEF_KECCAKF_ITER(22)
DEF_KECCAKF_ITER(23)
#define KECCAKF_ITER(st, i) keccakf_iter_##i(st)

// TODO undo _iter and make one big func again?
keccackf_t keccakf(uint64_t st[25]) //uint64_t KeccakState[25]
{
    //uint32_t i;
    //for(i = 0; i < 24; i+=1) 
    //{
      //keccackf_t iter = keccakf_iter(st, keccakf_rnd_consts[i]);
      keccackf_t iter = KECCAKF_ITER(st, 0);
      st = iter.st;
      iter = KECCAKF_ITER(st, 1);
      st = iter.st;
      iter = KECCAKF_ITER(st, 2);
      st = iter.st;
      iter = KECCAKF_ITER(st, 3);
      st = iter.st;
      iter = KECCAKF_ITER(st, 4);
      st = iter.st;
      iter = KECCAKF_ITER(st, 5);
      st = iter.st;
      iter = KECCAKF_ITER(st, 6);
      st = iter.st;
      iter = KECCAKF_ITER(st, 7);
      st = iter.st;
      iter = KECCAKF_ITER(st, 8);
      st = iter.st;
      iter = KECCAKF_ITER(st, 9);
      st = iter.st;
      iter = KECCAKF_ITER(st, 10);
      st = iter.st;
      iter = KECCAKF_ITER(st, 11);
      st = iter.st;
      iter = KECCAKF_ITER(st, 12);
      st = iter.st;
      iter = KECCAKF_ITER(st, 13);
      st = iter.st;
      iter = KECCAKF_ITER(st, 14);
      st = iter.st;
      iter = KECCAKF_ITER(st, 15);
      st = iter.st;
      iter = KECCAKF_ITER(st, 16);
      st = iter.st;
      iter = KECCAKF_ITER(st, 17);
      st = iter.st;
      iter = KECCAKF_ITER(st, 18);
      st = iter.st;
      iter = KECCAKF_ITER(st, 19);
      st = iter.st;
      iter = KECCAKF_ITER(st, 20);
      st = iter.st;
      iter = KECCAKF_ITER(st, 21);
      st = iter.st;
      iter = KECCAKF_ITER(st, 22);
      st = iter.st;
      iter = KECCAKF_ITER(st, 23);
      st = iter.st;
    //}
    keccackf_t rv;
    rv.st = st;
    return rv;
}

#pragma MAIN_MHZ DoNXSTest 845.0 // Timing goal
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
  SkeinRoundTest_t srt = SkeinRoundTest0(P, Key); 
  P = srt.State;
  Key = srt.Key;
  
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
  SkeinRoundTest_t srt = SkeinRoundTest1(P, Key);
  P = srt.State;
  Key = srt.Key;

  uint64_t KeccakState[25];
  // memset(KeccakState, 0x00, 200);
  ARRAY_SET(KeccakState, 0x00, 25)
  // Copying qwords 0 - 8 (inclusive, so 9 qwords).
  // Note this is technically an XOR operation, just
  // with zero in this instance.
  // memcpy(KeccakState, P, 72);
  ARRAY_COPY(KeccakState, P, 9) 
  
  keccackf_t k = keccakf(KeccakState);
  KeccakState = k.st;
  
  for(i = 0; i < 7; i+=1) KeccakState[i] ^= P[i + 9];

  KeccakState[7] ^= 0x0000000000000005ULL;
  KeccakState[8] ^= 0x8000000000000000ULL;
  
  k = keccakf(KeccakState);
  KeccakState = k.st;

  k = keccakf(KeccakState);
  KeccakState = k.st;
  
  return(KeccakState[6]);
}
