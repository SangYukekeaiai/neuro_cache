CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall

all: cache_replay cache_replay_hierarchical cache_sweep_hierarchical

cache_replay: main.cpp config.h dims.h layout.h policy.h cache.h
	$(CXX) $(CXXFLAGS) -o cache_replay main.cpp

cache_replay_hierarchical: main_hierarchical.cpp config.h dims.h layout.h policy.h cache.h hierarchy.h
	$(CXX) $(CXXFLAGS) -o cache_replay_hierarchical main_hierarchical.cpp

cache_sweep_hierarchical: main_hierarchical_sweep.cpp config.h dims.h layout.h policy.h cache.h hierarchy.h
	$(CXX) $(CXXFLAGS) -o cache_sweep_hierarchical main_hierarchical_sweep.cpp

clean:
	rm -f cache_replay cache_replay_hierarchical cache_sweep_hierarchical

.PHONY: all clean
