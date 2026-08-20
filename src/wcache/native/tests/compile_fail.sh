#!/usr/bin/env bash
# The negative half of two units' exit criteria.
#
# A1: "any mix of the three time-like types fails to compile" (plan N12).
# A2a: AddressMapper is abstract and stays abstract, a subclass that leaves any
# one of the four pure virtuals unimplemented cannot be instantiated, and an
# override may not quietly change a signature (the const, the out parameter's
# reference, a return type).
#
# A test that must not compile cannot live in a file that must, so it lives
# here. Each case is compiled on its own and is expected to FAIL.
#
# The control cases at the end are not decoration. A typo in this script, a
# missing include, or a renamed type would make every MUST-FAIL case fail for
# the wrong reason and the script would report a clean pass while checking
# nothing. The controls are what make a vacuous pass impossible.

set -u
cd "$(dirname "$0")/.."

CXX=${CXX:-g++}
FLAGS="-std=c++17 -Iinclude -fsyntax-only"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

# Bounded parallelism. Every case is an independent g++ on its own translation
# unit with -fsyntax-only, so nothing is shared between them and they can run
# concurrently. Serially the suite is one g++ start-up after another, which is
# what made it the dominant cost of a mutation case: each mutation re-runs this
# whole file.
#
# Thirty-two, which is nproc here, and JOBS=n overrides it.
#
# The reason for the old default of eight was the NCSA Delta login node: a
# shared machine with a CPU-time cap per process, where grabbing every core was
# antisocial and a faster sweep was not a legal unfiltered one. That is not this
# machine, and B81 measured it: a standalone workstation, 32 cores, no
# scheduler, `ulimit -t` unlimited. There is no CPU cap for parallelism to fail
# to work around and no other user to be antisocial toward, so the default is
# now the fast answer rather than a policy inherited from a machine this work
# has never run on.
#
# `make -j` past 8 buys nothing, because `make test` serializes on this script,
# which takes its own JOBS. Measured at A4c/A5, with 214 compile cases, whole
# `make test` on a warm tree, three runs each:
#
#   JOBS=8    4.43  4.44  4.38 s        JOBS=32   2.39  2.16  2.26 s
#
# so 4.42 s becomes 2.27 s, a 49% cut, and it compounds across a mutation sweep
# where every case is a full `make test`. The verdicts are unchanged: the two
# settings produce byte-identical output, which the buffering below guarantees
# and which was checked with a diff rather than assumed.
JOBS=${JOBS:-32}

# Output is buffered per case and printed in SOURCE order at the end, never as
# the jobs finish. Two properties depend on this and both would be lost by
# letting the children write to the terminal: a diagnostic stays attached to
# the case that produced it rather than landing in the middle of another
# case's, and two runs of an unchanged tree print byte-identical output, which
# is what lets a diff of two runs be evidence.
#
# `seq_no` is the position in that order. Headers reserve one too, so a section
# cannot drift away from the cases under it.
seq_no=0

# section <text>: a header, reserving its place in the output stream.
section() {
    seq_no=$((seq_no + 1))
    printf '%s\n' "$1" > "$TMP/out.$seq_no"
}

# run_case <n> <expect> <name> <body> <extra>, run in the background.
run_case() {
    local n=$1 expect=$2 name=$3 body=$4 extra=$5
    local src="$TMP/case.$n.cpp" err="$TMP/err.$n"
    {
        echo '#include <wcache/types.h>'
        [ -n "$extra" ] && echo "$extra"
        echo '#include <cstdint>'
        echo 'using namespace wcache;'
        echo "$body"
    } > "$src"

    local got
    if $CXX $FLAGS "$src" 2>"$err"; then
        got=accept
    else
        got=reject
    fi

    if [ "$got" = "$expect" ]; then
        echo pass > "$TMP/v.$n"
        printf '  ok        %-46s (%s)\n' "$name" "$expect" > "$TMP/out.$n"
    else
        echo fail > "$TMP/v.$n"
        {
            printf '  FAIL      %-46s expected %s, got %s\n' "$name" "$expect" "$got"
            [ "$got" = reject ] && sed -n '1,4p' "$err" | sed 's/^/            /'
        } > "$TMP/out.$n"
    fi
}

# try <expect: reject|accept> <name> <body> [extra-include-line]
try() {
    seq_no=$((seq_no + 1))
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    run_case "$seq_no" "$1" "$2" "$3" "${4:-}" &
}

# tryL: the same, with layout.h in the preamble. A2a's cases need Placement and
# AddressMapper; A1's do not, and keeping the two preambles apart means an
# accidental dependency of types.h on layout.h shows up here rather than
# hiding behind a header everybody includes.
tryL() { try "$1" "$2" "$3" '#include <wcache/layout.h>'; }

# tryP: the same again with block_pack.h, for A2b. A third preamble rather than
# folding it into tryL, for the same reason tryL is not folded into try: the
# concrete mapper's header pulls in layout.h and types.h, so a case compiled
# with it proves nothing about which header a name came from, and the A1 and
# A2a cases must keep proving that.
tryP() { try "$1" "$2" "$3" '#include <wcache/block_pack.h>'; }

# tryC: the same again with cache.h, for A4a. A fourth preamble for the reason
# the other three are separate: cache.h includes types.h and nothing else, so a
# case compiled with it proves the array interface needs no layout header. If
# CacheArray ever grows a dependency on AddressMapper, the A4a cases start
# failing here rather than being carried silently by a preamble that already
# included it.
tryC() { try "$1" "$2" "$3" '#include <wcache/cache.h>'; }

# tryS: the same again with set_associative.h, for A4b. A fifth preamble for
# the reason tryP is not folded into tryL: the concrete array's header pulls in
# cache.h AND layout.h, so a case compiled with it proves nothing about which
# header a name came from, and the A4a cases under tryC must keep proving that
# CacheArray needs no layout header.
tryS() { try "$1" "$2" "$3" '#include <wcache/set_associative.h>'; }

# tryR: the same again with policy.h, for A5. A sixth preamble, and it is the
# one that carries A5's half of plan 2.2's array/policy split.
#
# policy.h includes cache.h and types.h and nothing else, so a case compiled
# with it proves the policy interface needs nothing but a SlotId and a
# Candidate. That is not restating a type: the split says a policy "knows
# nothing about sets or ways", and the way it would erode is a policy that
# wanted an associativity and reached for the array's header to get one. If
# policy.h ever grows that dependency the cases below start ACCEPTING, which is
# the same wall tryC puts around the array in the other direction.
tryR() { try "$1" "$2" "$3" '#include <wcache/policy.h>'; }

# Phase B's three preambles. NAMING, because the tree carries a collision: the
# PLAN's Phase B units are B1 (Port), B2 (EventQueue) and B3 (MshrFile), while
# PROGRESS.md's DECISIONS are also numbered B1-B104. Every "B1"/"B2"/"B3" in the
# sections below is the plan's unit.
#
# tryPort: port.h, which includes types.h and nothing else. A case compiled with
# it proves the timing primitive needs no layout, no array and no MSHR, which is
# what "Phase B: timing primitives, the clock exists and the hierarchy does not"
# means as a compile-time fact rather than as a sentence in a plan.
tryPort() { try "$1" "$2" "$3" '#include <wcache/port.h>'; }

# tryEvent: event.h. This preamble is also the reason `make test` compiles the
# header at all: before B2's tests, event.h was included by NO translation unit
# in the tree, so nothing built it. Same shape as cache.h's state before A4a,
# which B59 recorded.
tryEvent() { try "$1" "$2" "$3" '#include <wcache/event.h>'; }

# tryMshr: mshr.h, an eighth preamble for tryPort's reason. The MSHR file holds
# no port and no clock (it "cannot violate P2 by predicting a time, since it
# holds no clock"), so a case compiled here proves it reaches neither.
tryMshr() { try "$1" "$2" "$3" '#include <wcache/mshr.h>'; }

# tryBoth: event.h AND mshr.h in one translation unit. It exists for exactly one
# question, and it is a question no single-header preamble can ask: both headers
# declare a free function named `key_less` in namespace wcache, one over 3.6's
# EventKey and one over 3.8's Request. They are different keys for different
# populations, and the engine includes both headers, so "these two overloads
# coexist and each call resolves" has to be measured somewhere.
tryBoth() { try "$1" "$2" "$3" '#include <wcache/event.h>
#include <wcache/mshr.h>'; }

# The one valid configuration every A2b case builds on, so a case that is meant
# to fail on a type cannot pass or fail on a bad extent instead.
SHAPE='WeightShape{3, 3, 256, 64}'

# The same configuration already constructed, for A2c's cases. Every one of them
# is about a call on a live mapper rather than about construction, and writing
# the constructor out per case would let a case fail on the construction while
# claiming to fail on the call. const because all three A2c helpers are const:
# one mapper serves L1 and L2, so a case that needed a non-const mapper would be
# testing the opposite of what the unit promises.
PACK="const BlockPackMapper m($SHAPE, 64, 128, 1);"

# A minimal complete implementation, so a case can say "and now instantiate it"
# without repeating it. Nothing in it is under test; the control cases at the
# end are what prove it compiles, and every case that removes one line from it
# is testing that the removal is what did the rejecting.
MAPPER='struct M : AddressMapper {
  void expand(const Burst&, std::vector<LineId>&) const override {}
  Placement locate(LineId, std::int64_t) const override { return Placement{SetIndex{0}, TagId{0}}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 4; }
};'

# The same subclass with one override removed, by name.
omit() { echo "$MAPPER" | grep -v "$1"; }

# A minimal complete CacheArray, for A4a, in exactly the role MAPPER plays for
# A2a. Nothing in it is under test: it is the smallest thing that satisfies the
# interface, so a case can say "and now instantiate it" and a case that removes
# one line from it is testing that the removal is what did the rejecting. The
# bodies are deliberately trivial -- A4a is an interface, and
# SetAssociativeArray is A4b's.
ARRAY='struct A : CacheArray {
  SlotId probe(LineId) const override { return NoSlot; }
  SlotId free_slot(LineId) const override { return SlotId{0}; }
  void victim_candidates(LineId, std::vector<Candidate>& out) const override { out.clear(); }
  InsertResult insert(LineId, SlotId) override { return InsertResult{false, NoLine}; }
  void invalidate(SlotId) override {}
  std::int32_t num_slots() const override { return 1; }
};'

omitA() { echo "$ARRAY" | grep -v "$1"; }

section "== N12: the three time-like types do not mix"
try reject 'SimTime < LocalTick'        'int main(){ return SimTime{1} < LocalTick{1}; }'
try reject 'SimTime == RefusalOrder'    'int main(){ return SimTime{1} == RefusalOrder{1}; }'
try reject 'LocalTick == RefusalOrder'  'int main(){ return LocalTick{1} == RefusalOrder{1}; }'
try reject 'SimTime <= LocalTick'       'int main(){ return SimTime{1} <= LocalTick{1}; }'
try reject 'SimTime > RefusalOrder'     'int main(){ return SimTime{1} > RefusalOrder{1}; }'
try reject 'SimTime != LocalTick'       'int main(){ return SimTime{1} != LocalTick{1}; }'

