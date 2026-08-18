#!/usr/bin/env bash
# Plan Part 7: "tests pass" is not the exit criterion, "tests fail when the
# code is wrong" is. The v1 effort learned that 125 passing checks hid 6 live
# mutations.
#
# Each case below breaks one library header in one specific way and expects
# `make test` to fail. A mutation that SURVIVES means the suite does not cover
# that behaviour, and is a finding, not a warning to be tuned away.
#
# A2a's cases are killed mostly at compile time rather than by a failing check,
# because A2a is an interface and its content IS its shape. That is not a
# weaker result than a red assertion: `make test` going red is `make test`
# going red, and a signature that silently changed would otherwise reach every
# future mapper.
#
# Some mutations are expected to survive for a stated reason. Those are listed
# as `allow` and must carry the reason; an unexplained survivor fails the run.

set -u
cd "$(dirname "$0")/.."

# Two mutations below leave a block size of zero in place, so the test binary
# divides by zero and dies on SIGFPE. That is a kill and is the point, but the
# default core limit turns each one into a multi-megabyte core file next to the
# Makefile. Dropping the limit for this script's children only.
ulimit -c 0 2>/dev/null || true

# Every library file with content that can be wrong, so a unit whose file is not
# listed cannot be mutation tested by accident-of-omission. That is now both
# headers and sources: A2b is the first unit with a .cpp, and its constructor is
# where every layout invariant is established. All of them are restored before
# each case, not just the one being mutated, so a case can never inherit the
# previous case's damage. Basenames are unique across the list, which is what
# lets one flat backup directory hold them.
FILES="include/wcache/types.h include/wcache/layout.h include/wcache/block_pack.h src/block_pack.cpp"
BAKDIR=$(mktemp -d)
for f in $FILES; do cp "$f" "$BAKDIR/$(basename "$f")"; done
restore() { for f in $FILES; do cp "$BAKDIR/$(basename "$f")" "$f"; done; }
trap 'restore; rm -rf "$BAKDIR"' EXIT

# An optional argument runs only the cases whose mutated file path OR case name
# contains it, so the suite can be worked in parts: each case costs one full
# `make test`, and the whole set is long enough to matter on a login node with a
# CPU cap. It is also how a single case is re-run when a test is being checked
# for whether it is load-bearing. The default is every case, and a filtered run
# says how many it skipped on the summary line so it cannot be read as a clean
# full run.
FILTER=${1:-}
skipped=0

killed=0
survived=0
unexpected=0

# mutate_in <header> <expect: kill|allow> <name> <sed-expression> [reason-if-allow]
mutate_in() {
    local hdr=$1 expect=$2 name=$3 expr=$4 reason=${5:-}

    case "$hdr|$name" in
        *"$FILTER"*) ;;
        *) skipped=$((skipped + 1)); return ;;
    esac

    restore
    sed -i "$expr" "$hdr"

    if ! cmp -s "$BAKDIR/$(basename "$hdr")" "$hdr"; then
        :
    else
        printf '  ERROR     %-42s sed matched nothing; the mutation is not real\n' "$name"
        unexpected=$((unexpected + 1))
        return
    fi

    if make test >/dev/null 2>&1; then
        # suite passed, so the mutation was NOT detected
        if [ "$expect" = allow ]; then
            survived=$((survived + 1))
            printf '  survived  %-42s expected: %s\n' "$name" "$reason"
        else
            unexpected=$((unexpected + 1))
            printf '  SURVIVED  %-42s NOT DETECTED by the suite\n' "$name"
        fi
    else
        if [ "$expect" = allow ]; then
            unexpected=$((unexpected + 1))
            printf '  killed    %-42s but was expected to survive; update the reason\n' "$name"
        else
            killed=$((killed + 1))
            printf '  killed    %-42s\n' "$name"
        fi
    fi
}

# The A1 cases were written before there was a second header, so `mutate`
# stays spelled the way they use it.
mutate() { mutate_in include/wcache/types.h "$@"; }
mutate_layout() { mutate_in include/wcache/layout.h "$@"; }
mutate_pack_h() { mutate_in include/wcache/block_pack.h "$@"; }
mutate_pack() { mutate_in src/block_pack.cpp "$@"; }

echo "== comparison operators"
mutate kill '<= becomes <'   's|operator<=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() <= b|operator<=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() < b|'
mutate kill '>= becomes >'   's|operator>=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() >= b|operator>=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() > b|'
mutate kill '<  becomes <='  's|operator<(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() < b|operator<(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() <= b|'
mutate kill '>  becomes >='  's|operator>(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() > b|operator>(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() >= b|'
mutate kill '== becomes !='  's|operator==(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() == b|operator==(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() != b|'
mutate kill '!= becomes =='  's|operator!=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() != b|operator!=(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b) { return a.get() == b|'

