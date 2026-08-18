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
# A4a adds include/wcache/cache.h. Listing it is not bookkeeping: the comment
# above is the rule, and a unit whose file is missing from this line is not
# mutation tested at all while the summary still reports a clean sweep, which
# is the same shape of silent lie the baseline guard below exists for.
# A4b adds include/wcache/set_associative.h and src/set_associative.cpp, which
# is B59's precedent applied to the file it was written about: cache.h was
# untestable from the moment it was created, so A4a's interface would have
# carried a clean sweep while nothing in it was ever mutated. A4b is a whole
# constructor of validation and would have done the same, at a larger size.
FILES="include/wcache/types.h include/wcache/layout.h include/wcache/block_pack.h include/wcache/cache.h include/wcache/set_associative.h src/block_pack.cpp src/set_associative.cpp"
BAKDIR=$(mktemp -d)
for f in $FILES; do cp "$f" "$BAKDIR/$(basename "$f")"; done
restore() { for f in $FILES; do cp "$BAKDIR/$(basename "$f")" "$f"; done; }
trap 'restore; rm -rf "$BAKDIR"' EXIT

# The baseline must be GREEN before a single case runs, and this check is the
# difference between a result and a rumour.
#
# Every case below judges a kill by `if make test; then survived`. That reads
# the suite's exit status as an answer about the MUTATION, which it only is
# when the unmutated tree passes. If the baseline is already red, `make test`
# fails for a reason that has nothing to do with the sed, every case takes the
# else branch, and the run reports a clean sweep of kills while testing
# nothing. The failure is silent and it inverts: the more broken the tree, the
# better the report looks.
#
# It is not hypothetical. A4a landed with two compile_fail.sh cases
# deliberately red (the accept->reject flip B29 called for), and in that state
# an intentional `allow`, unreachable by construction and therefore
# guaranteed to survive, was reported as `killed ... but was expected to
# survive`. That is this harness reporting the exact opposite of the truth.
#
# So the precondition is checked rather than assumed, once, before any
# mutation. One `make test` (about 17 s) buys every later line its meaning.
# Bounded parallelism for the builds this script drives. The compile-fail
# runner takes JOBS the same way, so one setting covers both halves of a case.
# Not nproc: this is a shared login node, and the cap that actually binds is on
# CPU time, which parallelism does not reduce.
JOBS=${JOBS:-8}
export JOBS

restore
printf 'baseline: '
if make -j"$JOBS" test >/dev/null 2>&1; then
    echo "green"
else
    echo "RED"
    echo
    echo "ERROR: the unmutated tree fails 'make test', so no mutation result from" >&2
    echo "this run would mean anything: every case would report 'killed' whether" >&2
    echo "the suite detects it or not. Fix the baseline, then re-run." >&2
    echo >&2
    echo "The failing baseline, in full:" >&2
    make -j"$JOBS" test 2>&1 | tail -30 >&2
    exit 2
fi
echo

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

    # Which suite can possibly see this mutation.
    #
    # compile_fail.sh compiles its cases with -fsyntax-only against include/ and
    # never links the library, so a mutation inside a .cpp cannot change any of
    # its 188 verdicts. Running it there is 188 g++ spawns that cannot report
    # anything, and it was the dominant cost of every .cpp case.
    #
    # Verified rather than assumed, because the whole sweep's meaning rests on
    # it: swapping locate's set index and tag in src/block_pack.cpp leaves
    # compile_fail.sh at 188 cases / 0 failures while turning `make test` red.
    # A header mutation still runs the full `make test`, since for several of
    # them the compile cases are the ONLY thing that catches them.
    local target=test
    case "$hdr" in
        *.cpp) target=test-run ;;
    esac

    if make -j"$JOBS" "$target" >/dev/null 2>&1; then
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
mutate_cache() { mutate_in include/wcache/cache.h "$@"; }
mutate_pack_h() { mutate_in include/wcache/block_pack.h "$@"; }
mutate_pack() { mutate_in src/block_pack.cpp "$@"; }
mutate_sa_h() { mutate_in include/wcache/set_associative.h "$@"; }
mutate_sa() { mutate_in src/set_associative.cpp "$@"; }

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
# A4a's sentinel. B3 says a sentinel sits at the TOP of its range so ordinary
# `<` puts it last; these are the two ways to break that. 0 makes line 0 look
# free, and INT64_MIN sorts a free slot FIRST, inverting any victim scan.
mutate kill 'A4a NoLine becomes 0'      's|inline constexpr LineId NoLine{INT64_MAX};|inline constexpr LineId NoLine{0};|'
mutate kill 'A4a NoLine becomes INT64_MIN' 's|inline constexpr LineId NoLine{INT64_MAX};|inline constexpr LineId NoLine{INT64_MIN};|'
# The seventh tagged type has to be its OWN tag. Pointing it at an existing one
# makes SetIndex an alias, and `policy.on_hit(SlotId{set_index})` compiles
# again, which is the exact accident A1a's carried obligation asked A4 to stop.
mutate kill 'A4a SetIndex aliases LineId' \
    's|using SetIndex = Tagged<std::int64_t, tags::set_index>;|using SetIndex = Tagged<std::int64_t, tags::line>;|'
mutate kill 'A4a SetIndex aliases SimTime' \
    's|using SetIndex = Tagged<std::int64_t, tags::set_index>;|using SetIndex = Tagged<std::int64_t, tags::sim_time>;|'

echo "== the type wall itself (killed by compile_fail.sh, not the binary)"
# Retargeted at A4a. This case used to read `constexpr explicit Tagged(Rep v)`,
# which A4a deleted: the constructor is now a constrained template taking U.
# The old expression matched nothing and the run reported `ERROR sed matched
# nothing`, which is the same rot B45 deleted four A2b cases for. It is
# retargeted rather than deleted, because what it pins is still true and still
# worth pinning: `explicit` is the half of the wall that stops the conversion
# nobody asked for, and it is orthogonal to the narrowing constraint below.
mutate kill 'explicit dropped'          's|constexpr explicit Tagged(U v)|constexpr Tagged(U v)|'
mutate kill 'default ctor restored'     's|Tagged() = delete;|constexpr Tagged() : v_(0) {}|'
mutate kill 'a conversion out is added' 's|constexpr Rep get() const { return v_; }|constexpr Rep get() const { return v_; }\n    constexpr operator Rep() const { return v_; }|'