section "== the id types do not mix, with each other or with time"
try reject 'LineId == SlotId'           'int main(){ return LineId{1} == SlotId{1}; }'
try reject 'LineId == CoreId'           'int main(){ return LineId{1} == CoreId{1}; }'
try reject 'SlotId < CoreId'            'int main(){ return SlotId{1} < CoreId{1}; }'
try reject 'LineId < SimTime'           'int main(){ return LineId{1} < SimTime{1}; }'

section "== arithmetic is closed except for the one crossing"
try reject 'LocalTick + SimTime (order)' 'int main(){ return (int)(LocalTick{1} + SimTime{1}).get(); }'
try reject 'SimTime - LocalTick'         'int main(){ return (int)(SimTime{1} - LocalTick{1}).get(); }'
try reject 'SimTime + RefusalOrder'      'int main(){ return (int)(SimTime{1} + RefusalOrder{1}).get(); }'
try reject 'RefusalOrder + RefusalOrder' 'int main(){ return (int)(RefusalOrder{1} + RefusalOrder{1}).get(); }'
try reject 'LineId + LineId'             'int main(){ return (int)(LineId{1} + LineId{1}).get(); }'
try reject 'SlotId + SlotId'             'int main(){ return (int)(SlotId{1} + SlotId{1}).get(); }'
try reject 'CoreId + CoreId'             'int main(){ return (int)(CoreId{1} + CoreId{1}).get(); }'
try reject 'SimTime += LocalTick'        'int main(){ SimTime a{1}; a += LocalTick{1}; return (int)a.get(); }'

section "== no implicit conversion in or out (explicit constructor, no operator T)"
try reject 'SimTime t = 5'              'int main(){ SimTime t = 5; return (int)t.get(); }'
try reject 'int64 from SimTime'         'std::int64_t f(){ return SimTime{5}; } int main(){ return (int)f(); }'
try reject 'call f(SimTime) with int'   'void f(SimTime); int main(){ f(5); }'
try reject 'call f(LineId) with SlotId' 'void f(LineId); int main(){ f(SlotId{1}); }'
try reject 'SimTime a = LocalTick'      'int main(){ SimTime a{1}; a = LocalTick{2}; return (int)a.get(); }'
try reject 'return LocalTick as SimTime' 'SimTime f(){ return LocalTick{1}; } int main(){ return (int)f().get(); }'

section "== decision B2: no default construction"
try reject 'SlotId s;'                  'int main(){ SlotId s; return (int)s.get(); }'
try reject 'SimTime t;'                 'int main(){ SimTime t; return (int)t.get(); }'
try reject 'vector<SlotId> v(4)'        '#include <vector>
int main(){ std::vector<SlotId> v(4); return (int)v.size(); }'
try reject 'struct member left out'     'struct S { int a; SimTime t; S(int x) : a(x) {} };
int main(){ S s(1); return (int)s.t.get(); }'

section "== A1b: geometry, the distinctions that are kept"
# Coord and WeightShape are both four int32s. The whole reason they are two
# types is that an extent must not be readable as a coordinate.
try reject 'coord_on(WeightShape)'      'int main(){ return coord_on(WeightShape{1,1,1,1}, Axis::KH); }'
try reject 'extent_on(Coord)'           'int main(){ return extent_on(Coord{1,1,1,1}, Axis::KH); }'
try reject 'Coord c = WeightShape{}'    'int main(){ Coord c = WeightShape{1,1,1,1}; return c.kh; }'
# Axis is scoped and does not decay, so an int cannot stand in for an axis and
# an axis cannot be used as an index or a coordinate.
try reject 'bare KH'                    'int main(){ return coord_on(Coord{1,1,1,1}, KH); }'
try reject 'coord_on with an int axis'  'int main(){ return coord_on(Coord{1,1,1,1}, 2); }'
try reject 'Axis in arithmetic'         'int main(){ return Axis::KH + 1; }'
try reject 'int from Axis'              'int main(){ int a = Axis::CIN; return a; }'
# Burst's axis field is an Axis, not an index, and its anchor is a Coord.
try reject 'Burst with an int axis'     'int main(){ Burst b{Coord{0,0,0,0}, 3, 4, 1}; return b.count; }'
try reject 'Burst anchored on a shape'  'int main(){ Burst b{WeightShape{1,1,1,1}, Axis::COUT, 4, 1}; return b.count; }'

section "== A2a: AddressMapper is abstract and stays abstract"
# The interface exists so the engine never learns which layout it has. An
# instantiable AddressMapper would be a mapper with no layout at all, which is
# the one thing every caller would then have to guard against.
tryL reject 'AddressMapper m;'          'int main(){ AddressMapper m; (void)m; return 0; }'
tryL reject 'new AddressMapper'         'int main(){ auto* p = new AddressMapper(); delete p; }'
# An abstract class cannot be a parameter or a return type, which is what stops
# a mapper being sliced down to its base and losing the layout on the way into
# a function. Both cases name the parameter and give the function a body: a
# bare `void f(AddressMapper);` declaration is accepted by g++ under
# -fsyntax-only, so the declaration-only spelling would have reported a pass
# while checking nothing.
tryL reject 'AddressMapper by value in'  "$MAPPER void f(AddressMapper m){ (void)m; } int main(){ M m; f(m); }"
tryL reject 'AddressMapper by value out' "$MAPPER AddressMapper f(){ M m; return m; } int main(){ f(); }"
tryL reject 'vector<AddressMapper>'      'int main(){ std::vector<AddressMapper> v(1); return (int)v.size(); }'

# A subclass that leaves any one of the four unimplemented is abstract too, and
# fails at its own first instantiation. Four cases rather than one, because a
# single case would pass if only ONE of the four were pure.
tryL reject 'subclass omits expand'          "$(omit 'void expand') int main(){ M m; (void)m; }"
tryL reject 'subclass omits locate'          "$(omit 'Placement locate') int main(){ M m; (void)m; }"
tryL reject 'subclass omits num_lines'       "$(omit 'LineId num_lines') int main(){ M m; (void)m; }"
tryL reject 'subclass omits line_size_bytes' "$(omit 'line_size_bytes') int main(){ M m; (void)m; }"

section "== A2a: the signature is the contract"
# `const` on the pure virtuals is not a hint. An override that drops it does
# not override, so the class stays abstract, and `override` says so at the
# declaration rather than at the instantiation.
tryL reject 'override drops const' 'struct M : AddressMapper {
  void expand(const Burst&, std::vector<LineId>&) override {}
  Placement locate(LineId, std::int64_t) const override { return Placement{SetIndex{0}, TagId{0}}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'
# Returning the lines instead of appending them is the shape the interface
# rejected (a caller accumulates a tick into one reused buffer), so it must not
# be reachable by accident.
tryL reject 'expand returns a vector' 'struct M : AddressMapper {
  std::vector<LineId> expand(const Burst&) const override { return {}; }
  Placement locate(LineId, std::int64_t) const override { return Placement{SetIndex{0}, TagId{0}}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'
# num_lines is a LineId, not a raw count: the bound the engine compares tags
# against is the same quantity as the ids it is bounding.
tryL reject 'num_lines returns int64' 'struct M : AddressMapper {
  void expand(const Burst&, std::vector<LineId>&) const override {}
  Placement locate(LineId, std::int64_t) const override { return Placement{SetIndex{0}, TagId{0}}; }
  std::int64_t num_lines() const override { return 1; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'

section "== A2a: N12 at the mapper boundary"
# locate takes a LineId, and Tagged's explicit constructor is what makes the
# raw-int spelling a compile error rather than a silent reinterpretation.
#
# The result is unwrapped with .tag.get() rather than cast. Since U16 the tag is
# a TagId, so `(int)....tag` would not compile EITHER, and each case would then
# reject whatever its argument was: three cases reporting a pass while checking
# nothing. The unwrap leaves the argument as the only thing under test.
tryL reject 'locate(int)'      "$MAPPER int main(){ M m; return (int)m.locate(5, 8).tag.get(); }"
tryL reject 'locate(SlotId)'   "$MAPPER int main(){ M m; return (int)m.locate(SlotId{1}, 8).tag.get(); }"
tryL reject 'locate(SimTime)'  "$MAPPER int main(){ M m; return (int)m.locate(SimTime{1}, 8).tag.get(); }"
# A line count is not an int64 and a byte count is not a LineId. This is the
# mix-up the two return types exist to stop: cache_size_bytes / line_size_bytes
# is a set count, num_lines is a coverage denominator, and nothing sensible
# compares them.
tryL reject 'int64 from num_lines'   "$MAPPER int main(){ M m; std::int64_t n = m.num_lines(); return (int)n; }"
tryL reject 'num_lines < line_size'  "$MAPPER int main(){ M m; return m.num_lines() < m.line_size_bytes(); }"
tryL reject 'LineId from line_size'  "$MAPPER int main(){ M m; LineId n = m.line_size_bytes(); return (int)n.get(); }"
# expand fills a vector of LineId. A vector of SlotId is the same 32/64-bit
# shape mistake in container form.
tryL reject 'expand into vector<SlotId>' "$MAPPER int main(){ M m; std::vector<SlotId> out;
  m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1}, out); return (int)out.size(); }"

section "== A2b: BlockPackMapper is final and fully specified"
# B10: a differently NESTED layout is a new AddressMapper subclass, not a
# variant of this one. A class deriving from BlockPackMapper would inherit the
# block-packed flatten in order to disagree with part of it, which is the shape
# that makes a bug in one override invisible in the others.
tryP reject 'derive from BlockPackMapper' 'struct D : BlockPackMapper {
  using BlockPackMapper::BlockPackMapper;
}; int main(){ D d('"$SHAPE"', 64, 128, 1); (void)d; }'
# A mapper with no layout at all. The constructor is the only place the
# invariants are established, so a default-constructed one would have skipped
# every check in this unit.
tryP reject 'BlockPackMapper m;'          'int main(){ BlockPackMapper m; (void)m; }'
# weight_bytes has no default. Decision D2 in v1 was two places computing the
# size of a line and disagreeing; a defaulted parameter here would put the
# second one back by letting a caller omit it.
tryP reject 'ctor without weight_bytes'   'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128); (void)m; }'
# Coord and WeightShape are both four int32s, and the constructor takes the
# extents. Passing the coordinate of one element instead would build a mapper
# for a tensor the size of that coordinate, silently.
tryP reject 'ctor takes a Coord'          'int main(){ BlockPackMapper m(Coord{3, 3, 256, 64}, 64, 128, 1); (void)m; }'
# shape() hands out a const reference to the member every derived value was
# computed from. A writable one would leave num_lines() describing a tensor the
# mapper no longer has, with no way to notice.
tryP reject 'write through shape()'       'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  m.shape().KH = 1; return m.shape().KH; }'
# The concrete declarations, not only the interface ones. A caller holding a
# BlockPackMapper by value binds to these, so the A2a cases above do not cover
# them.
tryP reject 'int64 from num_lines'        'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  std::int64_t n = m.num_lines(); return (int)n; }'
tryP reject 'LineId from line_size_bytes' 'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  LineId n = m.line_size_bytes(); return (int)n.get(); }'