echo "== arithmetic"
mutate kill 'SimTime + becomes -'      's|operator+(SimTime a, SimTime b) { return SimTime{a.get() + b|operator+(SimTime a, SimTime b) { return SimTime{a.get() - b|'
mutate kill 'SimTime - becomes +'      's|operator-(SimTime a, SimTime b) { return SimTime{a.get() - b|operator-(SimTime a, SimTime b) { return SimTime{a.get() + b|'
mutate kill 'LocalTick + becomes -'    's|operator+(LocalTick a, LocalTick b) { return LocalTick{a.get() + b|operator+(LocalTick a, LocalTick b) { return LocalTick{a.get() - b|'
mutate kill '+= drops the accumulate'  's|operator+=(SimTime\& a, SimTime b) { a = a + b|operator+=(SimTime\& a, SimTime b) { a = b|'
mutate kill 'the Part 5 crossing subtracts' 's|return SimTime{origin.get() + offset.get()};|return SimTime{origin.get() - offset.get()};|'

echo "== sentinels"
mutate kill 'NoSlot becomes 0'          's|inline constexpr SlotId NoSlot{INT32_MAX};|inline constexpr SlotId NoSlot{0};|'
mutate kill 'NoRefusal becomes INT64_MIN' 's|inline constexpr RefusalOrder NoRefusal{INT64_MAX};|inline constexpr RefusalOrder NoRefusal{INT64_MIN};|'
mutate kill 'NoRefusal becomes 0'       's|inline constexpr RefusalOrder NoRefusal{INT64_MAX};|inline constexpr RefusalOrder NoRefusal{0};|'

echo "== the type wall itself (killed by compile_fail.sh, not the binary)"
mutate kill 'explicit dropped'          's|constexpr explicit Tagged(Rep v)|constexpr Tagged(Rep v)|'
mutate kill 'default ctor restored'     's|Tagged() = delete;|constexpr Tagged() : v_(0) {}|'
mutate kill 'a conversion out is added' 's|constexpr Rep get() const { return v_; }|constexpr Rep get() const { return v_; }\n    constexpr operator Rep() const { return v_; }|'

# A constant hash is a *correct* hash, only a slow one, so this mutation was
# predicted to survive. It does not, because test_hash pins the stronger
# property that a Tagged hashes exactly as its payload (the tag carries nothing
# at run time). That test is deliberate, so the expectation here is `kill`.
echo "== hashing"
mutate kill 'hash returns a constant'   's|return hash<Rep>{}(v.get());|return 0;|'

echo "== A1b: the axis accessors"
mutate kill 'coord_on CIN reads cout'   's|case Axis::CIN:  return c.cin;|case Axis::CIN:  return c.cout;|'
mutate kill 'coord_on KH reads kw'      's|case Axis::KH:   return c.kh;|case Axis::KH:   return c.kw;|'
mutate kill 'extent_on KW reads KH'     's|case Axis::KW:   return shape.KW;|case Axis::KW:   return shape.KH;|'
mutate kill 'extent_on COUT reads CIN'  's|case Axis::COUT: return shape.COUT;|case Axis::COUT: return shape.CIN;|'
mutate kill 'with_coord_on COUT writes cin' 's|case Axis::COUT: c.cout = v; return c;|case Axis::COUT: c.cin  = v; return c;|'
mutate kill 'with_coord_on KW writes kh' 's|case Axis::KW:   c.kw   = v; return c;|case Axis::KW:   c.kh   = v; return c;|'
mutate kill 'axis_name CIN says COUT'   's|case Axis::CIN:  return "CIN";|case Axis::CIN:  return "COUT";|'

# The nesting order A2 flattens in. Renumbering the enumerators leaves every
# accessor correct and every line id wrong, so it is pinned numerically.
mutate kill 'Axis CIN and COUT swap'    's|enum class Axis : std::uint8_t { KH = 0, KW = 1, CIN = 2, COUT = 3 };|enum class Axis : std::uint8_t { KH = 0, KW = 1, COUT = 2, CIN = 3 };|'
# Widening the underlying type is not wrong on its own; it is pinned because
# the unknown-axis test casts an out-of-range value into it, which is
# well-defined only while the type is fixed.
mutate kill 'Axis underlying type freed' 's|enum class Axis : std::uint8_t {|enum class Axis {|'

