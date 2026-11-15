TARGET = cacti
SHELL = /bin/sh
.PHONY: all depend clean
.SUFFIXES: .cc .o

ifndef NTHREADS
  NTHREADS = 8
endif


LIBS = 
INCS = -lm

# x86-only (-msse2/-mfpmath=sse) and gcc-only (-gstabs+) flags are gated on a
# real x86_64 host so the build also works on arm64 / clang (e.g. macOS).
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_M),x86_64)
  ARCH_OPT = -msse2 -mfpmath=sse
  DBG_FMT  = -gstabs+
else
  ARCH_OPT =
  DBG_FMT  =
endif

ifeq ($(TAG),dbg)
  DBG = -Wall
  OPT = -ggdb -g -O0 -DNTHREADS=1 $(DBG_FMT)
else
  DBG =
  OPT = -g $(ARCH_OPT) -DNTHREADS=$(NTHREADS)
endif

# -std=gnu++98: this CACTI vintage glues string literals to macros
# ("."VER_COMMENT_CACTI), which post-C++11 compilers reject.
#CXXFLAGS = -Wall -Wno-unknown-pragmas -Winline $(DBG) $(OPT)
CXXFLAGS = -std=gnu++98 -Wno-unknown-pragmas $(DBG) $(OPT)
CXX = g++ -m64
CC  = gcc -m64

archx.  = area.cc bank.cc mat.cc main.cc Ucache.cc io.cc technology.cc basic_circuit.cc parameter.cc \
		decoder.cc component.cc uca.cc subarray.cc wire.cc htree2.cc extio.cc extio_technology.cc \
		cacti_interface.cc router.cc nuca.cc crossbar.cc arbiter.cc powergating.cc TSV.cc memorybus.cc \
		memcad.cc memcad_parameters.cc
		

OBJS = $(patsubst %.cc,obj_$(TAG)/%.o,$(archx.))
PYTHONLIB_SRCS = $(patsubst main.cc, ,$(archx.)) obj_$(TAG)/cacti_wrap.cc
PYTHONLIB_OBJS = $(patsubst %.cc,%.o,$(PYTHONLIB_SRCS)) 
INCLUDES       = -I /usr/include/python2.4 -I /usr/lib/python2.4/config

all: obj_$(TAG)/$(TARGET)
	cp -f obj_$(TAG)/$(TARGET) $(TARGET)

obj_$(TAG)/$(TARGET) : $(OBJS)
	$(CXX) $(OBJS) -o $@ $(INCS) $(CXXFLAGS) $(LIBS) -pthread

#obj_$(TAG)/%.o : %.cc
#	$(CXX) -c $(CXXFLAGS) $(INCS) -o $@ $<

obj_$(TAG)/%.o : %.cc
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	-rm -f *.o _cacti.so cacti.py $(TARGET)