section "== A2c: the flatten helpers belong to the concrete mapper"
# line_of, line_stride and block_len are NOT on AddressMapper, and that is the
# reason the interface has four members rather than seven. The engine holds a
# mapper through the base (layout.h:34-40), so anything reachable there becomes
# an obligation on every future layout; B23's argument that a layout is chosen
# by naming a subclass is what these three would quietly widen. Three cases and
# not one, because moving any single helper onto the base would still leave the
# other two rejecting and a single case would report a pass.
tryP reject 'line_of through the base'     "int main(){ $PACK
  const AddressMapper& r = m; return (int)r.line_of(Coord{0,0,0,0}).get(); }"
tryP reject 'line_stride through the base' "int main(){ $PACK
  const AddressMapper& r = m; return (int)r.line_stride(Axis::KH); }"
tryP reject 'block_len through the base'   "int main(){ $PACK
  const AddressMapper& r = m; return (int)r.block_len(Axis::CIN); }"
# The radices themselves stay private. B24 puts them in stride_[4] indexed by
# static_cast<int>(Axis) so a future permutation is one function's edit; a
# reader that could subscript the array directly would be depending on the
# indexing convention from outside the one file that establishes it, and
# line_stride would stop being the only way to ask.
tryP reject 'stride_ is private'           "int main(){ $PACK return (int)m.stride_[0]; }"

section "== A2c: a coordinate is not a shape, and a stride is not an id"
# Coord and WeightShape are both four int32s and line_of takes the coordinate.
# A2b already pins the constructor against the swap (it takes the shape); this
# is the same confusion at the other end, where passing the layer's extents
# would name the element one past every corner.
tryP reject 'line_of takes a WeightShape'  "int main(){ $PACK return (int)m.line_of($SHAPE).get(); }"
# A burst is a run of coordinates, not one of them. expand is what takes a
# Burst, and it is the member that does not exist yet, so this is the mistake a
# caller wired up early would actually make.
tryP reject 'line_of takes a Burst'        "int main(){ $PACK
  return (int)m.line_of(Burst{Coord{0,0,0,0}, Axis::COUT, 4, 1}).get(); }"
# line_of names an address, so it returns a LineId and the tag does not fall
# off on the way out. This is the same wall as A2a's 'int64 from num_lines',
# restated on the member that produces ids one at a time.
tryP reject 'int64 from line_of'           "int main(){ $PACK
  std::int64_t l = m.line_of(Coord{0,0,0,0}); return (int)l; }"
# And the two helpers are the other side of it: a stride and a block count are
# DELTAS, not addresses, so neither becomes a LineId by assignment. v1's
# line_stride returned LineId; A1's typing is what makes that spelling gone
# rather than merely discouraged (the A2b to A2c board row).
tryP reject 'LineId from line_stride'      "int main(){ $PACK
  LineId s = m.line_stride(Axis::KH); return (int)s.get(); }"
tryP reject 'LineId from block_len'        "int main(){ $PACK
  LineId n = m.block_len(Axis::CIN); return (int)n.get(); }"
# The arithmetic that a step check wants to write. LineId has no operator+ at
# all (A1a), so "the line one block along CIN" has to be spelled with an
# explicit .get(), which is what tests/test_block_pack.cpp does. Without this
# case the .get() there reads as a style choice rather than as the only
# spelling that exists.
tryP reject 'line_of + line_stride'        "int main(){ $PACK
  return (int)(m.line_of(Coord{0,0,0,0}) + m.line_stride(Axis::CIN)).get(); }"
# Comparing an id against a delta is the same mix-up as an ordering. It is
# worth its own case because `line_of(c) < line_stride(a)` is a plausible
# accident in a bounds check, where the bound wanted is num_lines().
tryP reject 'line_of < line_stride'        "int main(){ $PACK
  return m.line_of(Coord{0,0,0,0}) < m.line_stride(Axis::KH); }"
# A vector of strides is not a vector of lines. Same shape mistake as A2a's
# 'expand into vector<SlotId>', in the container form a caller accumulating a
# burst would reach for.
tryP reject 'vector<LineId> takes a stride' "int main(){ $PACK
  std::vector<LineId> v; v.push_back(m.line_stride(Axis::COUT)); return (int)v.size(); }"

section "== A2c: an axis is an Axis"
# Axis is scoped and does not decay, so an int cannot stand in for one. Both
# helpers take an Axis and both index or switch on it, and line_stride's index
# is into a four-element array: an int argument would be the one spelling that
# could read past stride_[3] without the switch ever seeing it.
tryP reject 'line_stride(int)'             "int main(){ $PACK return (int)m.line_stride(2); }"
tryP reject 'block_len(int)'               "int main(){ $PACK return (int)m.block_len(2); }"
tryP reject 'line_stride with a bare KH'   "int main(){ $PACK return (int)m.line_stride(KH); }"

section "== A2d: expand fills a caller's buffer, and cannot be made to drop it"
# The out parameter is a non-const lvalue reference, which is what makes the
# accumulate pattern layout.h describes possible AND what stops a caller
# discarding a whole burst by passing a temporary. Both spellings below compile
# happily against a by-value or a by-const-reference parameter and neither
# returns anything, so the loss is silent: the tick accumulates nothing and the
# hit rate is a hit rate on demand that was never issued.
tryP reject 'expand into a temporary'      "int main(){ $PACK
  m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1}, std::vector<LineId>{}); return 0; }"
tryP reject 'expand into a const vector'   "int main(){ $PACK const std::vector<LineId> out;
  m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1}, out); return (int)out.size(); }"
# The buffer holds LineId, not the raw int64 the flatten computes. This is the
# same wall as A2a's 'expand into vector<SlotId>', on the container a caller
# accumulating a tick would actually declare, and it is what keeps the tag from
# falling off between the mapper and the MSHR file that is keyed by LineId.
tryP reject 'expand into vector<int64>'    "int main(){ $PACK std::vector<std::int64_t> out;
  m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1}, out); return (int)out.size(); }"
# A burst is a RUN of coordinates and expand is the member that takes one.
# line_of is the member that takes a single Coord, and the two are one letter
# apart at the call site now that both exist on the same object.
tryP reject 'expand takes a Coord'         "int main(){ $PACK std::vector<LineId> out;
  m.expand(Coord{0,0,0,0}, out); return (int)out.size(); }"
# Returning the lines instead of appending them is the shape layout.h rejected.
# A2a pins it on the interface; this is the same case on the concrete class,
# which is what a caller holding a BlockPackMapper by value binds to.
tryP reject 'expand returns the lines'     "int main(){ $PACK
  std::vector<LineId> out = m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1});
  return (int)out.size(); }"

section "== A2d: locate takes a LineId and a plain set count, and returns neither"
# N12 at the member that turns an id into an array subscript. A raw int64 line
# is the spelling that would let a set index, a tag, or a byte count be located
# by accident, and Tagged's explicit constructor is what makes it an error.
#
# .tag.get() rather than a cast, for the reason the A2a cases above give: since
# U16 the tag is a TagId and the cast alone would reject every one of them.
tryP reject 'locate takes a raw int64'     "int main(){ $PACK return (int)m.locate(5, 8).tag.get(); }"
tryP reject 'locate takes a SlotId'        "int main(){ $PACK return (int)m.locate(SlotId{1}, 8).tag.get(); }"
# num_sets is a plain int64 and deliberately not a tagged scalar: it is a
# geometry of the ARRAY, not of the layout, which is why it is an argument
# rather than mapper state. A LineId there would be a line count standing in for
# a set count, which is exactly the confusion the wall exists to stop.
tryP reject 'locate num_sets is a LineId'  "int main(){ $PACK
  return (int)m.locate(LineId{0}, LineId{8}).tag.get(); }"
# Placement's set index does not convert back into a line id. Since U16 the
# field is a SetIndex, so BOTH spellings reject: this copy-initialisation, which
# rejected before U16 too because Tagged's constructor is explicit, and the
# braced `LineId l{...set_index}` below, which used to be the accepted half and
# is now the case that measures the field's type.
tryP reject 'LineId from set_index'        "int main(){ $PACK
  LineId l = m.locate(LineId{0}, 8).set_index; return (int)l.get(); }"

section "== controls: these MUST compile, or every case above is vacuous"
try accept 'SimTime < SimTime'          'int main(){ return SimTime{1} < SimTime{2}; }'
try accept 'SimTime + SimTime'          'int main(){ return (int)(SimTime{1} + SimTime{2}).get(); }'
try accept 'SimTime + LocalTick'        'int main(){ return (int)(SimTime{1} + LocalTick{2}).get(); }'
try accept 'LocalTick + LocalTick'      'int main(){ return (int)(LocalTick{1} + LocalTick{2}).get(); }'
try accept 'SimTime += SimTime'         'int main(){ SimTime a{1}; a += SimTime{1}; return (int)a.get(); }'
try accept 'RefusalOrder < RefusalOrder' 'int main(){ return RefusalOrder{1} < NoRefusal; }'
try accept 'SlotId == NoSlot'           'int main(){ return SlotId{1} == NoSlot; }'
try accept 'vector<SlotId> v(4, NoSlot)' '#include <vector>
int main(){ std::vector<SlotId> v(4, NoSlot); return (int)v.size(); }'
try accept 'f(SimTime{5})'              'void f(SimTime); int main(){ f(SimTime{5}); }'
try accept 'coord_on(Coord, Axis)'      'int main(){ return coord_on(Coord{1,1,1,1}, Axis::KH); }'
try accept 'extent_on(WeightShape,Axis)' 'int main(){ return extent_on(WeightShape{1,1,1,1}, Axis::KH); }'
try accept 'with_coord_on writes'       'int main(){ return with_coord_on(Coord{1,1,1,1}, Axis::CIN, 7).cin; }'
try accept 'Burst braced'               'int main(){ Burst b{Coord{0,0,0,0}, Axis::COUT, 4, 1}; return b.count; }'

# A2a's controls. The four "subclass omits X" cases above are worth nothing
# unless the complete subclass compiles and instantiates, and the N12 cases are
# worth nothing unless the correctly typed call does.
tryL accept 'complete subclass'         "$MAPPER int main(){ M m; (void)m; return 0; }"
tryL accept 'used through the base'     "$MAPPER int main(){ M m; const AddressMapper& r = m;
  std::vector<LineId> out; r.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 1, 1}, out);
  return (int)out.size(); }"
tryL accept 'delete through the base'   "$MAPPER int main(){ AddressMapper* p = new M(); delete p; }"
tryL accept 'locate(LineId, int64)'     "$MAPPER int main(){ M m; return (int)m.locate(LineId{5}, 8).set_index.get(); }"
tryL accept 'num_lines is a LineId'     "$MAPPER int main(){ M m; LineId n = m.num_lines(); return (int)n.get(); }"
# The unwrap is explicit and therefore allowed: N12 asks that the mix be
# impossible by accident, not that it be impossible.
tryL accept 'explicit .get() unwrap'    "$MAPPER int main(){ M m;
  return m.num_lines().get() < m.line_size_bytes() ? 1 : 0; }"