echo "== A1b: refusing to invent an answer"
mutate kill 'coord_on falls back to 0'  's|throw std::logic_error("coord_on: unknown Axis");|return 0;|'
mutate kill 'extent_on falls back to 0' 's|throw std::logic_error("extent_on: unknown Axis");|return 0;|'
mutate kill 'with_coord_on falls back'  's|throw std::logic_error("with_coord_on: unknown Axis");|return c;|'
mutate kill 'axis_name falls back'      's|throw std::logic_error("axis_name: unknown Axis");|return "?";|'

# ---------------------------------------------------------------------------
# A2a: Placement and the AddressMapper interface
#
# A2a has no executable code, so there is no arithmetic to invert and no branch
# to flip. What CAN be mutated is the shape of the interface itself: a field
# type, a field order, a const, a return type, the virtual on the destructor,
# the `= 0` that makes a member pure. Those are the whole content of the unit,
# and every one of them is a change that would compile against a naive test
# suite and silently alter what every future mapper means.
#
# Most of these are killed at compile time rather than by a failing check, and
# that is not a weaker result: the suite going red is the suite going red. The
# ones killed by a static_assert in test_layout.cpp are marked; the ones killed
# by a real check are the field order and the destructor.
# ---------------------------------------------------------------------------
echo "== A2a: Placement's shape"
# Both fields are int64 so that `line == tag * num_sets + set_index` holds
# without a cast. Narrowing set_index makes the identity a 32-bit truncation
# for any array with more sets than fit, which is silent.
mutate_layout kill 'set_index narrowed to int32' 's|    std::int64_t set_index;|    std::int32_t set_index;|'
# Unsigned tag makes `0 <= set_index` vacuous on the sibling field and reopens
# the v1 line_of bug class (decision B5).
mutate_layout kill 'tag made unsigned'           's|    std::int64_t tag;|    std::uint64_t tag;|'
# Field ORDER, which is the one a reader cannot see: locate returns a braced
# Placement, so swapping the declarations swaps every mapper's answer without
# touching a single call site. Killed by the conformance identity check, not by
# a static_assert.
mutate_layout kill 'set_index and tag swap' \
    's|    std::int64_t set_index;  // in \[0, num_sets)|    std::int64_t tag_SWAP_;|; s|    std::int64_t tag;|    std::int64_t set_index;|; s|    std::int64_t tag_SWAP_;|    std::int64_t tag;|'

echo "== A2a: the interface stays an interface"
# Deleting a derived mapper through an AddressMapper* is what the engine does.
# A non-virtual destructor there is undefined behaviour whose usual symptom is
# a leak, so nothing but a deliberate probe announces it.
mutate_layout kill 'destructor made non-virtual'  's|virtual ~AddressMapper() = default;|~AddressMapper() = default;|'
# A pure virtual given a body makes AddressMapper concrete: `AddressMapper m;`
# starts compiling, and a mapper with no layout at all becomes constructible.
mutate_layout kill 'expand given a default body'  's|virtual void expand(const Burst\& b, std::vector<LineId>\& out) const = 0;|virtual void expand(const Burst\& b, std::vector<LineId>\& out) const {}|'
mutate_layout kill 'locate given a default body'  's|virtual Placement locate(LineId line, std::int64_t num_sets) const = 0;|virtual Placement locate(LineId line, std::int64_t num_sets) const { return Placement{0, 0}; }|'

echo "== A2a: the signature is the contract"
# const on the pure virtuals means no implementation can mutate the mapper
# while answering a query, which is what lets one instance serve L1 and L2.
mutate_layout kill 'expand loses its const'       's|std::vector<LineId>\& out) const = 0;|std::vector<LineId>\& out) = 0;|'
mutate_layout kill 'locate loses its const'       's|locate(LineId line, std::int64_t num_sets) const = 0;|locate(LineId line, std::int64_t num_sets) = 0;|'
# The out parameter by value is the append contract erased at the type level:
# every caller would silently get nothing back.
mutate_layout kill 'expand takes out by value'    's|std::vector<LineId>\& out) const = 0;|std::vector<LineId> out) const = 0;|'
# N12 at the boundary: a raw int64 line and a LineId are the same bits and
# different quantities, and locate is where a set index gets computed from one.
mutate_layout kill 'locate takes a raw int64'     's|locate(LineId line, std::int64_t num_sets)|locate(std::int64_t line, std::int64_t num_sets)|'
mutate_layout kill 'num_lines returns a raw int64' 's|virtual LineId num_lines() const = 0;|virtual std::int64_t num_lines() const = 0;|'
mutate_layout kill 'line_size_bytes narrowed'     's|virtual std::int64_t line_size_bytes() const = 0;|virtual std::int32_t line_size_bytes() const = 0;|'