# == A4a: the non-narrowing constraint itself (B29, U2)
#
# The three cases above pin the parts of the wall A1a built. These three pin
# the part A4a added, and they exist because the constraint is one mechanism
# spread over three lines of types.h: the trait, the enable_if_t that consumes
# it, and the ABSENCE of a plain Tagged(Rep) beside it. Break any one and the
# rule is gone, so a case that only covered the enable_if_t would leave two
# live ways to reopen exactly the gap B29 was raised for.
#
# All three are killed by the two compile_fail.sh cases A4a flipped from
# accept to reject, `a 64-bit tag becomes a SlotId` and `a stride becomes a
# SlotId`, which is what makes those flips load-bearing rather than
# bookkeeping.
#
# What each one is worth knowing: under every one of these mutations g++
# emits only a -Wnarrowing WARNING and compiles the truncation, and
# compile_fail.sh runs without -Werror. So the suite catches these by the
# constructor being GONE, never by the compiler objecting to the conversion.
mutate kill 'A4a the enable_if_t is dropped' \
    's|typename = std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>|typename = void|'
mutate kill 'A4a the trait always says yes' \
    's|struct converts_without_narrowing : std::false_type {};|struct converts_without_narrowing : std::true_type {};|'
# The third is the one that pins WHY the plain constructor had to be removed
# rather than shadowed by the constrained one. Restored beside it, with the
# historical `: v_(v)` spelling A1a used, an unconstrained Tagged(Rep) is the
# better match for a narrowing argument -- the conversion happens in the
# argument, where g++ only warns -- so the constrained template never gets
# consulted and the wall is back to where B29 found it. This case is the
# difference between "the constraint is present" and "the constraint is
# reachable".
mutate kill 'A4a the plain Tagged(Rep) is restored beside it' \
    's|    constexpr Rep get() const { return v_; }|    constexpr explicit Tagged(Rep v) : v_(v) {}\n    constexpr Rep get() const { return v_; }|'

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

# The four A2d tripwire mutations that used to sit here are gone with the stubs
# they mutated: they replaced the two `logic_error` bodies with a silent return
# and a plain Placement, which is the one A2b failure with no wrong number
# attached. A2d implemented both members, so those sed expressions now match
# nothing, and a case that matches nothing is reported as an ERROR by this
# script rather than passing quietly. The behaviour they guarded is guarded from
# here on by the A2d section at the end of this file, which mutates the real
# bodies instead.

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

# ---------------------------------------------------------------------------
# A2c: the four radices, line_stride, block_len and the flatten
#
# Every case below lives in src/block_pack.cpp, which A2b already occupies, so
# the file path no longer separates the two units. The names carry an `A2c`
# prefix instead and `./tests/mutation_check.sh A2c` runs exactly this section.
# That is not cosmetic: each case costs a full `make test`, and a login node
# with a CPU cap is the machine this is run on.
#
# Four families:
#
#   the radices     the four stride_ fills, where a swap leaves num_lines()
#                   unchanged because it is their product
#   the two helpers line_stride and block_len, including the arms that refuse
#                   an Axis outside the enumerators
#   the flatten     the division, the accumulate, and the block size each axis
#                   divides by
#   the range check B25, which is the only reason a negative coordinate is
#                   visible at all, plus the message and the exception type
# ---------------------------------------------------------------------------
echo "== A2c: the four radices"
# COUT at radix 1 is the whole of B22: it is what makes a COUT-walking burst a
# contiguous run of ids, and every trace in the corpus bursts along COUT. Any
# other value still gives a bijection onto SOME set of ids, so nothing crashes
# and only the set spreading changes.
mutate_pack kill 'A2c COUT radix is not 1' \
    's|stride_\[static_cast<int>(Axis::COUT)\] = 1;|stride_[static_cast<int>(Axis::COUT)] = 2;|'
# The classic swap. num_lines() is the product of the four radices, so reading
# n_cin_blocks_ where n_cout_blocks_ belongs leaves it untouched and is
# invisible on any shape where the two block counts agree.
mutate_pack kill 'A2c CIN radix reads n_cin_blocks' \
    's|stride_\[static_cast<int>(Axis::CIN)\]  = n_cout_blocks_;|stride_[static_cast<int>(Axis::CIN)]  = n_cin_blocks_;|'
mutate_pack kill 'A2c KW radix drops n_cin_blocks' \
    's|checked_mul(n_cin_blocks_, n_cout_blocks_, "KW line stride")|checked_mul(1, n_cout_blocks_, "KW line stride")|'
# F11's class, restated on the radices: with a square kernel KH and KW are
# interchangeable and nothing in the suite could tell them apart. The KH radix
# is the one that multiplies by the OTHER kernel extent.
mutate_pack kill 'A2c KH radix multiplies by KH' \
    's|checked_mul(shape.KW, stride_\[static_cast<int>(Axis::KW)\], "KH line stride")|checked_mul(shape.KH, stride_[static_cast<int>(Axis::KW)], "KH line stride")|'
# And the nesting itself: KH steps over a whole KW row of planes, so it is
# built from the KW radix. Built from the CIN one it steps over a plane
# instead, which is a smaller stride that still produces plausible ids.
mutate_pack kill 'A2c KH radix nests on CIN' \
    's|checked_mul(shape.KW, stride_\[static_cast<int>(Axis::KW)\], "KH line stride")|checked_mul(shape.KW, stride_[static_cast<int>(Axis::CIN)], "KH line stride")|'

echo "== A2c: line_stride and block_len"
# The lookup B24 exists for. A constant index compiles, answers, and is wrong
# for three axes out of four.
mutate_pack kill 'A2c line_stride reads slot 0' \
    's|            return stride_\[static_cast<int>(a)\];|            return stride_[0];|'
# The refusal arms. types.h set the precedent (refuse rather than invent), and
# here it is stronger than a convention: line_stride indexes stride_[4], so an
# answer for an out-of-enumerator Axis is what a read past the end of the
# object would look like.
mutate_pack kill 'A2c line_stride invents an answer' \
    's|throw std::logic_error("BlockPackMapper::line_stride: unknown Axis");|return 1;|'
mutate_pack kill 'A2c block_len invents an answer' \
    's|throw std::logic_error("BlockPackMapper::block_len: unknown Axis");|return 1;|'
