CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall

cache_replay: main.cpp config.h dims.h layout.h policy.h cache.h
	$(CXX) $(CXXFLAGS) -o cache_replay main.cpp

clean:
	rm -f cache_replay

.PHONY: clean