tryL accept 'Placement braced'          'int main(){ Placement p{SetIndex{3}, TagId{100}};
  return (int)(p.tag.get() + p.set_index.get()); }'
# U16: Placement's fields are TYPED, and these four cases are what says so.
#
# Three of them were accepts until U16, and they are the reason U16 was asked
# for. A4a's constrained constructor closed the WIDTH half of B29 and only that
# half: it could reject `SlotId{tag}` because 64 into 32 loses something, and it
# could never reject `LineId{set_index}` because both were int64 and nothing was
# lost. What was wrong with those was the NAME, and no narrowing rule reaches a
# name. Giving the fields their own types (SetIndex, TagId) is what closes them,
# and B29's corrected row is closed by this block going all-reject.
#
# Each case is a DIFFERENT wall, which is why there are four and not one:
# leaking out to the raw representation, into a sibling id, into a time, and
# into a narrower id.
tryL reject 'set_index is a raw int64'  'int main(){ Placement p{SetIndex{3}, TagId{100}};
  std::int64_t s = p.set_index; return (int)s; }'
tryL reject 'a set index becomes a LineId' 'int main(){ Placement p{SetIndex{3}, TagId{100}};
  LineId l{p.set_index}; return (int)l.get(); }'
tryL reject 'a tag becomes a SimTime'      'int main(){ Placement p{SetIndex{3}, TagId{100}};
  SimTime t{p.tag}; return (int)t.get(); }'
# The one crossing that has to be spelled out, because it is the alias a reader
# can talk themselves into: a tag and a line id are BOTH signed 64-bit addresses
# in the same flat space, and `line == tag * num_sets + set_index` makes them
# look like the same quantity at num_sets == 1. They are not. A tag names a line
# only WITHIN one set, so a tag used as a line id addresses a different line at
# every set count but one.
#
# Added because the mutation `using TagId = Tagged<std::int64_t, tags::line>`
# SURVIVED the whole suite: with it, TagId and LineId are one type, and every
# other case in this block still rejected. This is the case that kills it.
tryL reject 'a tag becomes a LineId'       'int main(){ Placement p{SetIndex{3}, TagId{100}};
  LineId l{p.tag}; return (int)l.get(); }'
# Still a reject, but no longer for the reason it was written for, and that is
# worth stating rather than leaving for someone to misread later. Before U16 the
# tag was a raw int64 and this measured B29's WIDTH rule: 64 into 32 narrows, so
# the constrained constructor removed the overload. Now the tag is a TagId,
# which converts to nothing at all, so the case is rejected on the name before
# any width question is asked and it no longer measures width.
#
# It is NOT replaced with a new width case. The width rule keeps its own
# section below ("the non-narrowing constructor rejects on WIDTH"), six cases
# over three target types, and it is measured on a live member's return value by
# 'a stride becomes a SlotId', where line_stride really does return a raw int64.
# Typing Placement's fields did not weaken that rule; it removed the last raw
# int64 from THIS surface, so there is no longer a width question here to ask.
tryL reject 'a 64-bit tag becomes a SlotId' 'int main(){ Placement p{SetIndex{3}, TagId{100}};
  SlotId s{p.tag}; return (int)s.get(); }'

# A2b's controls. The seven cases above are worth nothing unless the ordinary
# four-argument construction compiles, unless the class really is usable through
# the base, and unless the two accessors that must NOT convert really do return
# the types the reject cases assumed.
tryP accept 'BlockPackMapper constructed' 'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  return (int)m.n_cin_blocks(); }'
tryP accept 'held by the base'            'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  const AddressMapper& r = m; return (int)r.line_size_bytes(); }'
tryP accept 'num_lines is a LineId'       'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  LineId n = m.num_lines(); return (int)n.get(); }'
tryP accept 'line_size_bytes is an int64' 'int main(){ BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  std::int64_t b = m.line_size_bytes(); return (int)b; }'
tryP accept 'shape() reads'               'int main(){ const BlockPackMapper m('"$SHAPE"', 64, 128, 1);
  return m.shape().CIN + (int)m.n_cout_blocks() + m.weight_bytes(); }'

# A2c's controls. Every reject case above is worth nothing unless the ordinary
# spellings compile: the three helpers on a CONST mapper (one mapper serves L1
# and L2), line_of binding a temporary Coord (which is what proves the
# parameter is a const reference rather than a mutable one), and the two return
# types the reject cases assumed.
tryP accept 'line_of on a temporary Coord' "int main(){ $PACK return (int)m.line_of(Coord{0,0,0,0}).get(); }"
tryP accept 'LineId from line_of'          "int main(){ $PACK
  LineId l = m.line_of(Coord{0,0,0,0}); return (int)l.get(); }"
tryP accept 'int64 from line_stride'       "int main(){ $PACK
  std::int64_t s = m.line_stride(Axis::KH); return (int)s; }"
tryP accept 'int64 from block_len'         "int main(){ $PACK
  std::int64_t n = m.block_len(Axis::CIN); return (int)n; }"
# The radix identity as the test file spells it, and the id/bound comparison
# that IS well typed: a line id compares against num_lines() because both name
# addresses in the same space.
tryP accept 'block_len * line_stride'      "int main(){ $PACK
  return (int)(m.block_len(Axis::CIN) * m.line_stride(Axis::CIN)); }"
tryP accept 'line_of < num_lines'          "int main(){ $PACK
  return m.line_of(Coord{0,0,0,0}) < m.num_lines(); }"
# The step check's spelling, with the unwrap made explicit. N12 asks that the
# mix be impossible by accident, not that it be impossible, and this is the
# escape hatch tests/test_block_pack.cpp uses on every stride check.
tryP accept 'explicit .get() plus a stride' "int main(){ $PACK
  return (int)(m.line_of(Coord{0,0,0,0}).get() + m.line_stride(Axis::CIN)); }"
# B29 discharged on A2c's surface. A stride is a factor of num_lines(), which
# is an int64 the constructor's overflow guard bounds only at INT64_MAX, so the
# size that used to be lost here was not bounded by anything this class checks.
# Before A4a this was an accept: g++ reported the truncation as a -Wnarrowing
# WARNING and compiled it anyway, and compile_fail.sh runs without -Werror, so
# the flags decided and the answer was "accepted and truncated". A4a's
# constrained constructor removes the overload instead of converting through
# it, so the call has no candidate and the flags no longer get a say.
tryP reject 'a stride becomes a SlotId'    "int main(){ $PACK
  SlotId s{m.line_stride(Axis::KH)}; return (int)s.get(); }"

# A2d's controls. The nine cases above are worth nothing unless the ordinary
# spellings compile: expand appending into a caller's own vector, locate taking
# the two types it names, both reached through the base (which is the only way
# the engine ever reaches them), and the explicit unwrap that N12 permits.
tryP accept 'expand appends to a vector'   "int main(){ $PACK std::vector<LineId> out;
  m.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 4, 1}, out); return (int)out.size(); }"
tryP accept 'expand through the base'      "int main(){ $PACK const AddressMapper& r = m;
  std::vector<LineId> out; r.expand(Burst{Coord{0,0,0,0}, Axis::COUT, 4, 1}, out);
  return (int)out.size(); }"
tryP accept 'locate(LineId, int64)'        "int main(){ $PACK
  return (int)m.locate(LineId{0}, 8).set_index.get(); }"
tryP accept 'locate through the base'      "int main(){ $PACK const AddressMapper& r = m;
  return (int)r.locate(LineId{0}, 8).tag.get(); }"
tryP accept 'Placement from locate'        "int main(){ $PACK
  Placement p = m.locate(LineId{0}, 8);
  return (int)(p.tag.get() + p.set_index.get()); }"
# U16, on the concrete mapper. The tryL case of the same name pins the wall on a
# hand-built Placement; this is the same wall on the value locate actually
# returns, which is the only Placement the engine ever holds. Both are kept
# because a field type could be reverted on the struct while locate went on
# constructing tagged values, and then only one of the two would go red.
tryP reject 'a set index becomes a LineId' "int main(){ $PACK
  LineId l{m.locate(LineId{0}, 8).set_index}; return (int)l.get(); }"

# ---------------------------------------------------------------------------
# A4a
# ---------------------------------------------------------------------------

section "== A4a: the non-narrowing constructor rejects on WIDTH (B29, U2)"
# The rule is about types, not values, and these are the cases that say so.
# Every one of them compiled before A4a, with g++ reporting a -Wnarrowing
# warning and truncating anyway; compile_fail.sh runs without -Werror, so
# "warned" meant "accepted". The constrained constructor removes the overload
# instead, so there is no longer anything to call.
try reject 'int64 lvalue into a SlotId'  'int main(){ std::int64_t b = 5; SlotId s{b}; return (int)s.get(); }'
try reject 'int64 lvalue into a CoreId'  'int main(){ std::int64_t b = 5; CoreId c{b}; return (int)c.get(); }'
# THE case for the trait being written with std::declval rather than with a
# value. `std::int32_t x{5L}` is legal C++: a constant expression that fits is
# a permitted narrowing. If the trait asked its question with a literal, that
# exception would leak in and the rule would depend on whether the caller
# happened to write a constant, which is a rule about values wearing a rule
# about types. declval names a value of the type without being one, so the
# answer is the same for `5L` and for a run-time int64. Both reject.
try reject 'a literal 5L into a SlotId'  'int main(){ SlotId s{5L}; return (int)s.get(); }'
try reject 'a literal 5L into a CoreId'  'int main(){ CoreId c{5L}; return (int)c.get(); }'
# Float to integer is a narrowing whatever the widths, including one that fits.
try reject 'a double into a LineId'      'int main(){ LineId l{1.5}; return (int)l.get(); }'
try reject 'an exact double into a LineId' 'int main(){ LineId l{2.0}; return (int)l.get(); }'

section "== A4a: and the accepts it must NOT have broken"
# A constraint that rejects everything would pass every case above and be
# useless. These are the spellings the engine actually writes.
try accept 'SlotId{5}'                   'int main(){ SlotId s{5}; return (int)s.get(); }'
try accept 'LineId{5}'                   'int main(){ LineId l{5}; return (int)l.get(); }'
# Widening is not narrowing: an int32 reaching an int64 id loses nothing.
try accept 'int32 lvalue into a LineId'  'int main(){ std::int32_t n = 5; LineId l{n}; return (int)l.get(); }'
# Copy construction. It survives ONLY because the constraint removes the
# template from the overload set for U = SlotId (there is no int32_t{SlotId}),
# leaving the implicit copy constructor to take the call. Both spellings,
# because they take different initialisation paths and a constraint written
# slightly differently could break one and leave the other.
try accept 'SlotId b{a}, copy braced'    'int main(){ SlotId a{5}; SlotId b{a}; return (int)b.get(); }'
try accept 'SlotId b = a, copy assigned' 'int main(){ SlotId a{5}; SlotId b = a; return (int)b.get(); }'
try accept 'SetIndex copy construction'  'int main(){ SetIndex a{5}; SetIndex b{a}; return (int)b.get(); }'
# A SetIndex is int64 and locate's answer is int64, so the type it exists to
# name is reachable from the quantity it names without a cast.
try accept 'SetIndex from an int64 lvalue' 'int main(){ std::int64_t v = 5; SetIndex s{v}; return (int)s.get(); }'
try accept 'NoSlot comparison'           'int main(){ return SlotId{1} != NoSlot; }'
try accept 'NoLine comparison'           'int main(){ return LineId{1} != NoLine; }'
try accept 'NoLine ordering'             'int main(){ return LineId{1} < NoLine; }'
try accept 'vector<LineId> v(4, NoLine)' '#include <vector>
int main(){ std::vector<LineId> v(4, NoLine); return (int)v.size(); }'