# logic_error, not out_of_range: an Axis of 9 came from a cast, not from a
# range, and A2c is where the two failures first coexist on one object.
mutate_pack kill 'A2c unknown Axis becomes out_of_range' \
    's|throw std::logic_error("BlockPackMapper::line_stride: unknown Axis");|throw std::out_of_range("BlockPackMapper::line_stride: unknown Axis");|'
# block_len is the extent in LINES. Reporting the raw extent is the mistake its
# name invites, and B25 left it with no in-library caller until A2d, so nothing
# but its own test can see this.
mutate_pack kill 'A2c block_len CIN reports the extent' \
    's|        case Axis::CIN:  return n_cin_blocks_;|        case Axis::CIN:  return static_cast<std::int64_t>(shape_.CIN);|'
mutate_pack kill 'A2c block_len COUT reports n_cin' \
    's|        case Axis::COUT: return n_cout_blocks_;|        case Axis::COUT: return n_cin_blocks_;|'
mutate_pack kill 'A2c block_len KH reads KW' \
    's|        case Axis::KH:   return static_cast<std::int64_t>(shape_.KH);|        case Axis::KH:   return static_cast<std::int64_t>(shape_.KW);|'

echo "== A2c: the flatten"
# The division is what makes a line a BLOCK of elements. Without it every
# element of a tile gets its own id, num_lines() no longer bounds the result,
# and the hit rate collapses toward the no-reuse case.
mutate_pack kill 'A2c the flatten drops the divide' \
    's|line += static_cast<std::int64_t>(v / block) \* line_stride(a);|line += static_cast<std::int64_t>(v) * line_stride(a);|'
# An assignment instead of an accumulate keeps only the last axis, which is
# COUT at radix 1: every id then lands in [0, n_cout_blocks).
mutate_pack kill 'A2c the flatten overwrites' \
    's|line += static_cast<std::int64_t>(v / block) \* line_stride(a);|line = static_cast<std::int64_t>(v / block) * line_stride(a);|'
# The two block sizes exchanged. On the corpus cin_block and cout_block are
# swept independently, so this is a configuration that really occurs rather
# than a contrived one.
mutate_pack kill 'A2c CIN divides by cout_block' \
    's|        case Axis::CIN:  return cin_block;|        case Axis::CIN:  return cout_block;|'
# KH and KW are not blocked, and saying so as "their block size is 1" is what
# keeps line_of free of per-axis code. Giving them a real divisor collapses the
# three kernel rows onto one line.
mutate_pack kill 'A2c the kernel axes get a block size' \
    's|        case Axis::KW:   return 1;|        case Axis::KW:   return cin_block;|'

echo "== A2c: B25, the range check"
# The single most important mutation in this unit. Integer division truncates
# toward zero, so every cin in [-(cin_block - 1), -1] divides to block 0 and
# names a real line: dropping the lower half of the check produces an ordinary
# id from a bad coordinate and nothing downstream can tell.
mutate_pack kill 'A2c the range check drops the lower half' \
    's@if (v < 0 || v >= n) {@if (v >= n) {@'
mutate_pack kill 'A2c the range check never fires' \
    's@if (v < 0 || v >= n) {@if (false) {@'
# The boundary, not the direction: `v > n` accepts the one coordinate one past
# the last element, which is exactly what an off-by-one in a caller's loop
# produces.
mutate_pack kill 'A2c the range check is off by one' \
    's@if (v < 0 || v >= n) {@if (v < 0 || v > n) {@'
# B25's rejected alternative, written out. Checking the QUOTIENT against
# block_len is the change a later reader is most likely to make, because it
# looks like it removes a redundant bound. It accepts the whole padded tail
# (cin 100..127 at CIN 100, cin_block 32) and it accepts every negative
# coordinate that truncates to block 0. This case is what makes B25 a tested
# decision rather than a comment.
mutate_pack kill 'A2c the range check uses block_len' \
    's@if (v < 0 || v >= n) {@const std::int32_t q_ = v / block_size_on(a, cin_block_, cout_block_); if (q_ < 0 || q_ >= block_len(a)) {@'
# out_of_range, not invalid_argument: a bad configuration is found once at
# construction and a bad coordinate once per access while the trace replays,
# and B27's whole vocabulary is that a catch site can tell them apart.
mutate_pack kill 'A2c the range failure is invalid_argument' \
    's@throw std::out_of_range("BlockPackMapper: " + what);@throw std::invalid_argument("BlockPackMapper: " + what);@'
# N11 again, on the message this increment is the first in the tree to produce.
mutate_pack kill 'A2c the range message drops the prefix' \
    's@throw std::out_of_range("BlockPackMapper: " + what);@throw std::out_of_range(what);@'
mutate_pack kill 'A2c the range message drops the value' \
    's@"), got " + std::to_string(v)@")"@'
mutate_pack kill 'A2c the range message drops the axis' \
    's@std::string(axis_name(a)) + " coordinate out of range@std::string("a") + " coordinate out of range@'

# The one A2c line the suite cannot reach. block_size_on is file-local and
# line_of is its only caller, which walks kAxes, so no legal call can carry an
# Axis outside the enumerators into it. line_stride and block_len are public
# and their equivalent arms ARE reachable (two kills above); this one is not,
# and the honest record is a stated survivor rather than a case quietly left
# out of the list. It becomes reachable at A2d only if expand or locate ever
# reaches block_size_on with an axis read from a burst.
mutate_pack allow 'A2c block_size_on invents an answer' \
    's@throw std::logic_error("BlockPackMapper: unknown Axis in block_size_on");@return 1;@' \
    'block_size_on is file-local and line_of, its only caller, walks kAxes'

# ---------------------------------------------------------------------------
# A2d: expand and locate
#
# Same file as A2b and A2c, so the path no longer separates the units and the
# names carry an `A2d` prefix instead: `./tests/mutation_check.sh A2d` runs
# exactly this section. Each case costs a full `make test` and the login node
# this runs on has a 30-minute CPU cap, so the filter is the difference between
# a check that can be run and one that is described.
#
# Four families:
#
#   the count check   B38, where the tier of the exception is as much of the
#                     contract as the refusal is
#   the far end       the one thing in expand that int64 arithmetic buys, and
#                     the only part of it a walk over line_of does not already
#                     cover
#   the walk          the sort, the de-duplication, and the append, which are
#                     B31 and layout.h's accumulate pattern
#   locate            the range check that runs BEFORE the division, and the
#                     identity `line == tag * num_sets + set_index`
# ---------------------------------------------------------------------------
echo "== A2d: B38, the count check"
# The boundary, not the sign. `< 1` and `< 0` agree on every negative count and
# disagree only at zero, which is the count an empty burst list produces.
mutate_pack kill 'A2d the count check accepts 0' \
    's|    if (b.count < 1) {|    if (b.count < 0) {|'
