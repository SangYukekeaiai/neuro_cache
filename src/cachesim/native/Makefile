# cachesim native build, plan Part 3.4.
#
# Two build modes, kept in separate object directories so one never picks up
# the other's objects:
#
#   make            fixture build, -O0 -g, asserts LIVE
#   make test       build and run every tests/test_*.cpp, one binary each,
#                   then the compile-fail driver
#   make test-cli   build apps/ and run the four end-to-end CLI scripts,
#                   including v1_pipe.sh, the V1 gate. Needs python3 and the
#                   checked-in examples/ fixtures, so it is NOT part of `test`
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

SRCS := $(sort $(shell find src -type f -name '*.cpp' -print))
OBJS := $(patsubst src/%.cpp,$(BUILDDIR)/%.o,$(SRCS))
DEPS := $(OBJS:.o=.d)
LIB  := $(BUILDDIR)/libcachesim.a

# One binary per tests/test_*.cpp, each with its own main(), rather than one
# binary linking every test file. Two reasons, both learned rather than
# preferred: a unit's tests stay separable (a fake or a helper written for A2a
# cannot leak into A1's binary and change what A1 is testing), and a link error
# in one unit's file does not stop the others from building and running, which
# is what would otherwise hide a passing suite behind an unrelated breakage.
#
# The source set is tests/test_*.cpp, not tests/*.cpp, so a future non-test .cpp
# under tests/ is not silently turned into a binary that is expected to have a
# main().
TEST_SRCS := $(sort $(shell find tests -type f -name 'test_*.cpp' -print))
TEST_BINS := $(patsubst tests/%.cpp,$(BUILDDIR)/%,$(TEST_SRCS))
# TEST_HDRS is explicit because each test binary is compiled and linked in one
# command, so it has no -MMD dependency file of its own. Without this
# prerequisite, changing tests/check.h can leave `make test` running the old
# binary and reporting a pass.
TEST_HDRS := $(sort $(shell find tests -type f -name '*.h' -print))
LIB_HDRS  := $(sort $(shell find include/cachesim -type f -name '*.h' -print))

# The programs. They live under apps/ and NOT under src/, because $(SRCS) is
# collected recursively under src/: a main() there would be archived into
# libcachesim.a
# and collide with every test binary's own main().
#
# Named one by one rather than derived from a broad pattern rule. That pattern
# would also match $(BUILDDIR)/libcachesim.a and every $(BUILDDIR)/*.o, and it
# would give make two candidate rules for an object whose source moved. A
# second program is one more line here.
APP_BINS := $(BUILDDIR)/cachesim_run $(BUILDDIR)/cachesim_sweep

.PHONY: all lib apps test test-cli test-run test-compile-fail release clean

all: lib apps

apps: $(APP_BINS)

# No -Itests: a program is not a test and must not reach into the test headers.
# apps/cli_args.h, oracle_io.h and output.h are what the two programs share; they
# are reached by quoted includes from the sources' own directory.
APP_HDRS := $(sort $(shell find apps -type f -name '*.h' -print))

$(BUILDDIR)/cachesim_run: apps/cachesim_run.cpp $(APP_HDRS) $(LIB_HDRS) $(LIB) | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) $< $(LIB) -o $@

$(BUILDDIR)/cachesim_sweep: apps/cachesim_sweep.cpp $(APP_HDRS) $(LIB_HDRS) $(LIB) | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) $< $(LIB) -o $@

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
	@rc=0; ( $(RUN_BINS) ) || rc=$$?; \
	  echo "note: the end-to-end CLI gate (invariant V1) is a separate target:"; \
	  echo "      make test-cli   [needs python3 and the examples/ fixtures]"; \
	  exit $$rc

# The four end-to-end CLI scripts, which drive the built programs over a
# checked-in fixture slice. v1_pipe.sh is invariant V1's gate, and it is
# non-vacuous: it also points the same check at two deliberately broken runs and
# requires it to go red.
#
# This is a SEPARATE target and deliberately not a prerequisite of `test`.
# `test` compiles and runs C++ only, so it is green wherever a compiler is, and
# that is the property worth keeping: these four scripts need python3 on PATH,
# an importable `cachesim.stream`, and the checked-in examples/ fixtures, none of which
# `test` needs today. Folding them in would trade a gate that always runs for a
# gate that runs where the environment happens to suit it, and a V1 check that
# is skipped on a bare machine is worse than one that is named and run. It also
# builds apps/, which `test` does not (see mutation_check.sh on that gap).
#
# PYTHON overrides the interpreter, as in the scripts themselves.
test-cli: apps
	@tests/run_cli.sh
	@tests/sweep_cli.sh
	@tests/v1_pipe.sh
	@tests/cout_golden.sh

# The C++ suites only, without the compile-fail driver. `make test` is still
# both, and the gate is still `make test`.
#
# This exists for mutation_check.sh, which uses it for a mutation to a .cpp.
# compile_fail.sh compiles every case with -fsyntax-only against include/ and
# never links the library, so no mutation inside src/*.cpp can change a single
# one of its verdicts. Verified rather than argued: swapping locate's set index
# and tag in src/layout/block_pack.cpp leaves compile_fail.sh at 316 cases, 0 failures
# while turning `make test` red. Running the 316-case pass for those mutations
# is 316 g++ spawns that cannot report anything, and it was the dominant cost
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


$(TEST_BINS): $(TEST_HDRS) $(LIB_HDRS) $(LIB)

$(TEST_BINS): $(BUILDDIR)/%: tests/%.cpp
	mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -Itests $< $(LIB) -o $@

# Re-enters make so the release objects land in build/release and the
# fixture objects are left untouched.
release:
	$(MAKE) MODE=release lib

$(LIB): $(OBJS) | $(BUILDDIR)
	$(AR) rcs $@ $^

$(BUILDDIR)/%.o: src/%.cpp | $(BUILDDIR)
	mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

clean:
	rm -rf build

-include $(DEPS)
