CXX      := g++
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra

SRCS := main.cpp
BIN  := eventsim

.PHONY: all clean

all: $(BIN)

$(BIN): $(SRCS) Transaction.h NoC.h EventSim.h
	$(CXX) $(CXXFLAGS) -o $(BIN) $(SRCS)

clean:
	rm -f $(BIN)