mutate_pack kill 'A2d the count check never fires' \
    's|    if (b.count < 1) {|    if (false) {|'
# invalid_argument, not out_of_range: a count of zero is malformed whatever
# layer it is applied to, while a coordinate past an extent is well formed and
# outside THIS layer. B27's whole value is that a catch site can tell them
# apart, and the conformance Env keeps the two tiers in separate buckets for
# exactly this case.
mutate_pack kill 'A2d the count failure is out_of_range' \
    's|        reject("burst count must be >= 1|        reject_range("burst count must be >= 1|'
mutate_pack kill 'A2d the count message drops the value' \
    's|"burst count must be >= 1, got " + std::to_string(b.count)|"burst count must be >= 1"|'

echo "== A2d: B49, the stride check"
# stride < 1 is malformed, ruled by the user directly rather than by delegation.
# Deleting the check does not merely make a backwards burst legal: it makes the
# unreachable-sort argument below false again, so this case and the `allow` in
# the walk section are two halves of one statement.
mutate_pack kill 'A2d the stride check is deleted' \
    '/    positive_or_reject("burst stride", b.stride);/d'
# The boundary, not the sign, the same distinction the count check draws: `< 1`
# and `< 0` agree on every negative stride and disagree only at 0, which is the
# standing-still run.
mutate_pack kill 'A2d the stride check accepts 0' \
    's|    positive_or_reject("burst stride", b.stride);|    if (b.stride < 0) reject("burst stride must be >= 1, got " + std::to_string(b.stride));|'
# invalid_argument, not out_of_range. A stride of 0 or less is malformed at
# every layer, so its tier is the count's and not the coordinate's, and B27's
# whole value is that a catch site can tell the two apart.
mutate_pack kill 'A2d the stride failure is out_of_range' \
    's|    positive_or_reject("burst stride", b.stride);|    if (b.stride < 1) reject_range("burst stride must be >= 1, got " + std::to_string(b.stride));|'

echo "== A2d: the order of the three refusals"
# layout.h states each rule and says nothing about their order, so these two
# cases pin what the code does rather than a rule anybody wrote (U12, U13). They
# are worth pinning because U10's re-throw at the engine boundary dispatches on
# the exception TYPE: a burst wrong in two ways reaches a different catch site
# depending on which check ran first.
mutate_pack kill 'A2d the stride check runs before the count check' \
    's|    if (b.count < 1) {|    positive_or_reject("burst stride", b.stride);\n    if (b.count < 1) {|'
mutate_pack kill 'A2d the stride check runs after the range check' \
    's|    positive_or_reject("burst stride", b.stride);||; s|    std::vector<LineId> lines;|    positive_or_reject("burst stride", b.stride);\n    std::vector<LineId> lines;|'

echo "== A2d: the far end of the walk"
# The single most important mutation in this unit, and the one that took a
# purpose-built case to kill. Deleting this check does NOT stop expand throwing:
# line_of validates all four coordinates of every element, so a burst running
# off the end still throws out_of_range and still appends nothing. What the
# check buys is that the coordinate reported is the far end, computed in int64,
# rather than whatever the element-by-element walk reached first after
# narrowing to int32. The killing case is a stride of 2^30, where the far end is
# 2^32 and truncates to a perfectly legal 0.
mutate_pack kill 'A2d the far end check is deleted' \
    's@    if (last < 0 || last >= n) {@    if (false) {@'
mutate_pack kill 'A2d the far end is computed in int32' \
    's|const std::int64_t last  = start + static_cast<std::int64_t>(b.count - 1) \* b.stride;|const std::int64_t last  = start + static_cast<std::int32_t>(b.count - 1) * b.stride;|'
# The off-by-one: `count` where the walk uses `count - 1` rejects the widest
# legal burst on every axis, which is the whole-axis COUT run the corpus emits.
mutate_pack kill 'A2d the far end drops the count offset' \
    's|static_cast<std::int64_t>(b.count - 1) \* b.stride|static_cast<std::int64_t>(b.count) * b.stride|'
# The two halves of the check are separately observable, and B49 changed what
# separates them. A downward walk is gone, so `last < 0` now holds exactly when
# the anchor's own coordinate on the walked axis is negative, and the case that
# kills this is the mirror of the 2^30 one above: anchor -8, count 4, stride 1
# makes the far end -5 while the walk would reach -8 first, so with the check
# the message names -5 and without it -8.
mutate_pack kill 'A2d the far end drops the lower half' \
    's@    if (last < 0 || last >= n) {@    if (last >= n) {@'
mutate_pack kill 'A2d the far end drops the upper half' \
    's@    if (last < 0 || last >= n) {@    if (last < 0) {@'
# The boundary, not the direction: `> n` accepts the coordinate one past the
# last element, which is what an off-by-one in a caller's loop produces.
mutate_pack kill 'A2d the far end is off by one' \
    's@    if (last < 0 || last >= n) {@    if (last < 0 || last > n) {@'
# The far end is measured on the WALKED axis. Reading the anchor's COUT whatever
# the burst says is "today's corpus always says COUT" baked in, and it is the
# fake RejectsUnpackedAxis's sibling from the other side.
mutate_pack kill 'A2d the far end assumes COUT' \
    's|const std::int32_t n     = extent_on(shape_, b.axis);|const std::int32_t n     = extent_on(shape_, Axis::COUT);|'
mutate_pack kill 'A2d the walk assumes COUT' \
    's|const std::int64_t start = coord_on(b.anchor, b.axis);|const std::int64_t start = coord_on(b.anchor, Axis::COUT);|'