section "== A4a: SetIndex is a NAME, not a width (B9, the A1a obligation)"
# The seventh tagged type earns its place here or nowhere. Every case below has
# matching widths on both sides, so the narrowing constraint cannot be what
# rejects them: what rejects them is that the two quantities are different
# types. This is the distinction A1a's carried obligation asked A4 for --
# without it a set index and a way index are the same type and
# `policy.on_hit(SlotId{set_index})` is a spelling the code invites.
try reject 'SetIndex becomes a LineId'   'int main(){ LineId l{SetIndex{3}}; return (int)l.get(); }'
try reject 'LineId becomes a SetIndex'   'int main(){ SetIndex s{LineId{3}}; return (int)s.get(); }'
try reject 'SetIndex becomes a SimTime'  'int main(){ SimTime t{SetIndex{3}}; return (int)t.get(); }'
try reject 'SetIndex becomes a SlotId'   'int main(){ SlotId s{SetIndex{3}}; return (int)s.get(); }'
try reject 'SetIndex == SlotId'          'int main(){ return SetIndex{1} == SlotId{1}; }'
try reject 'SetIndex < LineId'           'int main(){ return SetIndex{1} < LineId{1}; }'
try reject 'SetIndex + SetIndex'         'int main(){ return (int)(SetIndex{1} + SetIndex{1}).get(); }'
try reject 'SetIndex s;'                 'int main(){ SetIndex s; return (int)s.get(); }'
try reject 'SetIndex t = 5'              'int main(){ SetIndex t = 5; return (int)t.get(); }'
try reject 'int64 from SetIndex'         'std::int64_t f(){ return SetIndex{5}; } int main(){ return (int)f(); }'
try accept 'SetIndex == SetIndex'        'int main(){ return SetIndex{1} == SetIndex{2}; }'
# NoLine is a LineId and NoSlot a SlotId, so the two sentinels do not mix
# either. A slot scan comparing the wrong one would report every slot free.
try reject 'NoLine == NoSlot'            'int main(){ return NoLine == NoSlot; }'
try reject 'SlotId s = NoLine'           'int main(){ SlotId s{NoLine}; return (int)s.get(); }'

section "== A4a: the CacheArray interface keeps its shape (plan 2.2)"
# Same treatment A2a gave AddressMapper: the unit is an interface, so its
# content IS its shape, and a signature that silently changed would reach every
# array and every policy built on it.
tryC accept 'complete array'             "$ARRAY int main(){ A a; (void)a; return 0; }"
tryC accept 'array through the base'     "$ARRAY int main(){ A a; CacheArray& r = a;
  return (int)r.insert(LineId{1}, SlotId{0}).evicted; }"
tryC accept 'delete array through base'  "$ARRAY int main(){ CacheArray* p = new A(); delete p; }"
# All five verbs of 2.2, plus num_slots, reached through the base. invalidate is
# on the list from the start (N8), and this is the case that says so: a level
# that cannot invalidate cannot implement the inclusive branch at all.
tryC accept 'all five verbs through base' "$ARRAY int main(){ A a; CacheArray& r = a;
  std::vector<Candidate> out;
  SlotId s = r.probe(LineId{1});
  SlotId f = r.free_slot(LineId{1});
  r.victim_candidates(LineId{1}, out);
  InsertResult ir = r.insert(LineId{1}, SlotId{0});
  r.invalidate(SlotId{0});
  return (int)(s.get() + f.get() + out.size() + ir.evicted + r.num_slots()); }"
# probe is const and is NOT an access (plan 2.2), so it must be callable on a
# const array. This is the case that would fail first if probe ever grew a side
# effect that needed a non-const this, which is the change that would silently
# perturb the recency stack.
tryC accept 'probe on a const array'     "$ARRAY int main(){ const A a; const CacheArray& r = a;
  return (int)r.probe(LineId{1}).get(); }"
tryC accept 'free_slot on a const array' "$ARRAY int main(){ const A a; const CacheArray& r = a;
  return (int)r.free_slot(LineId{1}).get(); }"
tryC accept 'victim_candidates is const' "$ARRAY int main(){ const A a; const CacheArray& r = a;
  std::vector<Candidate> out; r.victim_candidates(LineId{1}, out); return (int)out.size(); }"
# Each verb omitted in turn: the class must stay abstract, so a partial array
# cannot be instantiated. Six cases because an interface with a verb nobody
# implements is the failure N8 exists to prevent.
tryC reject 'array omits probe'          "$(omitA 'SlotId probe') int main(){ A a; (void)a; return 0; }"
tryC reject 'array omits free_slot'      "$(omitA 'free_slot') int main(){ A a; (void)a; return 0; }"
tryC reject 'array omits victim_candidates' "$(omitA 'victim_candidates') int main(){ A a; (void)a; return 0; }"
tryC reject 'array omits insert'         "$(omitA 'InsertResult insert') int main(){ A a; (void)a; return 0; }"
tryC reject 'array omits invalidate'     "$(omitA 'void invalidate') int main(){ A a; (void)a; return 0; }"
tryC reject 'array omits num_slots'      "$(omitA 'num_slots') int main(){ A a; (void)a; return 0; }"
# An override may not quietly change a signature. `override` is what turns each
# of these into an error at the subclass rather than a second, silently
# unrelated function that leaves the pure virtual unimplemented.
tryC reject 'probe drops its const'      'struct A : CacheArray {
  SlotId probe(LineId) override { return NoSlot; }
  SlotId free_slot(LineId) const override { return SlotId{0}; }
  void victim_candidates(LineId, std::vector<Candidate>&) const override {}
  InsertResult insert(LineId, SlotId) override { return InsertResult{false, NoLine}; }
  void invalidate(SlotId) override {}
  std::int32_t num_slots() const override { return 1; }
}; int main(){ A a; (void)a; return 0; }'
tryC reject 'victim_candidates by value' 'struct A : CacheArray {
  SlotId probe(LineId) const override { return NoSlot; }
  SlotId free_slot(LineId) const override { return SlotId{0}; }
  void victim_candidates(LineId, std::vector<Candidate>) const override {}
  InsertResult insert(LineId, SlotId) override { return InsertResult{false, NoLine}; }
  void invalidate(SlotId) override {}
  std::int32_t num_slots() const override { return 1; }
}; int main(){ A a; (void)a; return 0; }'
tryC reject 'num_slots returns int64'    'struct A : CacheArray {
  SlotId probe(LineId) const override { return NoSlot; }
  SlotId free_slot(LineId) const override { return SlotId{0}; }
  void victim_candidates(LineId, std::vector<Candidate>&) const override {}
  InsertResult insert(LineId, SlotId) override { return InsertResult{false, NoLine}; }
  void invalidate(SlotId) override {}
  std::int64_t num_slots() const override { return 1; }
}; int main(){ A a; (void)a; return 0; }'
# N12 at the array's own surface. probe takes the id of a LINE; a slot id there
# is the confusion SlotId and LineId exist to keep apart, and insert's two
# arguments are one of each, so a swapped call must not compile.
tryC reject 'probe takes a SlotId'       "$ARRAY int main(){ A a; return (int)a.probe(SlotId{1}).get(); }"
tryC reject 'probe takes a raw int64'    "$ARRAY int main(){ A a; return (int)a.probe(5).get(); }"
tryC reject 'insert arguments swapped'   "$ARRAY int main(){ A a;
  return (int)a.insert(SlotId{0}, LineId{1}).evicted; }"
tryC reject 'invalidate takes a LineId'  "$ARRAY int main(){ A a; a.invalidate(LineId{1}); return 0; }"
# victim_candidates appends into the caller's buffer by reference, so a
# temporary and a const vector must both fail: the same wall A2a put around
# expand, on the verb that has the same shape.
tryC reject 'candidates into a temporary' "$ARRAY int main(){ A a;
  a.victim_candidates(LineId{1}, std::vector<Candidate>{}); return 0; }"
tryC reject 'candidates into a const vector' "$ARRAY int main(){ A a;
  const std::vector<Candidate> out; a.victim_candidates(LineId{1}, out); return (int)out.size(); }"
tryC reject 'candidates into vector<SlotId>' "$ARRAY int main(){ A a;
  std::vector<SlotId> out; a.victim_candidates(LineId{1}, out); return (int)out.size(); }"
# Candidate pairs a slot with the line in it, and the two fields are different
# types precisely so they cannot be written in the wrong order.
tryC reject 'Candidate fields swapped'   'int main(){ Candidate c{NoLine, NoSlot}; return (int)c.slot.get(); }'
tryC reject 'InsertResult line is a SlotId' 'int main(){ InsertResult r{true, NoSlot}; return (int)r.evicted; }'
tryC accept 'Candidate braced'           'int main(){ Candidate c{NoSlot, NoLine}; return (int)c.slot.get(); }'
tryC accept 'InsertResult braced'        'int main(){ InsertResult r{false, NoLine}; return (int)r.evicted; }'
# The array holds no policy state (2.2's hard boundary), so it has no on_hit to
# call. This is the shape check that would fail if the split ever eroded.
tryC reject 'array has on_hit'           "$ARRAY int main(){ A a; a.on_hit(SlotId{0}); return 0; }"

# ---------------------------------------------------------------------------
# A4b
# ---------------------------------------------------------------------------

section "== A4b: copy and move on the polymorphic base are protected"
# The defect A4a handed to A4b: CacheArray had a virtual destructor and no copy
# or move control, so it was a sliceable polymorphic base. What was actually
# reachable is ASSIGNMENT rather than copying -- the class is abstract, so no
# object of it can exist and a by-value copy never had anything to copy, which
# is what the abstractness cases above already prove. `r1 = r2` through two base
# references compiled and assigned the base subobject only, leaving the derived
# state untouched: for an array that is a half-assigned cache reporting a hit
# rate for a geometry no level ever had.
#
# These two cases are the whole guard on that decision. Without them the
# protected access specifier could be deleted, or moved back to public, and
# nothing in the tree would go red.
tryC reject 'base assignment through references' "$ARRAY int main(){ A a1, a2;
  CacheArray& r1 = a1; CacheArray& r2 = a2; r1 = r2; return 0; }"
tryC reject 'base move assignment'       "$ARRAY int main(){ A a1, a2;
  CacheArray& r1 = a1; r1 = static_cast<CacheArray&&>(a2); return 0; }"
