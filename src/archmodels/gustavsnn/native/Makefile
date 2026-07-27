CXX      := g++
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra

SRCS := main.cpp
BIN  := gustavgen

.PHONY: all clean

all: $(BIN)

$(BIN): $(SRCS) GustavGen.h
	$(CXX) $(CXXFLAGS) -o $(BIN) $(SRCS)

clean:
	rm -f $(BIN)