echo "== A2d: the walk, B31 and the accumulate pattern"
# The second intentional `allow` in this file, and the same kind as B41's: the
# mutation is unreachable, not untested.
#
# B31 makes strictly increasing an obligation on the implementation rather than
# a property of a layout, so the sort is unconditional. Under this layout the
# only thing that ever reordered anything was a walk running downward, and B49
# made that unrepresentable: `stride < 1` is refused above, so the walked
# coordinate is strictly increasing over the run; every element that survives
# line_of is non-negative, so its block index is non-decreasing in it; and every
# line stride is positive whatever the flatten order (B24). The ids therefore
# reach the sort already sorted, for every burst this mapper accepts, and no
# input can tell the sorted range from the unsorted one.
#
# Not deleted, and the mutation is not weakened to keep the count clean. The
# sort earns its place for two reasons the suite cannot see: it is what makes
# B31 structural rather than an argument re-made per layout, and std::unique
# removes only ADJACENT equals, so without it the de-duplication below would
# rest on that same monotonicity argument instead of on a sorted range. It
# becomes killable again the moment a non-monotone layout or a permuted flatten
# with a negative radix exists, and the `A2d the stride check is deleted` case
# above is what would announce a reversal of B49.
mutate_pack allow 'A2d expand drops the sort' \
    '/    std::sort(lines.begin(), lines.end());/d' \
    'stride >= 1 (B49) makes every walk this mapper accepts already increasing'
# unique() removes ADJACENT equals only, so this is not the same mutation as
# the one above: without it a packed burst appends one id per element and a
# caller counting distinct lines over-counts every one of them.
mutate_pack kill 'A2d expand drops the de-duplication' \
    '/    lines.erase(std::unique(lines.begin(), lines.end()), lines.end());/d'
# The accumulate pattern layout.h describes: a whole tick's demand goes into one
# reused buffer. Assigning keeps only the last core's lines, and every earlier
# core's demand vanishes with no error anywhere.
mutate_pack kill 'A2d expand assigns instead of appending' \
    's|    out.insert(out.end(), lines.begin(), lines.end());|    out = lines;|'
mutate_pack kill 'A2d expand prepends' \
    's|    out.insert(out.end(), lines.begin(), lines.end());|    out.insert(out.begin(), lines.begin(), lines.end());|'
# The stride is a format v2 header field and nothing downstream may assume it
# is 1. Walking flat gives a sorted, distinct, in-range answer of a plausible
# size for every burst, so only a check that pins expand's MEANING sees it.
mutate_pack kill 'A2d the walk ignores the stride' \
    's|const std::int64_t v = start + static_cast<std::int64_t>(i) \* b.stride;|const std::int64_t v = start + static_cast<std::int64_t>(i);|'
# One element short. The last element of a burst is the one that crosses into
# the next block, so dropping it is a line the core needed and never asked for.
mutate_pack kill 'A2d the walk stops one short' \
    's|    for (std::int32_t i = 0; i < b.count; ++i) {|    for (std::int32_t i = 0; i + 1 < b.count; ++i) {|'

echo "== A2d: locate"
# The range check, and it runs BEFORE the division. LineId is signed (B5), so a
# negative id comes back out of `line % num_sets` as a negative set index and a
# cache array subscripts its slot vector from below. That is v1's F9, found in
# the release build after the signedness change made it reachable.
mutate_pack kill 'A2d locate never range checks' \
    's@    if (v < 0 || v >= num_lines_) {@    if (false) {@'
mutate_pack kill 'A2d locate drops the lower half' \
    's@    if (v < 0 || v >= num_lines_) {@    if (v >= num_lines_) {@'
mutate_pack kill 'A2d locate drops the upper half' \
    's@    if (v < 0 || v >= num_lines_) {@    if (v < 0) {@'
mutate_pack kill 'A2d locate is off by one' \
    's@    if (v < 0 || v >= num_lines_) {@    if (v < 0 || v > num_lines_) {@'
# out_of_range, not invalid_argument: a LineId outside [0, num_lines()) is well
# formed and outside THIS layer, which is the same tier line_of throws from.
mutate_pack kill 'A2d the locate failure is invalid_argument' \
    's|        reject_range("line id out of range|        reject("line id out of range|'
mutate_pack kill 'A2d the locate message loses its subject' \
    's|reject_range("line id out of range \[0, "|reject_range("[0, "|'
# The identity is the definition of the pair, and swapping the two fields is
# silent at a small set count and catastrophic at a large one.
mutate_pack kill 'A2d locate swaps set index and tag' \
    's|    return Placement{v % num_sets, v / num_sets};|    return Placement{v / num_sets, v % num_sets};|'
mutate_pack kill 'A2d locate divides by num_lines' \
    's|    return Placement{v % num_sets, v / num_sets};|    return Placement{v % num_lines_, v / num_lines_};|'

echo "== A4a: the CacheArray interface (plan 2.2)"
# Like A2a's, these are killed mostly at COMPILE time rather than by a failing
# check, because A4a is an interface and its content is its shape. That is not
# a weaker result: `make test` going red is `make test` going red, and a
# signature that silently changed would reach every array and every policy.
#
# The exception is the destructor, which is the one property here that still
# compiles when it is wrong. It is killed by a run-time check for that reason.
mutate_cache kill 'A4a the base destructor loses virtual' \
    's|    virtual ~CacheArray() = default;|    ~CacheArray() = default;|'
# The five verbs of 2.2, one at a time. A verb deleted from the interface takes
# the whole abstraction with it: a level that cannot invalidate cannot
# implement the inclusive branch at all (N8), which is why invalidate is here
# from the start rather than arriving with C4.
mutate_cache kill 'A4a probe is dropped' \
    's|    virtual SlotId probe(LineId line) const = 0;|    // dropped|'
mutate_cache kill 'A4a free_slot is dropped' \
    's|    virtual SlotId free_slot(LineId line) const = 0;|    // dropped|'
mutate_cache kill 'A4a victim_candidates is dropped' \
    's|    virtual void victim_candidates(LineId line, std::vector<Candidate>\& out) const = 0;|    // dropped|'
mutate_cache kill 'A4a insert is dropped' \
    's|    virtual InsertResult insert(LineId line, SlotId slot) = 0;|    // dropped|'
mutate_cache kill 'A4a invalidate is dropped (N8)' \
    's|    virtual void invalidate(SlotId slot) = 0;|    // dropped|'
mutate_cache kill 'A4a num_slots is dropped' \
    's|    virtual std::int32_t num_slots() const = 0;|    // dropped|'