# ---------------------------------------------------------------------------
# A2b: BlockPackMapper's construction and validation
#
# The first unit with executable code, so unlike A2a these are mostly killed by
# a failing check rather than by the compiler. Three families:
#
#   the validations   a check that stops firing, or fires on the wrong side of
#                     its boundary, or reports a message nobody can act on
#   the arithmetic    the ceiling, the two block counts, and the two products
#   the tripwires     the A2d stubs quietly given a body, which is the one
#                     failure in this unit that produces no wrong number at all
# ---------------------------------------------------------------------------
echo "== A2b: the extent checks"
# The boundary, not the sign. `< 1` and `< 0` agree on every negative value and
# disagree only at zero, which is the value a config loader that forgot a field
# actually produces.
mutate_pack kill 'extent check accepts 0'   's|if (n < 1) {|if (n < 0) {|'
# All four extents are radices in the flatten, so dropping one is a whole axis
# left unvalidated. Two cases, on the two that are easiest to believe are
# harmless: KW because it is not blocked, COUT because it is last.
mutate_pack kill 'KW dropped from the loop'   's|constexpr Axis kAxes\[4\] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};|constexpr Axis kAxes[4] = {Axis::KH, Axis::KH, Axis::CIN, Axis::COUT};|'
mutate_pack kill 'COUT dropped from the loop' 's|constexpr Axis kAxes\[4\] = {Axis::KH, Axis::KW, Axis::CIN, Axis::COUT};|constexpr Axis kAxes[4] = {Axis::KH, Axis::KW, Axis::CIN, Axis::CIN};|'

echo "== A2b: the block and element checks"
mutate_pack kill 'positive_or_reject accepts 0' 's|if (v < 1) reject|if (v < 0) reject|'
mutate_pack kill 'cin_block unchecked'    '/positive_or_reject("cin_block", cin_block);/d'
mutate_pack kill 'cout_block unchecked'   '/positive_or_reject("cout_block", cout_block);/d'
# weight_bytes is not a layout radix, which is exactly why it is the one a
# reader would believe is safe to skip. A zero makes line_size_bytes zero and
# D1 divides cache_size_bytes by it.
mutate_pack kill 'weight_bytes unchecked' '/positive_or_reject("weight_bytes", weight_bytes);/d'

echo "== A2b: the message is part of the contract"
# N11 asks that a range failure be diagnosable. A message that only restates the
# rule is what v1 shipped, and it does not say which parameter or what it held.
mutate_pack kill 'the offending value is dropped' 's|" must be >= 1, got " + std::to_string(v)|" must be >= 1"|'
mutate_pack kill 'the parameter name is dropped'  's|reject(std::string(name) + " must be >= 1|reject(std::string("a parameter") + " must be >= 1|'
mutate_pack kill 'the axis name is dropped'       's|reject(std::string(axis_name(a)) + " extent must be >= 1|reject(std::string("an") + " extent must be >= 1|'
# One spelling of the prefix is what makes every message this class produces
# findable by the class name.
mutate_pack kill 'the prefix is dropped'          's|throw std::invalid_argument("BlockPackMapper: " + what);|throw std::invalid_argument(what);|'
# A bad configuration is invalid_argument. A2d'"'"'s range failures will be
# out_of_range, and the two must stay tellable apart at the catch site.
mutate_pack kill 'rejection type changed'         's|throw std::invalid_argument("BlockPackMapper: " + what);|throw std::runtime_error("BlockPackMapper: " + what);|'

echo "== A2b: the ceiling"
# A short final block still occupies a whole line. A floor drops it, and on the
# corpus that is COUT 64 at cout_block 128 becoming zero lines.
mutate_pack kill 'ceiling becomes floor'  's|return (static_cast<std::int64_t>(extent) + block - 1) / block;|return static_cast<std::int64_t>(extent) / block;|'
# The other side: a rounding term that over-counts is invisible to any suite
# whose extents never divide exactly.
mutate_pack kill 'ceiling over-counts'    's|(static_cast<std::int64_t>(extent) + block - 1) / block|(static_cast<std::int64_t>(extent) + block) / block|'

