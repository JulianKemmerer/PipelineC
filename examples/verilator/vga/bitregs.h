static inline uint32_t float_31_0(float a) { union _noname { float f; uint32_t i;} conv; conv.f = a; return conv.i; }
static inline float float_uint32(uint32_t a) { union _noname { float f; uint32_t i;} conv; conv.i = a; return conv.f; }

#ifndef __BITREGS_H_
#define __BITREGS_H_
//based on https://blog.codef00.com/2014/12/06/portable-bitfields-using-c11/
//License: "Feel free to use it for any purpose you like"

#include <cstdint>
#include <cstddef>
#include <type_traits>

template <size_t LastBit>
struct MinimumTypeHelper {
    typedef
        typename std::conditional<LastBit == 0 , void,
        typename std::conditional<LastBit <= 8 , uint8_t,
        typename std::conditional<LastBit <= 16, uint16_t,
        typename std::conditional<LastBit <= 32, uint32_t,
        typename std::conditional<LastBit <= 64, uint64_t,
        void>::type>::type>::type>::type>::type type;
};

#if 0
//fast version: native types, doesn't enforce bit sizes
#define DEFUINT(N) typedef MinimumTypeHelper<N>::type uint##N##_t
#define XYZbit(a, X, Y, Z) (((a)>>(Z)) & ((1<<((Y)-(Z)+1))-1))
#else


template <size_t Bits>
class BitField {
    typedef typename MinimumTypeHelper<Bits>::type T;

public:
    BitField() : value_(0) { }
    BitField(T value) : value_(value) { }
    template <class T2> BitField &operator=(T2 value) { value_ = value; return *this; }
    operator T() const { return value_; }
    operator bool() const { return value_; }
    BitField &operator++() { return *this = *this+1; }
    T operator++(int) { T r = *this; ++*this; return r; }
    BitField &operator--() { return *this = *this-1; }
    T operator--(int) { T r = *this; --*this; return r; }

    template <size_t START, size_t END> BitField<START-END+1> slice() const { return value_>>END; } 
    T operator()(size_t Y, size_t Z) const { return (((value_)>>(Z)) & ((1<<((Y)-(Z)+1))-1)); } 

private:
    union { T rawvalue; struct {T value_ :Bits;};};
};

#define DEFUINT(N) typedef BitField<N> uint##N##_t
#define XYZbit(a,X,Y,Z) BitField<(X)>(a).slice<(Y),(Z)>()

#endif


             DEFUINT( 1); DEFUINT( 2); DEFUINT( 3); DEFUINT( 4); DEFUINT( 5); DEFUINT( 6); DEFUINT( 7);              DEFUINT( 9);
DEFUINT(10); DEFUINT(11); DEFUINT(12); DEFUINT(13); DEFUINT(14); DEFUINT(15);              DEFUINT(17); DEFUINT(18); DEFUINT(19);
DEFUINT(20); DEFUINT(21); DEFUINT(22); DEFUINT(23); DEFUINT(24); DEFUINT(25); DEFUINT(26); DEFUINT(27); DEFUINT(28); DEFUINT(29);
DEFUINT(30); DEFUINT(31);              DEFUINT(33); DEFUINT(34); DEFUINT(35); DEFUINT(36); DEFUINT(37); DEFUINT(38); DEFUINT(39);
DEFUINT(40); DEFUINT(41); DEFUINT(42); DEFUINT(43); DEFUINT(44); DEFUINT(45); DEFUINT(46); DEFUINT(47); DEFUINT(48); DEFUINT(49);
DEFUINT(50); DEFUINT(51); DEFUINT(52); DEFUINT(53); DEFUINT(54); DEFUINT(55); DEFUINT(56); DEFUINT(57); DEFUINT(58); DEFUINT(59);
DEFUINT(60); DEFUINT(61); DEFUINT(62); DEFUINT(63);


//some bit access shortcuts
/*#define uint12_5_2(a) XYZbit(a, 12, 5, 2)
#define uint12_5_2(a) XYZbit(a, 12, 5, 2)
#define uint12_8_8(a) XYZbit(a, 12, 8, 8)
#define uint12_7_7(a) XYZbit(a, 12, 7, 7)
#define uint12_3_3(a) XYZbit(a, 12, 3, 3)
#define uint12_6_6(a) XYZbit(a, 12, 6, 6)*/

#endif // __BITREGS_H_