# probe is const and is NOT an access (2.2). Dropping the const is what would
# let a speculative lookup perturb the recency stack, and it is the change the
# prefetcher of 4.6 must not be able to make by accident (B11, I15).
mutate_cache kill 'A4a probe loses its const' \
    's|    virtual SlotId probe(LineId line) const = 0;|    virtual SlotId probe(LineId line) = 0;|'
mutate_cache kill 'A4a free_slot loses its const' \
    's|    virtual SlotId free_slot(LineId line) const = 0;|    virtual SlotId free_slot(LineId line) = 0;|'
mutate_cache kill 'A4a victim_candidates loses its const' \
    's|std::vector<Candidate>\& out) const = 0;|std::vector<Candidate>\& out) = 0;|'
# The out parameter is a reference. By value, every candidate list is computed
# into a copy and thrown away, and the caller reads an empty vector: silent,
# and a hit rate below the truth for the whole run.
mutate_cache kill 'A4a candidates are taken by value' \
    's|std::vector<Candidate>\& out) const = 0;|std::vector<Candidate> out) const = 0;|'
# N12 on the array's own surface: probe takes the id of a LINE, and insert
# takes one of each so a swapped call cannot compile.
mutate_cache kill 'A4a probe takes a SlotId' \
    's|    virtual SlotId probe(LineId line) const = 0;|    virtual SlotId probe(SlotId line) const = 0;|'
mutate_cache kill 'A4a insert arguments are swapped' \
    's|    virtual InsertResult insert(LineId line, SlotId slot) = 0;|    virtual InsertResult insert(SlotId line, LineId slot) = 0;|'
mutate_cache kill 'A4a invalidate takes a LineId' \
    's|    virtual void invalidate(SlotId slot) = 0;|    virtual void invalidate(LineId slot) = 0;|'
# num_slots is int32 because SlotId is: a slot count a SlotId cannot name is a
# geometry whose upper slots are unreachable storage the sweep paid for.
mutate_cache kill 'A4a num_slots widens to int64' \
    's|    virtual std::int32_t num_slots() const = 0;|    virtual std::int64_t num_slots() const = 0;|'
# The two aggregates. Swapping Candidate's fields is silent at the call site
# because both are braced, and it is the reason they are different types.
mutate_cache kill 'A4a Candidate fields are swapped' \
    's|    SlotId slot;|    LineId line;|; s|    LineId line;  // NoLine when the slot is free|    SlotId slot;|'
mutate_cache kill 'A4a Candidate line becomes a SlotId' \
    's|    LineId line;  // NoLine when the slot is free|    SlotId line;|'
mutate_cache kill 'A4a InsertResult loses its evicted line' \
    's|    LineId evicted_line;  // that line, or NoLine when `evicted` is false|    // dropped|'

# ---------------------------------------------------------------------------
# A4b: SetAssociativeArray's construction and validation
#
# The names carry an `A4b` prefix, per B40, so `./tests/mutation_check.sh A4b`
# runs exactly this section. The path would separate A4b from A4a today, since
# src/set_associative.cpp is a new file, but it will not separate A4b from A4c
# and the prefix is what keeps the filter working when it stops.
#
# Five families:
#
#   the positivity    the three checks every later division rests on, plus the
#                     shared message helper they all speak through
#   the exactness     the plan's exit criterion, split in two, and the carried
#                     obligation that the message names the line size's FACTORS
#   the bounds        the slot bound at INT32_MAX and the associativity bound,
#                     both pinned by WHICH message comes out rather than by
#                     something coming out, because a second refusal is always
#                     waiting behind each of them
#   the derivation    num_sets, num_slots and associativity_, where num_slots
#                     alone is the same number under a swapped division
#   the copy control  cache.h's protected copy and move, killed by
#                     compile_fail.sh rather than by a failing check
# ---------------------------------------------------------------------------
echo "== A4b: the three positivity checks"
# The boundary, not the sign, which is the distinction every other unit's
# positivity case draws: `< 1` and `< 0` agree on every negative and disagree
# only at 0, which is the value a config loader that forgot a field produces.
mutate_sa kill 'A4b positive_or_reject accepts 0' \
    's|    if (v < 1) reject|    if (v < 0) reject|'
mutate_sa kill 'A4b positive_or_reject never fires' \
    's|    if (v < 1) reject|    if (false) reject|'
mutate_sa kill 'A4b cache_size_bytes unchecked' \
    '/    positive_or_reject("cache_size_bytes", cache_size_bytes);/d'
mutate_sa kill 'A4b associativity unchecked' \
    '/    positive_or_reject("associativity", associativity);/d'
# The line size is the one whose absence is not merely a bad geometry: a line
# size of 0 is a division by zero one line later, so this check is what makes
# the failure diagnosable rather than a signal. It is also the one no real
# mapper can reach, since BlockPackMapper refuses it at its own construction,
# which is why the suite needs a stub mapper to reach the branch at all.
mutate_sa kill 'A4b the mapper line size is unchecked' \
    '/    positive_or_reject("mapper line_size_bytes", line_bytes);/d'

echo "== A4b: the message is part of the contract"
# N11 on this class's surface. A message that only restates the rule does not
# say which config field was wrong or what it held.
mutate_sa kill 'A4b the offending value is dropped' \
    's|" must be >= 1, got " + std::to_string(v)|" must be >= 1"|'
mutate_sa kill 'A4b the parameter name is dropped' \
    's|reject(std::string(name) + " must be >= 1|reject(std::string("a parameter") + " must be >= 1|'
# One spelling of the prefix is what makes every message this class produces
# findable by the class name, which is block_pack.cpp's convention.
mutate_sa kill 'A4b the prefix is dropped' \
    's|throw std::invalid_argument("SetAssociativeArray: " + what);|throw std::invalid_argument(what);|'
# B27's tiers: a construction failure is invalid_argument because the argument
# is malformed regardless of layer, and the catch site has to be able to tell it
# from a bad access.
mutate_sa kill 'A4b the rejection type changed' \
    's|throw std::invalid_argument("SetAssociativeArray: " + what);|throw std::runtime_error("SetAssociativeArray: " + what);|'

echo "== A4b: the exactness check, which is the plan's exit criterion"
mutate_sa kill 'A4b the exactness check never fires' \
    's|    if (cache_size_bytes % line_bytes != 0) {|    if (false) {|'