# And the other half, which is why the operations are PROTECTED rather than
# deleted: deleting would take them from derived classes too, and C1 holds one
# L1 per core over 8 to 256 cores, so a container of concrete arrays is the
# ordinary case. A derived class stays copyable AS ITSELF, where a copy is
# whole. If these ever start failing, `= default` has been changed to `= delete`
# and the engine's per-core arrays stop being storable.
tryC accept 'a whole derived copy'       "$ARRAY int main(){ A a; A b{a}; return (int)b.num_slots(); }"
tryC accept 'a whole derived assignment' "$ARRAY int main(){ A a, b; a = b; return (int)a.num_slots(); }"
tryC accept 'a vector of concrete arrays' '#include <vector>
struct A : CacheArray {
  SlotId probe(LineId) const override { return NoSlot; }
  SlotId free_slot(LineId) const override { return SlotId{0}; }
  void victim_candidates(LineId, std::vector<Candidate>& out) const override { out.clear(); }
  InsertResult insert(LineId, SlotId) override { return InsertResult{false, NoLine}; }
  void invalidate(SlotId) override {}
  std::int32_t num_slots() const override { return 1; }
};
int main(){ std::vector<A> v; v.push_back(A{}); v.push_back(A{}); return (int)v.size(); }'
# The default constructor has to be declared alongside them: declaring any
# constructor suppresses the implicit one. This is the case that says so, and it
# is the one that would catch its removal, since without it every array in the
# tree stops constructing and this file is where that shows up first.
tryC accept 'a derived array still default-constructs' "$ARRAY int main(){ A a; return (int)a.num_slots(); }"

section "== A4b: SetAssociativeArray keeps its shape"
# The mapper these cases construct against is written out here rather than
# reached for from block_pack.h, and that is the point of the preamble rather
# than a convenience: set_associative.h takes an abstract AddressMapper, so a
# case that pulled in the one concrete mapper in the tree would stop being able
# to say the array needs no particular layout. Its line size is 256, so 65536
# bytes is 256 lines and every geometry below divides.
SAMAP='struct SM : AddressMapper {
  void expand(const Burst&, std::vector<LineId>&) const override {}
  Placement locate(LineId, std::int64_t) const override { return Placement{SetIndex{0}, TagId{0}}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 256; }
};'
tryS accept 'SetAssociativeArray constructed' "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); return (int)a.num_slots(); }"
tryS accept 'held by the base'           "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); const CacheArray& r = a; return (int)r.num_slots(); }"
tryS accept 'deleted through the base'   "$SAMAP int main(){ SM m;
  CacheArray* p = new SetAssociativeArray(m, 65536, 8); delete p; }"
# num_sets and associativity are deliberately NOT on the interface: a fully
# associative array has no meaningful set count, and putting them there would
# invite a policy to read them, which is plan 2.2's array/policy split leaking.
# These are the two cases that keep that a decision rather than an accident.
tryS reject 'num_sets through the base'  "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); const CacheArray& r = a; return (int)r.num_sets(); }"
tryS reject 'associativity through the base' "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); const CacheArray& r = a; return (int)r.associativity(); }"
# B10's reason, and the same case BlockPackMapper has: a class deriving from
# this one would be inheriting the set-associative geometry in order to disagree
# with part of it. A fully associative array is a sibling of CacheArray.
tryS reject 'a subclass of the final array' "struct X : SetAssociativeArray {};
  int main(){ return 0; }"
# The C1 case made concrete: one L1 per core over 8 to 256 cores, so the real
# array has to be copyable as itself. This is what the protected-rather-than-
# deleted half of the decision actually buys.
tryS accept 'the array copied as itself' "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); SetAssociativeArray b{a}; return (int)b.num_slots(); }"
# And what it does NOT buy, recorded rather than assumed: the array holds the
# mapper by REFERENCE, so its copy assignment is implicitly deleted whatever the
# base does. An array cannot be re-pointed at a different mapper after
# construction, which is a stronger guarantee than the base's and is free.
tryS reject 'the array assigned over'    "$SAMAP int main(){ SM m;
  SetAssociativeArray a(m, 65536, 8); SetAssociativeArray b(m, 4096, 4);
  a = b; return (int)a.num_slots(); }"

# ---------------------------------------------------------------------------
# A5
# ---------------------------------------------------------------------------

section "== A5: a ReplacementPolicy needs nothing but SlotId and Candidate"
# The minimal conforming policy, written out here rather than reached for from
# stamp_policy.h. That is the point of the preamble rather than a convenience:
# a case that pulled in the concrete policies would compile against a header
# that already includes them, and would stop being able to say what policy.h
# alone provides.
POL='struct P : ReplacementPolicy {
  void on_hit(SlotId) override {}
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
  SlotId pick_victim(const std::vector<Candidate>&) override { return NoSlot; }
};'
tryR accept 'a policy built on policy.h alone' "$POL int main(){ P p; p.on_hit(SlotId{0});
  std::vector<Candidate> c{Candidate{SlotId{0}, NoLine}};
  return (int)p.pick_victim(c).get(); }"
# The array and the mapper are NOT reachable from this header, which is the
# split as a compile-time fact. These two reject because the names do not exist
# here at all; if either header is ever pulled in they start accepting.
tryR reject 'a policy names the array'   'int main(){ SetAssociativeArray* a = nullptr; return a == nullptr; }'
tryR reject 'a policy names a mapper'    'int main(){ AddressMapper* m = nullptr; return m == nullptr; }'
# All four verbs are pure, so a policy cannot be half implemented. A default
# body on any of them is a policy whose forgotten half is silent, which is the
# one failure mode a hit rate cannot report.
tryR reject 'a policy omits pick_victim' 'struct Q : ReplacementPolicy {
  void on_hit(SlotId) override {}
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
};
int main(){ Q q; return 0; }'
tryR reject 'a policy omits on_hit'      'struct Q : ReplacementPolicy {
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
  SlotId pick_victim(const std::vector<Candidate>&) override { return NoSlot; }
};
int main(){ Q q; return 0; }'
# SlotId is the whole of what crosses the split: dense in [0, num_slots) and
# stable while a line stays resident, so a policy indexes a flat vector with it
# and never computes a set index. A verb that took a line address instead would
# be the policy learning where lines live.
tryR reject 'on_hit takes a LineId'      'struct Q : ReplacementPolicy {
  void on_hit(LineId) override {}
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
  SlotId pick_victim(const std::vector<Candidate>&) override { return NoSlot; }
};
int main(){ Q q; return 0; }'
tryR reject 'pick_victim over slots alone' 'struct Q : ReplacementPolicy {
  void on_hit(SlotId) override {}
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
  SlotId pick_victim(const std::vector<SlotId>&) override { return NoSlot; }
};
int main(){ Q q; return 0; }'
# pick_victim is deliberately NOT const, and this is the case that keeps it so.
# A Random policy draws from an RNG, which is state it must advance, so a const
# signature here is exactly the interface change adding it would force (Q5).
tryR reject 'pick_victim made const'     'struct Q : ReplacementPolicy {
  void on_hit(SlotId) override {}
  void on_fill(SlotId) override {}
  void on_invalidate(SlotId) override {}
  SlotId pick_victim(const std::vector<Candidate>&) const override { return NoSlot; }
};
int main(){ Q q; return 0; }'

section "== A5: copy and move on the policy base are protected"
# B67's decision applied to the second polymorphic base in the tree, and these
# are its ONLY guard: `protected:` in policy.h could be moved back to public and
# nothing else in the suite would go red. Through two base references `p1 = p2`
# would compile and assign the base subobject only, leaving the derived recency
# state untouched -- a half-assigned eviction order, reporting a plausible hit
# rate for a history it never had.
tryR reject 'policy assignment through references' "$POL int main(){ P p1, p2;
  ReplacementPolicy& r1 = p1; ReplacementPolicy& r2 = p2; r1 = r2; return 0; }"
tryR reject 'policy move assignment'     "$POL int main(){ P p1, p2;
  ReplacementPolicy& r1 = p1; r1 = static_cast<ReplacementPolicy&&>(p2); return 0; }"
# And the half that is why they are protected rather than deleted: the engine
# holds one L1 policy per core over 8 to 256 cores, so a policy stays copyable
# AS ITSELF, where a copy is whole. If this starts failing, `= default` has
# become `= delete`.
tryR accept 'a whole derived policy copy' "$POL int main(){ P a; P b{a};
  b.on_fill(SlotId{0}); return 0; }"

# ---------------------------------------------------------------------------
# Phase B, units B1 (Port), B2 (EventQueue) and B3 (MshrFile)
# ---------------------------------------------------------------------------

section "== B3: BurstIndex is a NAME, and CoreId is the name it must not be"
# The ninth tagged scalar earns its place here or nowhere, and it earns it on
# ONE case: a CoreId and a BurstIndex are both int32 and both signed, so the
# non-narrowing constructor cannot separate them and `explicit` cannot either.
# Only the name catches the swap. `Request` holds them side by side (3.3), so
# `Request{core, line, burst}` written with two arguments transposed is a
# spelling the struct invites, and the swap is the whole reason the type exists.
try reject 'CoreId == BurstIndex'        'int main(){ return CoreId{1} == BurstIndex{1}; }'
try reject 'BurstIndex < CoreId'         'int main(){ return BurstIndex{1} < CoreId{2}; }'
try reject 'CoreId{BurstIndex}'          'int main(){ CoreId c{BurstIndex{1}}; return (int)c.get(); }'
try reject 'BurstIndex{CoreId}'          'int main(){ BurstIndex b{CoreId{1}}; return (int)b.get(); }'
try reject 'f(CoreId) with a BurstIndex' 'void f(CoreId); int main(){ f(BurstIndex{1}); }'
try reject 'f(BurstIndex) with a CoreId' 'void f(BurstIndex); int main(){ f(CoreId{1}); }'
# And the rest of the wall every tagged scalar gets, so the ninth is not the one
# type in the tree with a weaker one.
try reject 'BurstIndex == LineId'        'int main(){ return BurstIndex{1} == LineId{1}; }'
try reject 'BurstIndex == SimTime'       'int main(){ return BurstIndex{1} == SimTime{1}; }'
try reject 'BurstIndex + BurstIndex'     'int main(){ return (int)(BurstIndex{1} + BurstIndex{1}).get(); }'
try reject 'BurstIndex b;'               'int main(){ BurstIndex b; return (int)b.get(); }'
try reject 'BurstIndex b = 5'            'int main(){ BurstIndex b = 5; return (int)b.get(); }'
try reject 'int32 from BurstIndex'       'std::int32_t f(){ return BurstIndex{5}; } int main(){ return (int)f(); }'
# int32 like CoreId, per B5s width convention, so an int64 narrows and the
# constrained constructor removes the overload rather than truncating.
try reject 'int64 lvalue into a BurstIndex' 'int main(){ std::int64_t v = 5; BurstIndex b{v}; return (int)b.get(); }'
try accept 'BurstIndex{5}'               'int main(){ BurstIndex b{5}; return (int)b.get(); }'
try accept 'BurstIndex == BurstIndex'    'int main(){ return BurstIndex{1} == BurstIndex{2}; }'
try accept 'BurstIndex copy construction' 'int main(){ BurstIndex a{5}; BurstIndex b{a}; return (int)b.get(); }'
try accept 'int32 lvalue into a BurstIndex' 'int main(){ std::int32_t n = 5; BurstIndex b{n}; return (int)b.get(); }'

