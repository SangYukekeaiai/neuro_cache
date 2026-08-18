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

# try <expect: reject|accept> <name> <body> [extra-include-line]
try() {
    local expect=$1 name=$2 body=$3 extra=${4:-}
    {
        echo '#include <wcache/types.h>'
        [ -n "$extra" ] && echo "$extra"
        echo '#include <cstdint>'
        echo 'using namespace wcache;'
        echo "$body"
    } > "$TMP/case.cpp"

    if $CXX $FLAGS "$TMP/case.cpp" 2>"$TMP/err"; then
        local got=accept
    else
        local got=reject
    fi

    if [ "$got" = "$expect" ]; then
        pass=$((pass + 1))
        printf '  ok        %-46s (%s)\n' "$name" "$expect"
    else
        fail=$((fail + 1))
        printf '  FAIL      %-46s expected %s, got %s\n' "$name" "$expect" "$got"
        [ "$got" = reject ] && sed -n '1,4p' "$TMP/err" | sed 's/^/            /'
    fi
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

# The one valid configuration every A2b case builds on, so a case that is meant
# to fail on a type cannot pass or fail on a bad extent instead.
SHAPE='WeightShape{3, 3, 256, 64}'

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

echo "== N12: the three time-like types do not mix"
try reject 'SimTime < LocalTick'        'int main(){ return SimTime{1} < LocalTick{1}; }'
try reject 'SimTime == RefusalOrder'    'int main(){ return SimTime{1} == RefusalOrder{1}; }'
try reject 'LocalTick == RefusalOrder'  'int main(){ return LocalTick{1} == RefusalOrder{1}; }'
try reject 'SimTime <= LocalTick'       'int main(){ return SimTime{1} <= LocalTick{1}; }'
try reject 'SimTime > RefusalOrder'     'int main(){ return SimTime{1} > RefusalOrder{1}; }'
try reject 'SimTime != LocalTick'       'int main(){ return SimTime{1} != LocalTick{1}; }'

echo "== the id types do not mix, with each other or with time"
try reject 'LineId == SlotId'           'int main(){ return LineId{1} == SlotId{1}; }'
try reject 'LineId == CoreId'           'int main(){ return LineId{1} == CoreId{1}; }'
try reject 'SlotId < CoreId'            'int main(){ return SlotId{1} < CoreId{1}; }'
try reject 'LineId < SimTime'           'int main(){ return LineId{1} < SimTime{1}; }'

echo "== arithmetic is closed except for the one crossing"
try reject 'LocalTick + SimTime (order)' 'int main(){ return (int)(LocalTick{1} + SimTime{1}).get(); }'
try reject 'SimTime - LocalTick'         'int main(){ return (int)(SimTime{1} - LocalTick{1}).get(); }'
try reject 'SimTime + RefusalOrder'      'int main(){ return (int)(SimTime{1} + RefusalOrder{1}).get(); }'
try reject 'RefusalOrder + RefusalOrder' 'int main(){ return (int)(RefusalOrder{1} + RefusalOrder{1}).get(); }'
try reject 'LineId + LineId'             'int main(){ return (int)(LineId{1} + LineId{1}).get(); }'
try reject 'SlotId + SlotId'             'int main(){ return (int)(SlotId{1} + SlotId{1}).get(); }'
try reject 'CoreId + CoreId'             'int main(){ return (int)(CoreId{1} + CoreId{1}).get(); }'
try reject 'SimTime += LocalTick'        'int main(){ SimTime a{1}; a += LocalTick{1}; return (int)a.get(); }'

echo "== no implicit conversion in or out (explicit constructor, no operator T)"
try reject 'SimTime t = 5'              'int main(){ SimTime t = 5; return (int)t.get(); }'
try reject 'int64 from SimTime'         'std::int64_t f(){ return SimTime{5}; } int main(){ return (int)f(); }'
try reject 'call f(SimTime) with int'   'void f(SimTime); int main(){ f(5); }'
try reject 'call f(LineId) with SlotId' 'void f(LineId); int main(){ f(SlotId{1}); }'
try reject 'SimTime a = LocalTick'      'int main(){ SimTime a{1}; a = LocalTick{2}; return (int)a.get(); }'
try reject 'return LocalTick as SimTime' 'SimTime f(){ return LocalTick{1}; } int main(){ return (int)f().get(); }'

echo "== decision B2: no default construction"
try reject 'SlotId s;'                  'int main(){ SlotId s; return (int)s.get(); }'
try reject 'SimTime t;'                 'int main(){ SimTime t; return (int)t.get(); }'
try reject 'vector<SlotId> v(4)'        '#include <vector>
int main(){ std::vector<SlotId> v(4); return (int)v.size(); }'
try reject 'struct member left out'     'struct S { int a; SimTime t; S(int x) : a(x) {} };
int main(){ S s(1); return (int)s.t.get(); }'

echo "== A1b: geometry, the distinctions that are kept"
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

echo "== A2a: AddressMapper is abstract and stays abstract"
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

echo "== A2a: the signature is the contract"
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

echo "== A2a: N12 at the mapper boundary"
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

echo "== A2b: BlockPackMapper is final and fully specified"
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

echo "== controls: these MUST compile, or every case above is vacuous"
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
# Decision B9 and the A4 carried obligation: Placement holds raw int64 fields,
# not tagged scalars, so these compile on purpose. Recorded as accept cases so
# that a later unit tightening them has to come here and say so, and so that
# the size of the gap is written down rather than inferred.
#
# The gap is wider than "an int64 comes out". Because Tagged's constructor is
# explicit but its argument is an ordinary function parameter, a braced
# Placement field converts into ANY tagged scalar, including a 32-bit one,
# where the conversion is a silent truncation. The last case is the one to
# look at when A4 adds SetIndex.
tryL accept 'set_index is a raw int64'  'int main(){ Placement p{3, 100}; std::int64_t s = p.set_index; return (int)s; }'
tryL accept 'a set index becomes a LineId' 'int main(){ Placement p{3, 100}; LineId l{p.set_index}; return (int)l.get(); }'
tryL accept 'a tag becomes a SimTime'      'int main(){ Placement p{3, 100}; SimTime t{p.tag}; return (int)t.get(); }'
tryL accept 'a 64-bit tag becomes a SlotId' 'int main(){ Placement p{3, 100}; SlotId s{p.tag}; return (int)s.get(); }'

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

echo
echo "$((pass + fail)) compile cases, $fail failures"
[ "$fail" -eq 0 ]
