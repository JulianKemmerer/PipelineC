/*int FAKE_PRAGMA(char* s){
}*/

/*template<int c>
int add_const(int x) {
   return x + c;
}*/
//#pragma MY_PRAGMA arg0 arg1 etc
//int unused = FAKE_PRAGMA("MY_PRAGMA arg0 arg1 etc");
//int unused2 = FAKE_PRAGMA("TEST");
//#define MAIN_MHZ(main, mhz)\
//int unused = FAKE_PRAGMA(#main " " #mhz);

//MAIN_MHZ(main, 100.0)
//#pragma "MY_PRAGMA arg0 arg1 etc"

#pragma PART "xc7a100tcsg324-1"
#pragma MAIN main
typedef int uint1_t; // TEMP

uint1_t main(){
   return 1; //add_const<1>(x);
}

// clang -S -O0 -Xclang -disable-O0-optnone -fno-discard-value-names -emit-llvm test.cpp -o test.ll
/*typedef struct my_struct_t{
   int my_field;
}my_struct_t;

//int some_global;

my_struct_t test(my_struct_t s, my_struct_t x){
    my_struct_t rv;
    if(s.my_field){
        rv = s;
    }else{
        rv = x;
    }
    return rv;
}*/

/*template<int x, int y>
void DoSomething() {

// consume x, y as constants

}*/

/*
int add_1(int x) {
   return x + 1;
}
*/
/*int[2] make_2(int x) {
   int rv[2];
   rv[0] = x;
   rv[1] = x;
   return rv;
}*/

/*(int x, int y, int z) make_xyz(int a){
   x = a;
   y = a;
   z = a;
}*/

/*
_Pragma("MAIN_MHZ main 100.0");

int main(int x){
   //return add_const<1>(x);
   return add_1(x);
   //int two[2] = make_2(x);
   //return two[0]+two[1];
   int a,b,c;
   a,b,c = make_xyz(x);
   //DoSomething<0,1>();
   //DoSomething<640,480>();
}
*/