# The operands the wrong way round. It is a real edit rather than a contrived
# one: `line_bytes % cache_size_bytes` is a well-typed expression that is zero
# for exactly the geometries nobody runs.
mutate_sa kill 'A4b the exactness check divides the wrong way' \
    's|    if (cache_size_bytes % line_bytes != 0) {|    if (line_bytes % cache_size_bytes != 0) {|'
# The A2b carried obligation to this unit. A non-power-of-two line size is
# deliberately legal (B16), so "65536 is not a whole number of 96-byte lines" is
# actionable only if the 96 can be traced back to cin_block 12 x cout_block 8.
mutate_sa kill 'A4b the exactness message drops the terms' \
    's|               mapper.line_size_terms() + ")");|               ")");|'
mutate_sa kill 'A4b the exactness message drops the line size' \
    's|" is not a whole number of " + std::to_string(line_bytes) + "-byte lines ("|" is not a whole number of lines ("|'
mutate_sa kill 'A4b the exactness message drops the size' \
    's|reject("cache_size_bytes " + std::to_string(cache_size_bytes) +|reject("cache_size_bytes " +|'
# "Read once" is stated in the file as load-bearing: line_size_bytes() is a
# virtual call whose answer the constructor divides by, and a mapper free to
# compute it per call is a mapper free to answer differently at the byte check
# than at the line count. This writes the per-call form, and only the call
# COUNT can see it, since a consistent mapper gives the same geometry either way.
mutate_sa kill 'A4b the line size is read per use' \
    's|    if (cache_size_bytes % line_bytes != 0) {|    if (cache_size_bytes % mapper.line_size_bytes() != 0) {|'
mutate_sa kill 'A4b total_lines divides the wrong way' \
    's|    const std::int64_t total_lines = cache_size_bytes / line_bytes;|    const std::int64_t total_lines = line_bytes / cache_size_bytes;|'

echo "== A4b: the slot bound at INT32_MAX"
# Slot ids are exactly [0, num_slots) and SlotId's representation is int32, so a
# geometry above the bound has upper slots no SlotId can name: storage the sweep
# paid for and never used, visible only as a hit rate a few points below the
# truth.
#
# Every case here is killed by WHICH message comes out, not by a message coming
# out, because the divisibility check is a second refusal waiting behind this
# one on both test geometries. That is deliberate: the accepted side of this
# bound cannot be constructed at all, since INT32_MAX slots is a slot vector of
# about 17 GB that the constructor fills, so message discrimination is the only
# evidence available.
mutate_sa kill 'A4b the slot bound never fires' \
    's|    if (total_lines > INT32_MAX) {|    if (false) {|'
# The boundary is exact rather than approximate: at total_lines == INT32_MAX the
# largest slot id is INT32_MAX - 1, one short of NoSlot, so no valid slot can be
# mistaken for the sentinel. `>=` refuses that geometry.
mutate_sa kill 'A4b the slot bound is off by one' \
    's|    if (total_lines > INT32_MAX) {|    if (total_lines >= INT32_MAX) {|'
mutate_sa kill 'A4b the slot bound message drops the count' \
    's|        reject(std::to_string(total_lines) + " lines exceeds the " +|        reject(" lines exceeds the " +|'
mutate_sa kill 'A4b the slot bound message drops the limit' \
    's|               std::to_string(INT32_MAX) + " slots a SlotId can name");|               " slots a SlotId can name");|'

echo "== A4b: the two associativity refusals"
# The bound and the divisibility check are both "bad associativity" and an
# over-associative point fails the divisibility test too, so an implementation
# that dropped either would still throw on both inputs. Only the text tells them
# apart, which is what L7 in TEST_DESIGN_CACHE.md exists for.
mutate_sa kill 'A4b the associativity bound never fires' \
    's|    if (associativity > total_lines) {|    if (false) {|'
# The boundary: at assoc == total_lines the geometry is a legal fully
# associative cache, which is a configuration the sweep grid contains, so a `>=`
# here refuses a real point.
mutate_sa kill 'A4b the associativity bound is off by one' \
    's|    if (associativity > total_lines) {|    if (associativity >= total_lines) {|'
# The comparison reversed, which refuses every ordinary geometry instead of the
# exotic one.
mutate_sa kill 'A4b the associativity bound compares the wrong way' \
    's|    if (associativity > total_lines) {|    if (total_lines > associativity) {|'
mutate_sa kill 'A4b the associativity bound message drops the value' \
    's|        reject("associativity " + std::to_string(associativity) +|        reject("associativity " +|'
mutate_sa kill 'A4b the divides-into-sets check never fires' \
    's|    if (total_lines % associativity != 0) {|    if (false) {|'
mutate_sa kill 'A4b the divides-into-sets check tests the wrong operand' \
    's|    if (total_lines % associativity != 0) {|    if (associativity % total_lines != 0) {|'
mutate_sa kill 'A4b the divide message drops the associativity' \
    's|               std::to_string(associativity));|               "");|'

echo "== A4b: the order the checks run in"
# set_associative.cpp states the order and calls it load-bearing, and layout.h's
# tier vocabulary does not settle it, so these pin what the code does rather
# than a rule anybody wrote (the same shape as U13's sibling on expand). They
# matter because a sweep grid takes a cross product: a point wrong in two ways
# is the expected case, and which message it produces is what a reader acts on.
mutate_sa kill 'A4b the size check runs after the associativity check' \
    's|    positive_or_reject("cache_size_bytes", cache_size_bytes);||; s|    positive_or_reject("associativity", associativity);|    positive_or_reject("associativity", associativity);\n    positive_or_reject("cache_size_bytes", cache_size_bytes);|'
mutate_sa kill 'A4b the divide check runs before the associativity bound' \
    's|    if (associativity > total_lines) {|    if (total_lines % associativity != 0) {\n        reject(std::to_string(total_lines) + " lines do not divide evenly into sets of " +\n               std::to_string(associativity));\n    }\n    if (associativity > total_lines) {|'

echo "== A4b: the derived geometry"
# num_slots alone is the same number under a swapped division, so an
# implementation that reported num_sets where the associativity belongs, or that
# floored where it should refuse, would look identical from outside until A4c.
# These four are the reason num_sets() and associativity() are exposed at all.
mutate_sa kill 'A4b num_sets is the associativity' \
    's|    num_sets_      = total_lines / associativity;|    num_sets_      = associativity;|'
