# wcache native build, plan Part 3.4.
#
# Two build modes, kept in separate object directories so one never picks up
# the other's objects:
#
#   make            fixture build, -O0 -g, asserts LIVE
#   make test       build and run the fixture tests
#   make release    sweep build,   -O2 -DNDEBUG, asserts compiled out
#   make clean      remove build/
#
# The warning set is pinned here rather than remembered on a hand-typed g++
# line. -Wsign-conversion in particular is what surfaced the unsigned
# flattening in line_of, so it is not optional.
#
# CXX is assigned, not defaulted. With `?=` it deferred to the environment,
# where it resolves to `CC`: on a Delta compute node that is a Cray wrapper
# whose defaults differ from the g++ line every verification run used. Pinning
# the warnings while leaving the compiler floating pins nothing.

CXX      := g++

CXXSTD   := -std=c++17
WARN     := -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow
INCLUDES := -Iinclude

MODE     ?= fixture
ifeq ($(MODE),release)
  MODEFLAGS := -O2 -DNDEBUG
else ifeq ($(MODE),fixture)
  MODEFLAGS := -O0 -g
else
  $(error MODE must be fixture or release, got '$(MODE)')
endif

BUILDDIR := build/$(MODE)
CXXFLAGS := $(CXXSTD) $(WARN) $(INCLUDES) $(MODEFLAGS)

SRCS := $(wildcard src/*.cpp)
OBJS := $(patsubst src/%.cpp,$(BUILDDIR)/%.o,$(SRCS))
DEPS := $(OBJS:.o=.d)
LIB  := $(BUILDDIR)/libwcache.a

TEST_SRCS := $(wildcard tests/*.cpp)
# Headers under tests/ are listed explicitly. The test binary is compiled and
# linked in one command, so it carries no -MMD dependency file of its own, and
# without this a change to tests/check.h left `make test` running the previous
# binary and reporting a pass. Verified: a deliberate #error in check.h still
# printed "125 checks, 0 failures" and exited 0. Headers under include/ need no
# entry here, since the library objects depend on them through -MMD and the
# test relinks whenever $(LIB) is newer.
TEST_HDRS := $(wildcard tests/*.h)
TEST_BIN  := $(BUILDDIR)/wcache_tests

.PHONY: all lib test release clean

all: lib

lib: $(LIB)

# The tests are meant to run in the fixture build, where the asserts in
# line_of are live. `make MODE=release test` compiles and passes, but it is
# then testing less than it looks like it is, so it warns.
test: $(TEST_BIN)
ifeq ($(MODE),release)
	@echo "warning: MODE=release compiles the asserts out, so the range"
	@echo "         preconditions in line_of are not being exercised."
endif
	$(TEST_BIN)

$(TEST_BIN): $(TEST_SRCS) $(TEST_HDRS) $(LIB) | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) -Itests $(TEST_SRCS) $(LIB) -o $@

# Re-enters make so the release objects land in build/release and the
# fixture objects are left untouched.
release:
	$(MAKE) MODE=release lib

$(LIB): $(OBJS)
	$(AR) rcs $@ $^

$(BUILDDIR)/%.o: src/%.cpp | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

clean:
	rm -rf build

-include $(DEPS)
