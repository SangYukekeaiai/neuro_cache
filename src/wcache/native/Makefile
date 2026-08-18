# wcache native build, plan Part 3.4.
#
# Two build modes, kept in separate object directories so one never picks up
# the other's objects:
#
#   make            fixture build, -O0 -g, asserts LIVE
#   make test       build and run every tests/test_*.cpp, one binary each,
#                   then the compile-fail driver
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

# One binary per tests/test_*.cpp, each with its own main(), rather than one
# binary linking every test file. Two reasons, both learned rather than
# preferred: a unit's tests stay separable (a fake or a helper written for A2a
# cannot leak into A1's binary and change what A1 is testing), and a link error
# in one unit's file does not stop the others from building and running, which
# is what would otherwise hide a passing suite behind an unrelated breakage.
#
# The wildcard is tests/test_*.cpp, not tests/*.cpp, so a future non-test .cpp
# under tests/ is not silently turned into a binary that is expected to have a
# main().
TEST_SRCS := $(wildcard tests/test_*.cpp)
TEST_BINS := $(patsubst tests/%.cpp,$(BUILDDIR)/%,$(TEST_SRCS))
# Headers under tests/ are listed explicitly. Each test binary is compiled and
# linked in one command, so it carries no -MMD dependency file of its own, and
# without this a change to tests/check.h left `make test` running the previous
# binary and reporting a pass. Verified: a deliberate #error in check.h still
# printed "125 checks, 0 failures" and exited 0. Headers under include/ need no
# entry here, since the library objects depend on them through -MMD and the
# test relinks whenever $(LIB) is newer.
TEST_HDRS := $(wildcard tests/*.h)
# Library headers are listed too. The note above says they need no entry
# because the test relinks whenever $(LIB) is newer, but that only holds once
# src/ has a .cpp: while the units are header-only, $(OBJS) is empty, $(LIB)
# never changes, and a mutated include/wcache/*.h left the previous binary in
# place. Verified: mutating operator<= in types.h still printed "161 checks,
# 0 failures" until this line existed.
#
# Both lines were re-verified empirically after the split to one binary per
# file (A2a), because the split rewrote the rule that carries them and the
# failure they prevent is silent. What was actually run, not inspected:
#
#   types.h,  operator<= changed to <          -> 2 binaries recompiled, red
#   layout.h, Placement's two fields swapped   -> 2 binaries recompiled, red
#   tests/check.h, a deliberate #error         -> red
#   all three reverted                         -> green, with no `make clean`
#
# Note that BOTH binaries rebuild on any library header, not only the one that
# includes it. That is the wildcard being coarse rather than a dependency being
# tracked, and it is the safe direction: every unit is header-only today, so
# $(OBJS) is still empty and $(LIB) still never changes, and these two lines
# are the only thing connecting a header to a test binary at all.
LIB_HDRS  := $(wildcard include/wcache/*.h)

.PHONY: all lib test test-run test-compile-fail release clean

all: lib

lib: $(LIB)

# The tests are meant to run in the fixture build, where the asserts are live.
# `make MODE=release test` compiles and passes, but it is then testing less
# than it looks like it is, so it warns.
#
# Every binary runs even after one of them fails, and the failing exit status
# is carried to the end. That is check.h's rule ("every failure prints and the
# run continues") applied one level up: stopping at the first red binary would
# report one unit's breakage and hide the rest.
# Shared by `test` and `test-run` so the two cannot drift apart.
RUN_BINS = rc=0; for b in $(TEST_BINS); do \
	    echo "===== $$b"; \
	    $$b || rc=1; \
	done; exit $$rc

# The prerequisite is $(TEST_BINS) rather than the two phony targets, and the
# recipe runs the compile-fail driver and the binaries in that order. Under
# `make -j` two phony prerequisites would run CONCURRENTLY and their output
# would interleave, which costs the gate the property that makes it readable:
# each suite's count sitting under its own name. Compilation of the binaries is
# still parallel, which is where the -j win actually is.
test: $(TEST_BINS)
ifeq ($(MODE),release)
	@echo "warning: MODE=release compiles the asserts out, so the internal"
	@echo "         invariants are not being exercised."
endif
	@tests/compile_fail.sh
	@$(RUN_BINS)

# The C++ suites only, without the compile-fail driver. `make test` is still
# both, and the gate is still `make test`.
#
# This exists for mutation_check.sh, which uses it for a mutation to a .cpp.
# compile_fail.sh compiles every case with -fsyntax-only against include/ and
# never links the library, so no mutation inside src/*.cpp can change a single
# one of its verdicts. Verified rather than argued: swapping locate's set index
# and tag in src/block_pack.cpp leaves compile_fail.sh at 188 cases, 0 failures
# while turning `make test` red. Running the 188-case pass for those mutations
# is 188 g++ spawns that cannot report anything, and it was the dominant cost
# of every .cpp case in the sweep.
#
# Header mutations still run the full `make test`, because those cases DO
# compile against the headers and are usually the only thing that catches them.
test-run: $(TEST_BINS)
	@$(RUN_BINS)

# The negative half of A1's exit criterion (N12) and of A2a's (an abstract
# class stays abstract, an override may not drop its const). A case that must
# not compile cannot live in a test binary, so it is a separate driver. Its own
# control cases guard against a vacuous pass.
test-compile-fail:
	@tests/compile_fail.sh

# The stem is `test_%` rather than `%` on purpose: a bare $(BUILDDIR)/% pattern
# would also match $(BUILDDIR)/libwcache.a and every $(BUILDDIR)/*.o, and make
# would then have two candidate rules for objects whose source moved or was
# deleted. Nothing the library builds is named test_*.
$(BUILDDIR)/test_%: tests/test_%.cpp $(TEST_HDRS) $(LIB_HDRS) $(LIB) | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) -Itests $< $(LIB) -o $@

# Re-enters make so the release objects land in build/release and the
# fixture objects are left untouched.
release:
	$(MAKE) MODE=release lib

# Order-only on $(BUILDDIR) because until the first src/*.cpp lands (A2) the
# header-only units leave $(OBJS) empty, and nothing else creates the directory.
$(LIB): $(OBJS) | $(BUILDDIR)
	$(AR) rcs $@ $^

$(BUILDDIR)/%.o: src/%.cpp | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

clean:
	rm -rf build

-include $(DEPS)
