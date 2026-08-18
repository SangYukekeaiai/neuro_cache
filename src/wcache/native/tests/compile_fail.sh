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
# Eight rather than nproc (32 here). This is a shared login node, the win is
# most of the way in by eight, and a script that grabs every core is antisocial
# on a machine other people are working on. JOBS=n overrides it.
#
# What parallelism does NOT buy, stated because it is the thing to get wrong:
# the total CPU time is unchanged, and the NCSA Delta cap is on CPU time per
# process, not wall time. A faster sweep is not a legal unfiltered sweep.
JOBS=${JOBS:-8}

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
  Placement locate(LineId, std::int64_t) const override { return Placement{0, 0}; }
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
  Placement locate(LineId, std::int64_t) const override { return Placement{0, 0}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'
# Returning the lines instead of appending them is the shape the interface
# rejected (a caller accumulates a tick into one reused buffer), so it must not
# be reachable by accident.
tryL reject 'expand returns a vector' 'struct M : AddressMapper {
  std::vector<LineId> expand(const Burst&) const override { return {}; }
  Placement locate(LineId, std::int64_t) const override { return Placement{0, 0}; }
  LineId num_lines() const override { return LineId{1}; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'
# num_lines is a LineId, not a raw count: the bound the engine compares tags
# against is the same quantity as the ids it is bounding.
tryL reject 'num_lines returns int64' 'struct M : AddressMapper {
  void expand(const Burst&, std::vector<LineId>&) const override {}
  Placement locate(LineId, std::int64_t) const override { return Placement{0, 0}; }
  std::int64_t num_lines() const override { return 1; }
  std::int64_t line_size_bytes() const override { return 4; }
}; int main(){ M m; (void)m; }'

section "== A2a: N12 at the mapper boundary"
# locate takes a LineId, and Tagged's explicit constructor is what makes the
# raw-int spelling a compile error rather than a silent reinterpretation.
tryL reject 'locate(int)'      "$MAPPER int main(){ M m; return (int)m.locate(5, 8).tag; }"
tryL reject 'locate(SlotId)'   "$MAPPER int main(){ M m; return (int)m.locate(SlotId{1}, 8).tag; }"
tryL reject 'locate(SimTime)'  "$MAPPER int main(){ M m; return (int)m.locate(SimTime{1}, 8).tag; }"
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
tryP reject 'locate takes a raw int64'     "int main(){ $PACK return (int)m.locate(5, 8).tag; }"
tryP reject 'locate takes a SlotId'        "int main(){ $PACK return (int)m.locate(SlotId{1}, 8).tag; }"
# num_sets is a plain int64 and deliberately not a tagged scalar: it is a
# geometry of the ARRAY, not of the layout, which is why it is an argument
# rather than mapper state. A LineId there would be a line count standing in for
# a set count, which is exactly the confusion the wall exists to stop.
tryP reject 'locate num_sets is a LineId'  "int main(){ $PACK
  return (int)m.locate(LineId{0}, LineId{8}).tag; }"
# Placement's fields are raw int64 (B9), so they do not convert back into an id
# by copy-initialisation. The braced spelling IS allowed and is an accept case
# below, which is the B29 gap A4 closes; this case is the half that already
# holds today.
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
tryL accept 'locate(LineId, int64)'     "$MAPPER int main(){ M m; return (int)m.locate(LineId{5}, 8).set_index; }"
tryL accept 'num_lines is a LineId'     "$MAPPER int main(){ M m; LineId n = m.num_lines(); return (int)n.get(); }"
# The unwrap is explicit and therefore allowed: N12 asks that the mix be
# impossible by accident, not that it be impossible.
tryL accept 'explicit .get() unwrap'    "$MAPPER int main(){ M m;
  return m.num_lines().get() < m.line_size_bytes() ? 1 : 0; }"
tryL accept 'Placement braced'          'int main(){ Placement p{3, 100}; return (int)(p.tag + p.set_index); }'
# Decision B9: Placement holds raw int64 fields, not tagged scalars, so these
# compile on purpose. Recorded as accept cases so that a later unit tightening
# them has to come here and say so, and so that the size of the gap is written
# down rather than inferred.
#
# A4a closed the width half of the gap and only the width half, which is why
# this block still has three accepts under it. Tagged's constructor is now
# constrained to non-narrowing sources, so the 32-bit case below rejects. The
# two int64 -> int64 cases do NOT reject and no narrowing rule can ever make
# them: Placement::set_index and ::tag are raw int64, LineId and SimTime are
# int64, and the conversion loses nothing. What is wrong with them is the
# NAME, not the width, and closing them means typing Placement's fields
# (SetIndex set_index, a tagged tag), which is an A2 interface change nobody
# has ruled on. They stay accept, and they are the measure of what is left.
tryL accept 'set_index is a raw int64'  'int main(){ Placement p{3, 100}; std::int64_t s = p.set_index; return (int)s; }'
tryL accept 'a set index becomes a LineId' 'int main(){ Placement p{3, 100}; LineId l{p.set_index}; return (int)l.get(); }'
tryL accept 'a tag becomes a SimTime'      'int main(){ Placement p{3, 100}; SimTime t{p.tag}; return (int)t.get(); }'
# B29 discharged, half of it: int64 tag into a 32-bit SlotId is a narrowing and
# the constrained constructor removes the overload, so there is nothing to call.
tryL reject 'a 64-bit tag becomes a SlotId' 'int main(){ Placement p{3, 100}; SlotId s{p.tag}; return (int)s.get(); }'

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
  return (int)m.locate(LineId{0}, 8).set_index; }"
tryP accept 'locate through the base'      "int main(){ $PACK const AddressMapper& r = m;
  return (int)r.locate(LineId{0}, 8).tag; }"
tryP accept 'Placement from locate'        "int main(){ $PACK
  Placement p = m.locate(LineId{0}, 8); return (int)(p.tag + p.set_index); }"
# Still an accept after A4a, and now for a reason worth stating: set_index and
# LineId are both int64, so this conversion loses nothing and no narrowing rule
# can reject it. What is wrong with it is the NAME. Closing it means typing
# Placement's fields, an A2 interface change nobody has ruled on, so it stays
# here as the measure of what B29 did NOT close.
tryP accept 'a set index becomes a LineId' "int main(){ $PACK
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