mutate_sa kill 'A4b num_sets multiplies instead of dividing' \
    's|    num_sets_      = total_lines / associativity;|    num_sets_      = total_lines * associativity;|'
mutate_sa kill 'A4b num_slots is the set count' \
    's|    num_slots_     = static_cast<std::int32_t>(total_lines);|    num_slots_     = static_cast<std::int32_t>(num_sets_);|'
mutate_sa kill 'A4b the associativity is not stored' \
    's|    associativity_ = associativity;|    associativity_ = 1;|'

# The slot storage, and these three are recorded as `kill` on purpose although
# NOTHING in A4b's own suite can reach them.
#
# slots_ is private and all three verbs that could report it (probe, free_slot,
# victim_candidates) are A4c logic_error stubs, so the initial fill is not
# observable at A4b by anything: deleting the assign, filling it with a real
# line id, or sizing it by the set count are all invisible from outside the
# object. That is a gap in the CODE's observability, not in the tests, and no
# test can be written against it here.
#
# They are `kill` rather than `allow` because they are unreachable only until
# A4c, not by construction the way B41's and B50's are, and B56 moved the sweep
# to the Phase A gate, by which time A4c's probe and free_slot tests kill all
# three. Marking them `allow` would make the gate report `killed but was
# expected to survive` on three cases behaving exactly as designed. Anyone
# running `./tests/mutation_check.sh A4b` BEFORE A4c lands should expect these
# three to survive, and that is the finding rather than a defect.
mutate_sa kill 'A4b the slots are never filled' \
    '/    slots_.assign(as_size(num_slots_), NoLine);/d'
mutate_sa kill 'A4b the slots start occupied' \
    's|    slots_.assign(as_size(num_slots_), NoLine);|    slots_.assign(as_size(num_slots_), LineId{0});|'
mutate_sa kill 'A4b the slot vector is sized by the set count' \
    's|    slots_.assign(as_size(num_slots_), NoLine);|    slots_.assign(as_size(static_cast<std::int32_t>(num_sets_)), NoLine);|'

echo "== A4b: the header's accessors and its final"
mutate_sa_h kill 'A4b SetAssociativeArray loses final' \
    's|class SetAssociativeArray final : public CacheArray {|class SetAssociativeArray : public CacheArray {|'
mutate_sa_h kill 'A4b num_slots reports the set count' \
    's|std::int32_t num_slots() const override { return num_slots_; }|std::int32_t num_slots() const override { return static_cast<std::int32_t>(num_sets_); }|'
mutate_sa_h kill 'A4b num_sets reports the slot count' \
    's|std::int64_t num_sets() const { return num_sets_; }|std::int64_t num_sets() const { return num_slots_; }|'
mutate_sa_h kill 'A4b associativity reports the set count' \
    's|std::int32_t associativity() const { return associativity_; }|std::int32_t associativity() const { return static_cast<std::int32_t>(num_sets_); }|'

echo "== A4b: line_size_terms, on both sides of the virtual"
# layout.h's inline default rather than a pure virtual. Making it pure is the
# change the obligation explicitly rejected: it would oblige every AddressMapper
# in the tree, including sixteen non-conforming fakes and four `subclass omits`
# reject cases, to implement a function about diagnostics. The kill is the whole
# tree failing to compile, which is the point.
mutate_layout kill 'A4b line_size_terms is made pure' \
    's|virtual std::string line_size_terms() const { return std::to_string(line_size_bytes()); }|virtual std::string line_size_terms() const = 0;|'
# The default has to be correct if uninformative. Empty is neither.
mutate_layout kill 'A4b the line_size_terms default says nothing' \
    's|virtual std::string line_size_terms() const { return std::to_string(line_size_bytes()); }|virtual std::string line_size_terms() const { return ""; }|'
# BlockPackMapper's override, one factor at a time. The three factors are what
# the obligation asked for, so dropping any one of them retires it silently.
mutate_pack kill 'A4b line_size_terms drops weight_bytes' \
    's| + " x weight_bytes " + std::to_string(weight_bytes_);|;|'
mutate_pack kill 'A4b line_size_terms names cin_block twice' \
    's|std::to_string(cout_block_) + " x weight_bytes "|std::to_string(cin_block_) + " x weight_bytes "|'
# The override reduced to the default, which is the change that looks like a
# simplification and is exactly the obligation being undone.
mutate_pack kill 'A4b line_size_terms reports the bare product' \
    's|    return "cin_block " + std::to_string(cin_block_) + " x cout_block " +|    return std::to_string(line_size_bytes_); return "cin_block " + std::to_string(cin_block_) + " x cout_block " +|'

echo "== A4b: the copy control on the polymorphic base (cache.h)"
# The A4a-to-A4b carried obligation. `r1 = r2` through two base references
# compiled and assigned the base subobject only, leaving the derived state
# untouched: for an array that is a half-assigned cache reporting a hit rate for
# a geometry no level ever had. Both cases are killed by compile_fail.sh, since
# access control is not something a running binary can observe.
mutate_cache kill 'A4b the copy control becomes public' \
    's|^protected:$|public:|'
# Protected rather than DELETED is the other half of the decision, and it has
# its own case because deleting also stops the slice: a suite that only tested
# the reject side would call this mutation a fix. C1 holds one L1 per core over
# 8 to 256 cores, so a container of concrete arrays is the ordinary case.
mutate_cache kill 'A4b the copy control is deleted instead' \
    's|    CacheArray(const CacheArray&)            = default;|    CacheArray(const CacheArray\&)            = delete;|'
mutate_cache kill 'A4b the copy assignment is deleted instead' \
    's|    CacheArray& operator=(const CacheArray&) = default;|    CacheArray\& operator=(const CacheArray\&) = delete;|'
# Declaring any constructor suppresses the implicit default one, so this line is
# what keeps every array in the tree constructible. Dropping it stops the whole
# build, which is the kill.
mutate_cache kill 'A4b the default constructor is dropped' \
    '/    CacheArray()                             = default;/d'

echo
echo "$((killed + survived + unexpected)) mutations: $killed killed, $survived survived as expected, $unexpected unexpected"
if [ -n "$FILTER" ]; then
    echo "FILTERED run: only files matching '$FILTER', $skipped cases skipped"
fi
[ "$unexpected" -eq 0 ]
