CXX      := g++
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra

SRCS := main.cpp
BIN  := loasgen

.PHONY: all clean

all: $(BIN)

$(BIN): $(SRCS) LoASGen.h
	$(CXX) $(CXXFLAGS) -o $(BIN) $(SRCS)

clean:
	rm -f $(BIN)