section "== B2: EventSeq is not the other counter in the same key"
# The tenth tagged scalar, and its case is the adjacency: 3.6 keys events on
# `(time, class, effective_age, core_id, seq)`, whose THIRD field is a refusal
# stamp and whose FIFTH is this. Both are monotonic int64 counters, so an
# implementation that compared them in the wrong order would be comparing two
# counters of the same width and would produce a plausible, wrong, and perfectly
# reproducible event order. They count different things: a refusal stamp is
# written once per REQUEST at its first refusal, this once per EVENT.
try reject 'EventSeq == RefusalOrder'    'int main(){ return EventSeq{1} == RefusalOrder{1}; }'
try reject 'EventSeq < RefusalOrder'     'int main(){ return EventSeq{1} < RefusalOrder{1}; }'
try reject 'RefusalOrder{EventSeq}'      'int main(){ RefusalOrder r{EventSeq{1}}; return (int)r.get(); }'
try reject 'EventSeq{RefusalOrder}'      'int main(){ EventSeq s{RefusalOrder{1}}; return (int)s.get(); }'
try reject 'EventSeq == SimTime'         'int main(){ return EventSeq{1} == SimTime{1}; }'
try reject 'EventSeq + EventSeq'         'int main(){ return (int)(EventSeq{1} + EventSeq{1}).get(); }'
try reject 'EventSeq s;'                 'int main(){ EventSeq s; return (int)s.get(); }'
try reject 'EventSeq s = 5'              'int main(){ EventSeq s = 5; return (int)s.get(); }'
try reject 'int64 from EventSeq'         'std::int64_t f(){ return EventSeq{5}; } int main(){ return (int)f(); }'
try accept 'EventSeq{5}'                 'int main(){ EventSeq s{5}; return (int)s.get(); }'
try accept 'EventSeq < EventSeq'         'int main(){ return EventSeq{1} < EventSeq{2}; }'
try accept 'EventSeq from an int64 lvalue' 'int main(){ std::int64_t v = 5; EventSeq s{v}; return (int)s.get(); }'

section "== B1: Port takes two SimTimes and hands back an accept time"
tryPort accept 'Port constructed'        'int main(){ Port p(SimTime{1}, SimTime{0}); return (int)p.ii().get(); }'
# No default construction: a Port with no numbers is one whose `ii` and
# `latency` nobody chose, and both are config fields (2.5b).
tryPort reject 'Port p;'                 'int main(){ Port p; (void)p; return 0; }'
tryPort reject 'Port with one argument'  'int main(){ Port p(SimTime{1}); (void)p; return 0; }'
tryPort reject 'Port from raw ints'      'int main(){ Port p(1, 0); (void)p; return 0; }'
# N12 at this unit's surface. A latency is a SimTime, not a trace-local tick:
# Part 5 keeps ONE clock by removing absolute trace time from the design, and a
# LocalTick reaching a port is exactly where the two would rejoin.
tryPort reject 'latency is a LocalTick'  'int main(){ Port p(SimTime{1}, LocalTick{0}); (void)p; return 0; }'
tryPort reject 'ii is a LocalTick'       'int main(){ Port p(LocalTick{1}, SimTime{0}); (void)p; return 0; }'
tryPort reject 'ii is a RefusalOrder'    'int main(){ Port p(RefusalOrder{1}, SimTime{0}); (void)p; return 0; }'
tryPort reject 'reserve takes a raw int' 'int main(){ Port p(SimTime{1}, SimTime{0}); return (int)p.reserve(5).get(); }'
tryPort reject 'reserve takes a LocalTick' 'int main(){ Port p(SimTime{1}, SimTime{0});
  return (int)p.reserve(LocalTick{5}).get(); }'
tryPort accept 'reserve takes a SimTime' 'int main(){ Port p(SimTime{1}, SimTime{0});
  return (int)p.reserve(SimTime{5}).get(); }'
# The accept time does not fall out of its type on the way back, which is what
# keeps `accept + latency` (3.4s own spelling) a SimTime rather than an int.
tryPort reject 'int64 from reserve'      'int main(){ Port p(SimTime{1}, SimTime{0});
  std::int64_t t = p.reserve(SimTime{0}); return (int)t; }'
tryPort accept 'accept + latency'        'int main(){ Port p(SimTime{1}, SimTime{7});
  return (int)(p.reserve(SimTime{0}) + p.latency()).get(); }'
# `reserve` MUTATES the port: it advances `next_accept`. A const port therefore
# cannot reserve, which is the compile-time statement of "reservations are
# non-preemptive and are never released" -- there is no read-only way to ask.
tryPort reject 'reserve on a const Port' 'int main(){ const Port p(SimTime{1}, SimTime{0});
  return (int)p.reserve(SimTime{0}).get(); }'
tryPort accept 'the readers are const'   'int main(){ const Port p(SimTime{1}, SimTime{2});
  return (int)(p.ii().get() + p.latency().get() + p.next_accept().get()); }'
tryPort reject 'next_accept_ is private' 'int main(){ Port p(SimTime{1}, SimTime{0});
  return (int)p.next_accept_.get(); }'
# One port per resource, held in a container: the engine holds `l1_port[c]` over
# 8 to 256 cores (2.5b), so the class stays copyable as itself.
tryPort accept 'a vector of ports'       '#include <vector>
int main(){ std::vector<Port> v; v.push_back(Port(SimTime{1}, SimTime{0})); return (int)v.size(); }'

section "== B2: schedule owns the seq and the class, and cannot be told otherwise"
tryEvent accept 'a queue is scheduled and popped' 'int main(){ EventQueue<int> q;
  q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, 1);
  return q.pop_min().payload; }'
# 3.6s "assigned at SCHEDULE time" made unrepresentable rather than promised.
# Two events given the same seq would stop the order being total exactly where a
# tie needs breaking, and the only way to be sure of that is for the caller to
# have no way to supply one.
tryEvent reject 'schedule takes a seq'   'int main(){ EventQueue<int> q;
  q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, EventSeq{0}, 1); return 0; }'
# The class is DERIVED from the kind through class_of rather than passed, so a
# handler cannot schedule a fill under the probe class. That mutation reverses
# V23s worked example and reports a plausible, wrong, reproducible answer.
tryEvent reject 'schedule takes a class' 'int main(){ EventQueue<int> q;
  q.schedule(SimTime{0}, EventClass::Fill, NoRefusal, CoreId{0}, 1); return 0; }'
# The key's third and fifth fields are two int64 counters, so the two arguments
# that carry them must not be interchangeable at the call site either.
tryEvent reject 'an EventSeq where the age goes' 'int main(){ EventQueue<int> q;
  q.schedule(SimTime{0}, EventKind::Issue, EventSeq{0}, CoreId{0}, 1); return 0; }'
tryEvent reject 'a BurstIndex where the core goes' 'int main(){ EventQueue<int> q;
  q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, BurstIndex{0}, 1); return 0; }'
tryEvent reject 'a LocalTick where the time goes' 'int main(){ EventQueue<int> q;
  q.schedule(LocalTick{0}, EventKind::Issue, NoRefusal, CoreId{0}, 1); return 0; }'
# EventKey's five fields in the plans order, and the same swap on the struct.
tryEvent accept 'EventKey braced'        'int main(){ EventKey k{SimTime{1}, EventClass::Fill,
  RefusalOrder{1}, CoreId{0}, EventSeq{2}}; return (int)k.seq.get(); }'
tryEvent reject 'EventKey age and seq swapped' 'int main(){ EventKey k{SimTime{1},
  EventClass::Fill, EventSeq{1}, CoreId{0}, RefusalOrder{2}}; return (int)k.core.get(); }'
# The two enums are vocabulary, not arithmetic. class_of maps one to the other
# and neither decays to an int, so an event kind cannot be used as an index and
# a class cannot be handed back where a kind was wanted.
tryEvent reject 'class_of takes a class' 'int main(){ return (int)class_of(EventClass::Fill); }'
tryEvent reject 'int from an EventClass' 'int main(){ int c = class_of(EventKind::Issue); return c; }'
tryEvent reject 'EventClass in arithmetic' 'int main(){ return EventClass::Fill == 0; }'
tryEvent reject 'EventKind in arithmetic' 'int main(){ return (int)(EventKind::Issue + 1); }'
# class_of is constexpr, which is what lets a static dispatch table be built
# from it later without the 3.6 mapping being written a second time.
tryEvent accept 'class_of is constexpr' 'static_assert(class_of(EventKind::L1Fill) == EventClass::Fill, "");
int main(){ return 0; }'
# The payload is a template parameter because at B2 the hierarchy does not
# exist. A queue that only worked over an integer handle would be this unit
# deciding a later ones storage.
tryEvent accept 'a non-numeric payload'  '#include <string>
int main(){ EventQueue<std::string> q;
  q.schedule(SimTime{0}, EventKind::Issue, NoRefusal, CoreId{0}, std::string("x"));
  return (int)q.pop_min().payload.size(); }'
# pop_min mutates; the three readers do not.
tryEvent reject 'pop_min on a const queue' 'int main(){ const EventQueue<int> q;
  return q.pop_min().payload; }'
tryEvent accept 'the readers are const'  'int main(){ const EventQueue<int> q;
  return (int)(q.empty() ? q.size() + (std::size_t)q.now().get() + (std::size_t)q.scheduled() : 0); }'
tryEvent reject 'the heap is private'    'int main(){ EventQueue<int> q; return (int)q.q_.size(); }'

section "== B3: a Request carries three DIFFERENT ids, in one order"
tryMshr accept 'a demand request braced' 'int main(){ Request r{CoreId{0}, LineId{7}, BurstIndex{3}};
  return (int)r.line.get(); }'
tryMshr accept 'a prefetch request braced' 'int main(){ Request r{CoreId{0}, LineId{7},
  BurstIndex{3}, false}; return r.demand ? 1 : 0; }'
# THE case the ninth tagged scalar exists for, and the reason it is here rather
# than only in the types section above: this is the struct that puts a CoreId
# and a BurstIndex side by side, both int32, both small counts, so the swap is
# the accident the field order invites.
tryMshr reject 'Request core and burst swapped' 'int main(){ Request r{BurstIndex{0}, LineId{7},
  CoreId{3}}; return (int)r.line.get(); }'
tryMshr reject 'Request core and line swapped'  'int main(){ Request r{LineId{7}, CoreId{0},
  BurstIndex{3}}; return (int)r.line.get(); }'
# The first three fields have no defaults, so a forgotten initialiser cannot
# silently mean core 0 / line 0 / the first burst of the tile (B2s rule).
tryMshr reject 'Request r;'              'int main(){ Request r; return (int)r.line.get(); }'
tryMshr reject 'Mshr m;'                 'int main(){ Mshr m; return (int)m.line.get(); }'
tryMshr accept 'Mshr braced'             'int main(){ Mshr m{LineId{1}, CoreId{0}, true, {}, {}};
  return (int)m.targets.size(); }'
