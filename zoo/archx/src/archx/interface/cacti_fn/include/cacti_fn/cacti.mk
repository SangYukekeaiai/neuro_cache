TARGET = cacti
SHELL = /bin/sh
.PHONY: all depend clean
.SUFFIXES: .cc .o

ifndef NTHREADS
  NTHREADS = 1
endif


LIBS = 
INCS = -lm

# x86-only (-msse2/-mfpmath=sse) and gcc-only (-gstabs+) flags are gated on a
# compiler target so translated x86_64 shells can build for arm64.
COMPILER_TARGET := $(shell $(CXX) -dumpmachine)
ifneq (,$(findstring x86_64,$(COMPILER_TARGET)))
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
  OPT = -O3 $(ARCH_OPT) -DNTHREADS=$(NTHREADS)
endif

#CXXFLAGS = -Wall -Wno-unknown-pragmas -Winline $(DBG) $(OPT) 
CXXFLAGS = -Wno-unknown-pragmas $(DBG) $(OPT) 
CXX = g++
CC  = gcc

SRCS  = xmlParser.cc area.cc bank.cc mat.cc main.cc Ucache.cc io.cc technology.cc basic_circuit.cc parameter.cc \
		decoder.cc component.cc uca.cc subarray.cc wire.cc htree2.cc \
		cacti_interface.cc router.cc nuca.cc crossbar.cc arbiter.cc 

OBJS = $(patsubst %.cc,obj_$(TAG)/%.o,$(SRCS))
PYTHONLIB_SRCS = $(patsubst main.cc, ,$(SRCS)) obj_$(TAG)/cacti_wrap.cc
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