echo "== A2b: the two block counts"
# num_lines is a product, so swapping the two counts leaves it unchanged. These
# three are the reason n_cin_blocks() and n_cout_blocks() are exposed at all.
mutate_pack kill 'n_cin_blocks measures COUT'  's|n_cin_blocks_  = blocks_covering(shape.CIN, cin_block);|n_cin_blocks_  = blocks_covering(shape.COUT, cin_block);|'
mutate_pack kill 'n_cout_blocks uses cin_block' 's|n_cout_blocks_ = blocks_covering(shape.COUT, cout_block);|n_cout_blocks_ = blocks_covering(shape.COUT, cin_block);|'
mutate_pack kill 'the two block counts swap'   's|n_cin_blocks_  = blocks_covering(shape.CIN, cin_block);|n_cout_blocks_ = blocks_covering(shape.CIN, cin_block);|; s|n_cout_blocks_ = blocks_covering(shape.COUT, cout_block);|n_cin_blocks_  = blocks_covering(shape.COUT, cout_block);|'

echo "== A2b: the two products"
mutate_pack kill 'line_size drops weight_bytes' 's|weight_bytes, "line_size_bytes")|1, "line_size_bytes")|'
# line_size_bytes is a function of the three layout parameters ONLY. Reading the
# shape makes L1 and L2 a different cache for every layer, and makes the size
# axis of the sweep incomparable across layers.
mutate_pack kill 'line_size reads the shape'    's|checked_mul(cin_block, cout_block, "line_size_bytes")|checked_mul(shape.CIN, cout_block, "line_size_bytes")|'
mutate_pack kill 'num_lines drops KW'           's|checked_mul(shape.KH, shape.KW, "num_lines")|checked_mul(shape.KH, 1, "num_lines")|'
mutate_pack kill 'num_lines drops n_cin_blocks'  's|n_cin_blocks_, "num_lines")|1, "num_lines")|'
mutate_pack kill 'num_lines drops n_cout_blocks' 's|n_cout_blocks_, "num_lines");|1, "num_lines");|'

echo "== A2b: the overflow guards"
# num_lines_ is the bound every later range check is written against, so a
# wrapped one is worse than a wrong one.
mutate_pack kill 'the guard never fires'     's|if (b > INT64_MAX / a) {|if (b > INT64_MAX) {|'
# The guard is a boundary, not a blanket rejection of large inputs: `>=` rejects
# the largest product that actually fits.
mutate_pack kill 'the guard is off by one'   's|if (b > INT64_MAX / a) {|if (b >= INT64_MAX / a) {|'
mutate_pack kill 'checked_mul drops a factor' 's|    return a \* b;|    return a;|'

echo "== A2b: the A2d tripwires"
# A stub that returns instead of throwing is the one failure in this unit with
# no wrong number attached: an empty expand appends nothing and reads exactly
# like a burst that touched no lines, so a caller wired up early runs to
# completion and reports a hit rate.
mutate_pack kill 'expand stub stops throwing' 's|throw std::logic_error("BlockPackMapper::expand is not implemented yet (increment A2d)");|return;|'
mutate_pack kill 'locate stub stops throwing' 's|throw std::logic_error("BlockPackMapper::locate is not implemented yet (increment A2d)");|return Placement{0, 0};|'
# logic_error, not invalid_argument: nothing is wrong with the argument, what is
# wrong is that the function was called at all.
mutate_pack kill 'the stubs throw invalid_argument' 's|throw std::logic_error("BlockPackMapper::|throw std::invalid_argument("BlockPackMapper::|'
# The increment the message names is what tells the next reader which unit owes
# the implementation, and it is what these two test cases match on.
mutate_pack kill 'the stub message loses A2d' 's|(increment A2d)|(later)|'

echo "== A2b: the header's derived state"
# B10 again, this time as the mutation rather than the compile-fail case.
mutate_pack_h kill 'BlockPackMapper loses final' 's|class BlockPackMapper final : public AddressMapper {|class BlockPackMapper : public AddressMapper {|'
# A line count and a byte count are both int64 members of the same object, one
# line apart.
mutate_pack_h kill 'num_lines reports the byte count' 's|return LineId{num_lines_};|return LineId{line_size_bytes_};|'
mutate_pack_h kill 'n_cin_blocks reports n_cout'      's|n_cin_blocks()   const { return n_cin_blocks_; }|n_cin_blocks()   const { return n_cout_blocks_; }|'
# A block count is a factor of a line count. Narrowing it is the mixed-width
# expression the v1 line_of bug lived in.
mutate_pack_h kill 'n_cin_blocks narrowed to int32'   's|std::int64_t       n_cin_blocks()   const { return n_cin_blocks_; }|std::int32_t       n_cin_blocks()   const { return static_cast<std::int32_t>(n_cin_blocks_); }|'

echo
echo "$((killed + survived + unexpected)) mutations: $killed killed, $survived survived as expected, $unexpected unexpected"
if [ -n "$FILTER" ]; then
    echo "FILTERED run: only files matching '$FILTER', $skipped cases skipped"
fi
[ "$unexpected" -eq 0 ]