tryMshr reject 'Mshr line and core swapped' 'int main(){ Mshr m{CoreId{0}, LineId{1}, true, {}, {}};
  return (int)m.targets.size(); }'
# P5 as a compile-time fact: a wait index stores POINTERS because it selects
# over structures the engine already owns rather than buffering them. A vector
# of Requests here would have invented hardware, and 4.1s bound would become an
# argument about simulator memory instead of about credits.
tryMshr reject 'targets hold Requests by value' 'int main(){ Mshr m{LineId{1}, CoreId{0}, true,
  {}, {}}; Request r{CoreId{0}, LineId{1}, BurstIndex{0}}; m.targets.push_back(r);
  return (int)m.targets.size(); }'

section "== B3: MshrFile takes a counter, and speaks in ids"
tryMshr accept 'MshrFile constructed'    'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  return (int)f.capacity(); }'
# The counter is a REFERENCE parameter, one per run, shared by every file,
# because a request refused at the L1 and again at the L2 keeps its original
# stamp. A file that could be built without one would be a file with a private
# stamp sequence, and cross-level seniority would silently stop meaning
# anything (3.8).
tryMshr reject 'MshrFile without a counter' 'int main(){ MshrFile f(4, 2, 1); return (int)f.capacity(); }'
tryMshr reject 'MshrFile f;'             'int main(){ MshrFile f; return (int)f.capacity(); }'
tryMshr reject 'MshrFile takes a counter by value' 'int main(){ MshrFile f(4, 2, 1, RefusalCounter{});
  return (int)f.capacity(); }'
tryMshr reject 'find takes a raw int'    'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  return f.find(5) == nullptr; }'
tryMshr reject 'find takes a SlotId'     'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  return f.find(SlotId{5}) == nullptr; }'
tryMshr accept 'find takes a LineId'     'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  return f.find(LineId{5}) == nullptr; }'
# find is NOT const: the caller merges onto the entry it gets back.
tryMshr reject 'find on a const file'    'int main(){ RefusalCounter c; const MshrFile f(4, 2, 1, c);
  return f.find(LineId{5}) == nullptr; }'
tryMshr accept 'the readers are const'   'int main(){ RefusalCounter c; const MshrFile f(4, 2, 1, c);
  Request r{CoreId{0}, LineId{1}, BurstIndex{0}};
  return f.live() + f.reserved() + f.slot_wait_depth() + (f.has_slot(r) ? 1 : 0); }'
# `retire` fills a caller-owned buffer by non-const reference, which is what
# lets one buffer be reused across retires AND what stops a caller discarding a
# whole wake list into a temporary. The same wall A2d put around `expand`.
tryMshr reject 'retire into a temporary' 'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  Request r{CoreId{0}, LineId{1}, BurstIndex{0}}; Mshr& e = f.allocate(LineId{1}, r);
  f.retire(e, RetireResult{}); return 0; }'
tryMshr reject 'slot_wait_ is private'   'int main(){ RefusalCounter c; MshrFile f(4, 2, 1, c);
  return (int)f.slot_wait_.size(); }'
# A stamp is not a count. `next()` hands out a RefusalOrder and `issued()` a
# plain int64, and V18 compares one against the other, so the two must not be
# assignable to each other or that comparison stops meaning anything.
tryMshr accept 'a stamp is a RefusalOrder' 'int main(){ RefusalCounter c; RefusalOrder o = c.next();
  return (int)o.get(); }'
tryMshr accept 'issued is a plain count' 'int main(){ RefusalCounter c; std::int64_t n = c.issued();
  return (int)n; }'
tryMshr reject 'int64 from next()'       'int main(){ RefusalCounter c; std::int64_t s = c.next();
  return (int)s; }'
# Copy-initialisation, which is the ACCIDENTAL spelling: `RefusalOrder o =
# c.issued()` is a count silently becoming a stamp. The braced
# `RefusalOrder{c.issued()}` stays legal and is deliberately not tested as a
# reject, because both are int64 and no narrowing rule reaches it -- N12 asks
# that the mix be impossible by accident, not that it be impossible.
tryMshr reject 'RefusalOrder from issued()' 'int main(){ RefusalCounter c; RefusalOrder o = c.issued();
  return (int)o.get(); }'
# WaitReason and Level are both scoped uint8 enums declared in one header, so
# they are exactly the pair that could be passed for each other. mark_refused
# takes the reason.
tryMshr accept 'mark_refused takes a WaitReason' 'int main(){ RefusalCounter c;
  Request r{CoreId{0}, LineId{1}, BurstIndex{0}}; mark_refused(r, WaitReason::Slot, c);
  return (int)r.refusal.get(); }'
tryMshr reject 'mark_refused takes a Level' 'int main(){ RefusalCounter c;
  Request r{CoreId{0}, LineId{1}, BurstIndex{0}}; mark_refused(r, Level::L1, c); return 0; }'
tryMshr reject 'WaitReason == Level'     'int main(){ return WaitReason::Slot == Level::L1; }'
tryMshr reject 'int from a Level'        'int main(){ int l = Level::L2; return l; }'
tryMshr reject 'Level in arithmetic'     'int main(){ return (int)(Level::L1 + 1); }'
# The refusal stamp is a RefusalOrder on the request too, so a raw counter value
# cannot be written into it by hand and bypass mark_refuseds write-once rule.
tryMshr reject 'refusal assigned a raw int' 'int main(){ Request r{CoreId{0}, LineId{1},
  BurstIndex{0}}; r.refusal = 5; return (int)r.refusal.get(); }'

section "== B2 and B3: the two key_less overloads coexist"
# Both headers declare a free `key_less` in namespace wcache: 3.6s key over an
# EventKey, and 3.8s over a Request. The engine includes both, so this is the
# one question neither single-header preamble can ask, and the answer must be
# that each call resolves on its argument type rather than becoming ambiguous.
tryBoth accept 'both key_less overloads resolve' 'int main(){
  EventKey a{SimTime{1}, EventClass::Fill, RefusalOrder{1}, CoreId{0}, EventSeq{0}};
  EventKey b{SimTime{2}, EventClass::Fill, RefusalOrder{1}, CoreId{0}, EventSeq{1}};
  Request p{CoreId{0}, LineId{1}, BurstIndex{0}};
  Request q{CoreId{1}, LineId{2}, BurstIndex{0}};
  return (key_less(a, b) ? 1 : 0) + (key_less(p, q) ? 2 : 0); }'
# And they are not interchangeable: an EventKey is not a Request and neither
# comparison accepts the others population.
tryBoth reject 'key_less mixes the two keys' 'int main(){
  EventKey a{SimTime{1}, EventClass::Fill, RefusalOrder{1}, CoreId{0}, EventSeq{0}};
  Request p{CoreId{0}, LineId{1}, BurstIndex{0}};
  return key_less(a, p) ? 1 : 0; }'

# ---------------------------------------------------------------------------
# Phase C. Four contracts, chosen under decision B74's slimming rule: a
# compile-fail case earns its place only where it pins something a later reader
# could plausibly write. Restating "this type is tagged" once per new type is
# what that rule exists to stop, so the seven new types of Phase C get no cases
# at all and these four do.
#
# tryEngine: engine.h, which pulls in the whole hierarchy. There is no
# minimal-preamble claim to make here, unlike tryC or tryR: the engine is the
# thing that joins every unit, so a case compiled with it proves nothing about
# where a name came from and is not trying to.
# ---------------------------------------------------------------------------
tryEngine() { try "$1" "$2" "$3" '#include <wcache/engine.h>'; }

section "Phase C: the contracts a later reader could plausibly break"

# N12 survives `as_duration`. engine.h adds the ONE crossing from a trace
# spacing to a simulated duration, and the risk it creates is that a reader now
# believes the two clocks are comparable. They are not: the crossing produces a
# SimTime and nothing compares a SimTime with a LocalTick.
tryEngine reject 'C3 a SimTime is compared with a LocalTick' \
    'int f() { return as_duration(LocalTick{1}) < LocalTick{2} ? 1 : 0; }'
tryEngine accept 'C3 control: two SimTimes compare' \
    'int f() { return as_duration(LocalTick{1}) < SimTime{2} ? 1 : 0; }'

# 3.7's outcomes are five states "distinguished ONLY by what releases them", and
# the collapse the plan warns about starts with treating one of them as a
# success flag. An enum class is what makes `if (triage(...))` a compile error
# rather than a reading of Hit as false.
tryEngine reject 'C1 a TriageOutcome is used as a condition' \
    'int f(TriageOutcome o) { return o ? 1 : 0; }'
tryEngine accept 'C1 control: a TriageOutcome is compared' \
    'int f(TriageOutcome o) { return o == TriageOutcome::Hit ? 1 : 0; }'

# The engine owns a deque of requests that the MSHR entries, the wait indices
# and `Request::mshr1` all point into (P5). A copy would duplicate that arena
# and leave every pointer in the copy aimed at the original, which is a sweep
# driver holding two engines and getting one of them silently wrong. It is
# already impossible, and this is what keeps it impossible.
tryEngine reject 'C2 an Engine is copied' \
    'void f(Engine& e) { Engine c(e); (void)c; }'
tryEngine accept 'C2 control: an Engine is referred to' \
    'void f(Engine& e) { Engine& r = e; (void)r; }'

# 4.6: "One hook, called from E_Issue, returning NOTHING", and that is the whole
# of "the PE is not changed": C5 is reachable from the core only through a call
# that cannot affect it. A policy that wanted to report something back is the
# plausible violation, and it is refused at the override rather than at the call.
tryEngine reject 'C5 a prefetcher reports back from its hook' \
    'struct P : Prefetcher {
       bool on_demand_issue(PrefetchIssuer&, CoreId, BurstIndex, SimTime) override { return true; }
       void on_tile_start(CoreId) override {} };
     int f() { P p; (void)p; return 0; }'
tryEngine accept 'C5 control: a prefetcher that returns nothing' \
    'struct P : Prefetcher {
       void on_demand_issue(PrefetchIssuer&, CoreId, BurstIndex, SimTime) override {}
       void on_tile_start(CoreId) override {} };
     int f() { P p; (void)p; return 0; }'

# Every case has been started; wait for the stragglers, then print the whole
# run in source order and tally it. The tally is done here rather than in the
# children on purpose: a child is a separate process and cannot increment the
# parent's counters, so a version that counted as it went would report zero
# failures however many there were.
wait

for i in $(seq 1 "$seq_no"); do
    [ -f "$TMP/out.$i" ] && cat "$TMP/out.$i"
    if [ -f "$TMP/v.$i" ]; then
        if [ "$(cat "$TMP/v.$i")" = pass ]; then
            pass=$((pass + 1))
        else
            fail=$((fail + 1))
        fi
    fi
done

echo
echo "$((pass + fail)) compile cases, $fail failures"
[ "$fail" -eq 0 ]
