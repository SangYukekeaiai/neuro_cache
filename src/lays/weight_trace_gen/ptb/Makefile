CXX      := g++
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra

SRCS := main.cpp
BIN  := ptbgen

.PHONY: all clean

all: $(BIN)

$(BIN): $(SRCS) PTBGen.h ../tick_output.h
	$(CXX) $(CXXFLAGS) -o $(BIN) $(SRCS)

clean:
	rm -f $(BIN)
