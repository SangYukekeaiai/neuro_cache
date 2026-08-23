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
# A5 adds include/wcache/policy.h, include/wcache/stamp_policy.h and
# src/stamp_policy.cpp, by the same rule: a unit whose file is not on this line
# is not mutation tested at all while the summary still reports a clean sweep.
# Phase C adds all eight of ITS files: include/wcache/trace.h, cache_level.h,
# engine.h and prefetcher.h, and src/cache_level.cpp, engine.cpp,
# engine_core.cpp and prefetcher.cpp. This omission has now bitten three times
# (cache.h at A4a, set_associative.* at A4b, and all of Phase B), which is why
# extending this line is the FIRST thing done to this file in a review round.
# trace.h is the one worth naming: it is a pure interface with no executable
# code at all, so nothing in it can produce a wrong number and only its SHAPE
# can be mutated -- which is exactly the argument A2a's section already makes,
# and exactly why leaving it off the list would have been invisible.
# D2c and D2d add include/wcache/stats.h, src/stats.cpp and include/wcache/hist.h,
# by the rule this comment block states: a unit whose file is not on this line is
# not mutation tested at all while the summary still reports a clean sweep.
# Task 15 adds apps/wcache_run.cpp, by the same rule and with one difference
# this file has to state rather than hide: `make test` does not BUILD apps/, so
# no mutation in it can turn this script's gate red. Its cases below are all
# `allow` for that reason, and the reason names tests/run_cli.sh, which is the
# end-to-end script that does cover it and which this harness does not drive.
# Listing the file anyway is what keeps the omission from being silent.
# Tasks 17 and 18 add include/wcache/sweep.h, src/sweep.cpp, apps/app_support.h
# and apps/wcache_sweep.cpp. The two library files ARE built by `make test`,
# through tests/test_sweep.cpp, so their cases expect a kill. The two under
# apps/ are not, for the reason stated just above, so theirs are `allow` and
# name tests/sweep_cli.sh as their cover. apps/app_support.h is where Task 15's
# `lines_per_burst` and `PaddingMeter` now live, shared by the two programs, so
# the two cases that used to name apps/wcache_run.cpp for them name it instead.
# Phase B adds all five of its files: include/wcache/port.h, event.h and mshr.h,
# and src/port.cpp and src/mshr.cpp. This omission has now bitten twice (cache.h
# at A4a, set_associative.* at A4b), which is why it is the FIRST thing done to
# this file in a review round rather than the last. event.h is the one worth
# naming: it is header-only AND was included by no translation unit at all until
# tests/test_event.cpp existed, so before this round nothing in the tree either
# compiled it or could mutate it.
FILES="include/wcache/types.h include/wcache/layout.h include/wcache/block_pack.h include/wcache/cache.h include/wcache/set_associative.h include/wcache/policy.h include/wcache/stamp_policy.h include/wcache/port.h include/wcache/event.h include/wcache/mshr.h include/wcache/trace.h include/wcache/cache_level.h include/wcache/engine.h include/wcache/prefetcher.h src/block_pack.cpp src/set_associative.cpp src/stamp_policy.cpp src/port.cpp src/mshr.cpp src/cache_level.cpp src/engine.cpp src/engine_core.cpp src/prefetcher.cpp include/wcache/config.h src/config.cpp include/wcache/stream_format.h include/wcache/byte_source.h include/wcache/stream_trace.h src/stream_trace.cpp include/wcache/stats.h src/stats.cpp include/wcache/hist.h apps/wcache_run.cpp include/wcache/sweep.h src/sweep.cpp apps/app_support.h apps/wcache_sweep.cpp"
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
#
# The old note here said this was a shared login node whose binding cap was on
# CPU time, which parallelism does not reduce. That was the NCSA Delta
# constraint and it does not apply: this machine is a standalone workstation,
# 32 cores, no scheduler, `ulimit -t` unlimited. There is no CPU cap, so a
# filtered run is a choice about wall time rather than a legal requirement.
#
# Thirty-two rather than eight, matching compile_fail.sh's default, and it is
# that half of the setting that carries the win: `make -j` past 8 buys nothing,
# because `make test` serializes on the compile-fail driver. This line EXPORTS
# JOBS, so leaving it at 8 would push the driver back down to 8 for every case
# in a sweep and undo the change where it compounds. See compile_fail.sh for the
# measurement.
JOBS=${JOBS:-32}
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

# apps/ judges against `make test-cli`, not `make test`. The Makefile's `test`
# target deliberately does not build apps/, so every apps/ case used to be an
# `allow` whose stated reason was "apps/ is not built by `make test`". That is a
# reason a case can never fail, which makes it a case that measures nothing: the
# two main()s carry the makespan, the CSV header and the padding meter, and all
# of it was unfalsifiable. `test-cli` builds apps/ and runs run_cli.sh,
# sweep_cli.sh and v1_pipe.sh over the checked-in fixtures, so those cases can
# now be judged. Added 2026-08-20 with the eight cases flipped to `kill`.
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
        apps/*) target=test-cli ;;
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
mutate_pol() { mutate_in include/wcache/policy.h "$@"; }
mutate_sp_h() { mutate_in include/wcache/stamp_policy.h "$@"; }
mutate_sp() { mutate_in src/stamp_policy.cpp "$@"; }
# Phase B. NAMING, because the tree carries a collision that misreads easily:
# the PLAN's Phase B units are B1 (Port), B2 (EventQueue) and B3 (MshrFile),
# while PROGRESS.md's DECISIONS are also numbered B1-B104. Every "B1"/"B2"/"B3"
# case-name prefix below is the plan's UNIT, matching the A2c / A4a / A5
# prefixes already in this file, which are unit names too (B40).
mutate_port_h() { mutate_in include/wcache/port.h "$@"; }
mutate_port() { mutate_in src/port.cpp "$@"; }
mutate_ev() { mutate_in include/wcache/event.h "$@"; }
mutate_mshr_h() { mutate_in include/wcache/mshr.h "$@"; }
mutate_mshr() { mutate_in src/mshr.cpp "$@"; }
# Phase C. Same naming trap as Phase B, one letter along: the PLAN's Phase C
# units are C1 (CacheLevel), C2 (the handlers), C3 (the core state machine and
# barrier), C4 (inclusion) and C5 (prefetching), while PROGRESS.md's DECISIONS
# are numbered B1-B126. Every "C1".."C5" case-name prefix below is the plan's
# UNIT. A third spelling exists and is NOT used here: Parts 2.1, 3.1 and 4.1 of
# the plan write "C1" and "C2" for two of v3's own changes, the core model of
# 4.5 and the prefetcher of 4.6.
mutate_tr() { mutate_in include/wcache/trace.h "$@"; }
mutate_st() { mutate_in src/stream_trace.cpp "$@"; }
mutate_stats_h() { mutate_in include/wcache/stats.h "$@"; }
mutate_stats() { mutate_in src/stats.cpp "$@"; }
mutate_hist() { mutate_in include/wcache/hist.h "$@"; }
mutate_app() { mutate_in apps/wcache_run.cpp "$@"; }
mutate_appsup() { mutate_in apps/app_support.h "$@"; }
mutate_sweep_h() { mutate_in include/wcache/sweep.h "$@"; }
mutate_sweep() { mutate_in src/sweep.cpp "$@"; }
mutate_sweep_app() { mutate_in apps/wcache_sweep.cpp "$@"; }
# D1's own reader had no case at all until Task 18 needed one for the grid.
# The gap is noted rather than filled here: this task owns parse_config_grid,
# not parse_config.
mutate_cfg() { mutate_in src/config.cpp "$@"; }
mutate_cl_h() { mutate_in include/wcache/cache_level.h "$@"; }
mutate_cl() { mutate_in src/cache_level.cpp "$@"; }
mutate_eng_h() { mutate_in include/wcache/engine.h "$@"; }
mutate_eng() { mutate_in src/engine.cpp "$@"; }
mutate_engc() { mutate_in src/engine_core.cpp "$@"; }
mutate_pf_h() { mutate_in include/wcache/prefetcher.h "$@"; }
mutate_pf() { mutate_in src/prefetcher.cpp "$@"; }

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
# U16's eighth tagged type, on the same three questions the seventh answers.
# A tag is a line id only WITHIN one set, so aliasing it to tags::line is the
# mistake the name exists to stop and is the one a reader is most likely to talk
# themselves into: both are int64 addresses in a flat space.
mutate kill 'U16 TagId aliases LineId' \
    's|using TagId = Tagged<std::int64_t, tags::tag_id>;|using TagId = Tagged<std::int64_t, tags::line>;|'
mutate kill 'U16 TagId aliases SetIndex' \
    's|using TagId = Tagged<std::int64_t, tags::tag_id>;|using TagId = Tagged<std::int64_t, tags::set_index>;|'
# The width under the name. A tag is `line / num_sets` over an int64 line space,
# so an int32 tag truncates for any array whose line count exceeds 2^31 sets
# worth -- and, because Tagged's constructor refuses to narrow, it does not
# truncate silently but stops locate compiling. Either way it is a kill, and the
# case is here so that the width is pinned rather than inherited from LineId by
# assumption.
mutate kill 'U16 TagId narrowed to int32' \
    's|using TagId = Tagged<std::int64_t, tags::tag_id>;|using TagId = Tagged<std::int32_t, tags::tag_id>;|'

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
echo "== A2a/U16: Placement's shape"
# U16 typed the fields, so these cases changed shape with it. The old ones asked
# whether a raw int64 field was wide enough and signed; the field is now a
# SetIndex and a TagId, and the questions worth asking are whether it still has
# a name at all and whether the two names are still different.

# The U16 revert, one field at a time. This is the mutation the whole increment
# exists to make loud: with a raw int64 field, `LineId l{p.set_index}` compiles
# again and the three compile_fail cases that were flipped to reject go green as
# accepts. Killed at compile time, in compile_fail.sh and at the static_asserts
# in test_layout.cpp.
mutate_layout kill 'set_index untyped back to a raw int64' \
    's|    SetIndex set_index;  // in \[0, num_sets)|    std::int64_t set_index;|'
mutate_layout kill 'tag untyped back to a raw int64' \
    's|    TagId    tag;|    std::int64_t tag;|'
# The subtler revert: both fields keep a NAME, but the same one. A set index and
# a tag are then interchangeable with each other, which is the confusion the
# pair was typed to stop, while every "is it tagged" check still passes.
mutate_layout kill 'tag becomes a second SetIndex' \
    's|    TagId    tag;|    SetIndex tag;|'
# Field ORDER. Before U16 this was the case a reader could not see, because
# locate returns a braced Placement and swapping the declarations swapped every
# mapper's answer silently. Since the two fields are different types it is a
# compile error instead, which is a stronger kill and is one of the things U16
# bought. Kept, because the property is still the property.
mutate_layout kill 'set_index and tag swap' \
    's|    SetIndex set_index;  // in \[0, num_sets)|    TagId    tag_SWAP_;|; s|    TagId    tag;|    SetIndex set_index;|; s|    TagId    tag_SWAP_;|    TagId    tag;|'

echo "== A2a: the interface stays an interface"
# Deleting a derived mapper through an AddressMapper* is what the engine does.
# A non-virtual destructor there is undefined behaviour whose usual symptom is
# a leak, so nothing but a deliberate probe announces it.
mutate_layout kill 'destructor made non-virtual'  's|virtual ~AddressMapper() = default;|~AddressMapper() = default;|'
# A pure virtual given a body makes AddressMapper concrete: `AddressMapper m;`
# starts compiling, and a mapper with no layout at all becomes constructible.
mutate_layout kill 'expand given a default body'  's|virtual void expand(const Burst\& b, std::vector<LineId>\& out) const = 0;|virtual void expand(const Burst\& b, std::vector<LineId>\& out) const {}|'
mutate_layout kill 'locate given a default body'  's|virtual Placement locate(LineId line, std::int64_t num_sets) const = 0;|virtual Placement locate(LineId line, std::int64_t num_sets) const { return Placement{SetIndex{0}, TagId{0}}; }|'

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
#
# Since U16 the swap is of the two VALUES rather than of the two fields: the
# fields have different types, so `Placement{TagId{...}, SetIndex{...}}` would
# not compile and would be a weaker mutation, killed by the compiler before it
# ever reached the identity check. The value swap is the one that still
# produces a well-typed mapper that is wrong, so it is the one kept.
mutate_pack kill 'A2d locate swaps set index and tag' \
    's|    return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};|    return Placement{SetIndex{v / num_sets}, TagId{v % num_sets}};|'
mutate_pack kill 'A2d locate divides by num_lines' \
    's|    return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};|    return Placement{SetIndex{v % num_lines_}, TagId{v / num_lines_}};|'

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
    's|               mapper.line_size_terms(line_bytes) + ")");|               ")");|'
# The caller half of Q3. Passing a fresh read instead of the value it already
# holds puts the second read back from this side, so the guarantee can be
# undone at either end and each end has its own case.
mutate_sa kill 'Q3 the caller passes a fresh read' \
    's|mapper.line_size_terms(line_bytes)|mapper.line_size_terms(mapper.line_size_bytes())|'
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
    's|    virtual std::string line_size_terms(std::int64_t line_bytes) const {|    virtual std::string line_size_terms(std::int64_t line_bytes) const = 0; std::string unused_(std::int64_t line_bytes) const {|'
# The default has to be correct if uninformative. Empty is neither.
mutate_layout kill 'A4b the line_size_terms default says nothing' \
    's|        return std::to_string(line_bytes);|        return "";|'
# Q3 itself. The default printing line_size_bytes() rather than the value it was
# handed is exactly the code Q3 replaced, and it is the reason the argument was
# added: the refusal then contains two reads of one mapper and, for a mapper
# whose answer moves, its two halves name different numbers. The argument going
# unused is not a style regression, it is the guarantee being dropped, so it has
# a case rather than a comment.
mutate_layout kill 'Q3 the default reads the line size again' \
    's|        return std::to_string(line_bytes);|        return std::to_string(line_size_bytes());|'
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

echo "== A4c: base_slot, the one piece of geometry the verbs share"
# A wrong base is wrong for all five verbs at once, which is why it has cases of
# its own rather than being covered incidentally by whichever verb runs first.
mutate_sa kill 'A4c base_slot drops the way stride' \
    's|    return static_cast<std::int32_t>(set_index \* associativity_);|    return static_cast<std::int32_t>(set_index);|'
# The identity `line == tag * num_sets + set_index` makes the tag look like the
# natural thing to key on, and at num_sets == 1 a tag genuinely IS the line, so
# this is the substitution a reader can talk themselves into.
mutate_sa kill 'A4c base_slot reads the tag' \
    's|mapper_.locate(line, num_sets_).set_index.get();|mapper_.locate(line, num_sets_).tag.get();|'
mutate_sa kill 'A4c base_slot locates against the slot count' \
    's|mapper_.locate(line, num_sets_)|mapper_.locate(line, num_slots_)|'

echo "== A4c: probe"
mutate_sa kill 'A4c probe returns the set base' \
    's|        if (slots_\[as_size(base + w)\] == line) return SlotId{base + w};|        return SlotId{base};|'
mutate_sa kill 'A4c probe compares against NoLine' \
    's|        if (slots_\[as_size(base + w)\] == line) return|        if (slots_\[as_size(base + w)\] == NoLine) return|'
mutate_sa kill 'A4c probe reports the way, not the slot' \
    's|        if (slots_\[as_size(base + w)\] == line) return SlotId{base + w};|        if (slots_\[as_size(base + w)\] == line) return SlotId{w};|'
# Addressed to probe's body, because the three way loops are textually
# identical and an unaddressed sed would mutate all three at once, which is
# three mutations wearing one name.
mutate_sa kill 'A4c probe scans one way short' \
    '/^SlotId SetAssociativeArray::probe/,/^}/ s|w < associativity_|w < associativity_ - 1|'

echo "== A4c: free_slot"
# The lowest free way is what makes the answer a function of the array's state
# alone, so a cold-start fill is reproducible. A downward scan is still correct
# and would silently change where every line in a sweep lands.
mutate_sa kill 'A4c free_slot scans downward' \
    '/^SlotId SetAssociativeArray::free_slot/,/^}/ s|for (std::int32_t w = 0; w < associativity_; ++w)|for (std::int32_t w = associativity_ - 1; w >= 0; --w)|'
mutate_sa kill 'A4c free_slot returns the first way untested' \
    's|        if (slots_\[as_size(base + w)\] == NoLine) return SlotId{base + w};|        return SlotId{base + w};|'
mutate_sa kill 'A4c free_slot takes an occupied way' \
    's|        if (slots_\[as_size(base + w)\] == NoLine) return|        if (slots_\[as_size(base + w)\] != NoLine) return|'
mutate_sa kill 'A4c free_slot never reports exhaustion' \
    '/^SlotId SetAssociativeArray::free_slot/,/^}/ s|    return NoSlot;|    return SlotId{base};|'

echo "== A4c: victim_candidates"
# The clear IS the contract (cache.h): an appending version lets a caller that
# forgot to clear pick a victim from a previous fill in a DIFFERENT set, and the
# line is then stored where probe can never look for it.
mutate_sa kill 'A4c victim_candidates drops the clear' \
    '/    out.clear();/d'
# And the order of the clear against the range check, which is the other half of
# the same rule: a throwing call must leave the caller's buffer as it was.
mutate_sa kill 'A4c victim_candidates clears before the range check' \
    '/^void SetAssociativeArray::victim_candidates/,/^}/ { /^    out.clear();$/d; s|^    const std::int32_t base = base_slot(line);$|    out.clear();\n    const std::int32_t base = base_slot(line);| }'
mutate_sa kill 'A4c victim_candidates loops one short' \
    '/^void SetAssociativeArray::victim_candidates/,/^}/ s|w < associativity_|w < associativity_ - 1|'
mutate_sa kill 'A4c victim_candidates reports every way free' \
    's|out.push_back(Candidate{SlotId{base + w}, slots_\[as_size(base + w)\]});|out.push_back(Candidate{SlotId{base + w}, NoLine});|'
mutate_sa kill 'A4c victim_candidates numbers ways, not slots' \
    's|out.push_back(Candidate{SlotId{base + w}, slots_\[as_size(base + w)\]});|out.push_back(Candidate{SlotId{w}, slots_\[as_size(base + w)\]});|'

echo "== A4c: insert and invalidate"
mutate_sa kill 'A4c insert always reports an eviction' \
    's|    if (previous == NoLine) return InsertResult{false, NoLine};|    if (false) return InsertResult{false, NoLine};|'
mutate_sa kill 'A4c insert never reports an eviction' \
    's|    return InsertResult{true, previous};|    return InsertResult{false, NoLine};|'
mutate_sa kill 'A4c insert names the new line as evicted' \
    's|    return InsertResult{true, previous};|    return InsertResult{true, line};|'
mutate_sa kill 'A4c insert writes to slot zero' \
    's|    slots_\[as_size(s)\] = line;|    slots_[0] = line;|'
mutate_sa kill 'A4c insert reads slot zero' \
    's|    const LineId previous = slots_\[as_size(s)\];|    const LineId previous = slots_[0];|'
mutate_sa kill 'A4c insert drops the slot bound check' \
    's|    const std::int32_t s = slot_or_reject("insert", slot);|    const std::int32_t s = slot.get();|'
mutate_sa kill 'A4c invalidate stores a line id' \
    's|    slots_\[as_size(slot_or_reject("invalidate", slot))\] = NoLine;|    slots_[as_size(slot_or_reject("invalidate", slot))] = LineId{0};|'
mutate_sa kill 'A4c invalidate does nothing' \
    's|    slots_\[as_size(slot_or_reject("invalidate", slot))\] = NoLine;|    (void)slot_or_reject("invalidate", slot);|'

echo "== A4c: the shared slot bound"
mutate_sa kill 'A4c the slot bound is closed at the top' \
    's@    if (s < 0 || s >= num_slots_) {@    if (s < 0 || s > num_slots_) {@'
# The message names the VERB rather than the class, because a caller with a
# stray slot id needs to know which call it reached. Both verbs reporting
# "insert" would pass any check that only asked whether something was thrown.
mutate_sa kill 'A4c both verbs report the same name' \
    's|std::string(verb)|std::string("insert")|'

# ---------------------------------------------------------------------------
# A5
# ---------------------------------------------------------------------------

echo "== A5: the stamp and the counter"
# The sentinel's VALUE is not observable, and this case is here to say so with a
# proof rather than to be silently dropped.
#
# The reasoning it was written on was that zero is smaller than every stamp ever
# handed out, so raising it above them inverts the preference for a never-filled
# slot. That reasoning misses the coupling: the constructor seeds the counter
# from the same constant, `next_stamp_(kNeverStamped + 1)`, so the first stamp
# handed out is ALWAYS sentinel+1 and every later one is larger. Moving the
# constant moves the sentinel and the whole stamp sequence together, and the
# ordering between them cannot change. All three sites that read the constant
# move with it for the same reason.
#
# Measured rather than argued: with this sed applied, a policy with slots 2 and
# 3 never filled still answers 2, and a policy whose slot 3 was invalidated
# still answers 3, under both LruPolicy and FifoPolicy. The only value that
# differs is the absolute stamp, which nothing outside this file can read.
#
# So it survives because it changes no behaviour, which is what `allow` means
# here, and the property it was reaching for is pinned by the three cases below
# instead: each one moves ONE of the three sites and leaves the other two, which
# is what actually breaks the ordering.
mutate_sp allow 'A5 a never-filled slot becomes the last victim' \
    's|constexpr std::int64_t kNeverStamped = 0;|constexpr std::int64_t kNeverStamped = 9000000000000000000;|' \
    'the counter is seeded kNeverStamped + 1, so moving the constant moves the sentinel and every stamp together and no order changes'
# Site 2, the initial fill, moved on its own: every slot starts ABOVE every
# stamp the counter will hand out, so a never-filled way becomes the LAST
# victim and the policy evicts a live line while an empty way sits unused.
# That is the silently wrong hit rate the case above was written to catch.
mutate_sp kill 'A5 a never-filled slot starts newest' \
    's|    stamp_.assign(static_cast<std::size_t>(num_slots), kNeverStamped);|    stamp_.assign(static_cast<std::size_t>(num_slots), kNeverStamped + 1000000);|'
# Site 1, the counter seed, moved on its own and in the other direction: the
# first stamp handed out is then BELOW the sentinel, so a freshly filled slot
# outranks a never-filled one as a victim. The `+ 1` is what forbids that, and
# the case below only pins the ties.
mutate_sp kill 'A5 the counter starts below the never-stamped value' \
    's|: next_stamp_(kNeverStamped + 1) {|: next_stamp_(kNeverStamped - 1) {|'
# Site 3, on_invalidate, moved on its own: an invalidated slot becomes the last
# victim rather than the first, so the array holds an empty way it will not
# reuse until every live line in the set has been evicted past it.
mutate_sp kill 'A5 on_invalidate makes the slot the last victim' \
    's|    stamp_\[index_or_reject("on_invalidate", slot)\] = kNeverStamped;|    stamp_[index_or_reject("on_invalidate", slot)] = kNeverStamped + 1000000;|'
mutate_sp kill 'A5 the counter starts at the never-stamped value' \
    's|: next_stamp_(kNeverStamped + 1) {|: next_stamp_(kNeverStamped) {|'
# Strictly increasing is what makes two occupied slots' stamps never equal,
# which is the premise the tie-break argument rests on.
mutate_sp kill 'A5 the stamp counter does not advance' \
    '/^    ++next_stamp_;$/d'
mutate_sp kill 'A5 on_fill does not stamp' \
    's|void StampPolicy::on_fill(SlotId slot) { stamp(slot); }|void StampPolicy::on_fill(SlotId slot) { (void)slot; }|'
# on_invalidate is observable rather than a formality: leaving the previous
# occupant's stamp makes an invalidated slot compete on the age of a line that
# is gone.
mutate_sp kill 'A5 on_invalidate leaves the old stamp' \
    's|    stamp_\[index_or_reject("on_invalidate", slot)\] = kNeverStamped;|    (void)index_or_reject("on_invalidate", slot);|'
mutate_sp kill 'A5 on_invalidate stamps instead of clearing' \
    's|    stamp_\[index_or_reject("on_invalidate", slot)\] = kNeverStamped;|    stamp(slot);|'

echo "== A5: LRU against FIFO"
# The whole of the difference between the two classes, in both directions.
mutate_sp kill 'A5 LRU does not refresh on a hit' \
    's|void LruPolicy::on_hit(SlotId slot) { stamp(slot); }|void LruPolicy::on_hit(SlotId slot) { (void)slot; }|'
mutate_sp kill 'A5 FIFO refreshes on a hit' \
    's|void FifoPolicy::on_hit(SlotId) {}|void FifoPolicy::on_hit(SlotId slot) { stamp(slot); }|'

echo "== A5: pick_victim, and the order-independence it owes"
# The plan's A5 exit criterion. Dropping the tie-break makes the answer depend
# on which arrangement the candidate set arrived in, which is the one regression
# nothing else announces: with only LRU and FIFO built, both pick "oldest by a
# stamp" and every fixture still passes.
mutate_sp kill 'A5 pick_victim drops the tie-break' \
    's@if (age < oldest || (age == oldest \&\& slot < victim)) {@if (age < oldest) {@'
mutate_sp kill 'A5 the tie-break prefers the largest slot id' \
    's@(age == oldest \&\& slot < victim)@(age == oldest \&\& slot > victim)@'
mutate_sp kill 'A5 pick_victim takes the newest' \
    's@if (age < oldest ||@if (age > oldest ||@'
mutate_sp kill 'A5 pick_victim answers the first candidate' \
    's|    return victim;|    return candidates[0].slot;|'
mutate_sp kill 'A5 pick_victim skips a candidate' \
    's|    for (std::size_t i = 1; i < candidates.size(); ++i) {|    for (std::size_t i = 2; i < candidates.size(); ++i) {|'
# The minimum of nothing has no answer, so the alternative to refusing is
# returning a slot id that names no candidate, which the caller installs into.
mutate_sp kill 'A5 pick_victim accepts an empty candidate set' \
    's|    if (candidates.empty()) {|    if (candidates.size() > 1000000) {|'
mutate_sp kill 'A5 the stamp bound is closed at the top' \
    's@if (s < 0 || static_cast<std::size_t>(s) >= stamp_.size()) {@if (s < 0 || static_cast<std::size_t>(s) > stamp_.size()) {@'
mutate_sp kill 'A5 the slot count check drops the boundary' \
    's|    if (num_slots < 1) {|    if (num_slots < 0) {|'

echo "== A5: make_policy"
mutate_sp kill 'A5 make_policy gives FIFO for lru' \
    's|        case PolicyKind::LRU:  return std::make_unique<LruPolicy>(num_slots);|        case PolicyKind::LRU:  return std::make_unique<FifoPolicy>(num_slots);|'
mutate_sp kill 'A5 make_policy gives LRU for fifo' \
    's|        case PolicyKind::FIFO: return std::make_unique<FifoPolicy>(num_slots);|        case PolicyKind::FIFO: return std::make_unique<LruPolicy>(num_slots);|'
# The one wrong answer for Random: a config naming a policy this build does not
# have would run to completion under a policy nobody selected, and the results
# row would attribute a hit rate to the wrong one.
mutate_sp kill 'A5 make_policy falls back to LRU for random' \
    's|            reject("make_policy",|            return std::make_unique<LruPolicy>(num_slots); reject("make_policy",|'
mutate_sp kill 'A5 make_policy ignores the slot count' \
    's|std::make_unique<LruPolicy>(num_slots)|std::make_unique<LruPolicy>(1)|'

echo "== A5: the interface (policy.h)"
# All four verbs are pure so a policy cannot be half implemented. These two are
# killed by compile_fail.sh's tryR cases, since a default body is not something
# a running binary can observe.
mutate_pol kill 'A5 on_hit gains a default body' \
    's|    virtual void on_hit(SlotId slot) = 0;|    virtual void on_hit(SlotId) {}|'
mutate_pol kill 'A5 pick_victim gains a default body' \
    's|    virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;|    virtual SlotId pick_victim(const std::vector<Candidate>\&) { return NoSlot; }|'
# pick_victim being non-const is the openness the criterion protects: a Random
# policy advances an RNG, and a const signature here is exactly the interface
# change adding it would force.
mutate_pol kill 'A5 pick_victim becomes const' \
    's|    virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;|    virtual SlotId pick_victim(const std::vector<Candidate>\& candidates) const = 0;|'
# SlotId is the whole of what crosses the array/policy split.
mutate_pol kill 'A5 on_hit takes a LineId' \
    's|    virtual void on_hit(SlotId slot) = 0;|    virtual void on_hit(LineId slot) = 0;|'
# B67's decision on the second polymorphic base in the tree. Both directions,
# for the reason cache.h's pair has both: deleting also stops the slice, so a
# suite that only tested the reject side would call that a fix.
mutate_pol kill 'A5 the policy copy control becomes public' \
    's|^protected:$|public:|'
mutate_pol kill 'A5 the policy copy control is deleted instead' \
    's|    ReplacementPolicy(const ReplacementPolicy&)            = default;|    ReplacementPolicy(const ReplacementPolicy\&)            = delete;|'
mutate_pol kill 'A5 the policy default constructor is dropped' \
    '/    ReplacementPolicy()                                    = default;/d'
# The engine holds a policy as unique_ptr<ReplacementPolicy>, so a non-virtual
# destructor here destroys the base subobject only and leaks the per-slot state
# for every policy in the run. It is a warning rather than an error, so the
# counting subclass in the suite is what catches it.
mutate_pol kill 'A5 the policy destructor stops being virtual' \
    's|    virtual ~ReplacementPolicy() = default;|    ~ReplacementPolicy() = default;|'

echo "== A5: the concrete policies (stamp_policy.h)"
mutate_sp_h kill 'A5 LruPolicy loses final' \
    's|class LruPolicy final : public StampPolicy {|class LruPolicy : public StampPolicy {|'
mutate_sp_h kill 'A5 FifoPolicy loses final' \
    's|class FifoPolicy final : public StampPolicy {|class FifoPolicy : public StampPolicy {|'
# FifoPolicy overrides one of the four verbs, so "it overrides no others" is a
# fact about the class rather than something the base guarantees. These two give
# it an on_invalidate of its own, in the two directions the LRU-side pair above
# already covers: ignoring the verb leaves an invalidated way competing on the
# age of a line that is gone, and stamping on it makes that way the LAST victim.
# Under `inclusion = inclusive` the back-invalidation path is where this lands,
# so an L2 eviction would leave an L1 way that is empty and unreachable.
mutate_sp_h kill 'A5 FIFO ignores an invalidate' \
    '/^class FifoPolicy/,/^};/ s|    void on_hit(SlotId slot) override;|    void on_hit(SlotId slot) override;\n    void on_invalidate(SlotId) override {}|'
mutate_sp_h kill 'A5 FIFO stamps on an invalidate' \
    '/^class FifoPolicy/,/^};/ s|    void on_hit(SlotId slot) override;|    void on_hit(SlotId slot) override;\n    void on_invalidate(SlotId slot) override { on_fill(slot); }|'
# V29's rule made literal: dropping random from the enum makes `policy = random`
# an unknown NAME rather than a known and unbuilt one, so the run would report a
# typo where it should report a missing feature.
mutate_sp_h kill 'A5 random leaves the enum' \
    's|enum class PolicyKind : std::uint8_t { LRU = 0, FIFO = 1, RANDOM = 2 };|enum class PolicyKind : std::uint8_t { LRU = 0, FIFO = 1 };|'
mutate_sp_h kill 'A5 PolicyKind widens' \
    's|enum class PolicyKind : std::uint8_t|enum class PolicyKind : std::int32_t|'

echo "== B1: Port, the occupancy arithmetic (src/port.cpp)"
# The unit is three lines, so the mutations are the three lines: which of the
# two stamps the accept comes from, what next_accept advances by, and what is
# handed back.
mutate_port kill 'B1 reserve always answers next_accept' \
    's|    const SimTime accept = (now < next_accept_) ? next_accept_ : now;|    const SimTime accept = next_accept_;|'
mutate_port kill 'B1 reserve always answers now' \
    's|    const SimTime accept = (now < next_accept_) ? next_accept_ : now;|    const SimTime accept = now;|'
mutate_port kill 'B1 the free/busy compare is inverted' \
    's|    const SimTime accept = (now < next_accept_) ? next_accept_ : now;|    const SimTime accept = (now > next_accept_) ? next_accept_ : now;|'
mutate_port kill 'B1 ii is never charged' \
    's|    next_accept_ = accept + ii_;|    next_accept_ = accept;|'
mutate_port kill 'B1 next_accept advances from now' \
    's|    next_accept_ = accept + ii_;|    next_accept_ = now + ii_;|'
# The two quantities confused for each other, in both directions. `ii` is the
# reciprocal of throughput and `latency` is what one request waits; a channel
# with 100 cycles of latency at ii 2 has 50 requests in flight and is a
# completely different machine from one that serializes 100-cycle round trips
# (2.4). Either of these makes the model the other machine, silently.
mutate_port kill 'B1 next_accept advances by the latency' \
    's|    next_accept_ = accept + ii_;|    next_accept_ = accept + latency_;|'
mutate_port kill 'B1 reserve returns the completion time' \
    's|    return accept;|    return accept + latency_;|'

echo "== B1: Port, the two rejections"
mutate_port kill 'B1 a negative field is accepted at -1' \
    's|    if (v.get() < 0) {|    if (v.get() < -1) {|'
mutate_port kill 'B1 the ii check is dropped' \
    '/    non_negative_or_reject("ii", ii);/d'
mutate_port kill 'B1 the latency check is dropped' \
    '/    non_negative_or_reject("latency", latency);/d'
# The ORDER, which port.h states and which decides what a grid point wrong in
# both fields reports. Inserting the latency check first is the smallest edit
# that reverses it; the trailing original check then runs a second time and
# passes, so the only observable change is which field the message names.
mutate_port kill 'B1 latency is checked before ii' \
    's|    non_negative_or_reject("ii", ii);|    non_negative_or_reject("latency", latency);\n    non_negative_or_reject("ii", ii);|'
mutate_port kill 'B1 the rejection is a logic_error' \
    's|throw std::invalid_argument("Port: " + what);|throw std::logic_error("Port: " + what);|'
mutate_port kill 'B1 the message drops the offending value' \
    's|reject(std::string(name) + " must be >= 0, got " + std::to_string(v.get()));|reject(std::string(name) + " must be >= 0");|'
mutate_port kill 'B1 the message always names ii' \
    's|reject(std::string(name) + " must be >= 0|reject(std::string("ii") + " must be >= 0|'

echo "== B1: Port, the accessors and the initial stamp (port.h)"
mutate_port_h kill 'B1 ii() reports the latency' \
    's|    SimTime ii() const { return ii_; }|    SimTime ii() const { return latency_; }|'
mutate_port_h kill 'B1 latency() reports the ii' \
    's|    SimTime latency() const { return latency_; }|    SimTime latency() const { return ii_; }|'
mutate_port_h kill 'B1 next_accept() reports the ii' \
    's|    SimTime next_accept() const { return next_accept_; }|    SimTime next_accept() const { return ii_; }|'
# The run starts at tile_origin[0] == 0 (Part 5), so a port that has never been
# used is free at 0. A port born busy delays the first access of the run at
# every level, which shifts every tile_origin and would read as a cache result.
mutate_port_h kill 'B1 a port is born busy' \
    's|    SimTime next_accept_{0};|    SimTime next_accept_{1};|'

echo "== B2: EventQueue, 3.6's class table (event.h)"
# Each of these reverses one row of the class table, and 4.6's worked example is
# what they cost: a prefetch fill and a demand probe both land at cycle 111, and
# only Fill before Probe makes that a hit rather than a second fetch and 110
# more cycles (V23). Every one of them produces a plausible, wrong, perfectly
# reproducible run.
mutate_ev kill 'B2 an L2 fill is classed as a probe' \
    's|        case EventKind::L2Fill:|        case EventKind::L2Fill:  return EventClass::Probe;|'
mutate_ev kill 'B2 the fills are classed as probes' \
    's|        case EventKind::L1Fill:  return EventClass::Fill;|        case EventKind::L1Fill:  return EventClass::Probe;|'
mutate_ev kill 'B2 the barrier is classed as a fill' \
    's|        case EventKind::Barrier: return EventClass::Barrier;|        case EventKind::Barrier: return EventClass::Fill;|'
mutate_ev kill 'B2 a probe is classed as a fill' \
    's|        case EventKind::L2Probe: return EventClass::Probe;|        case EventKind::L2Probe: return EventClass::Fill;|'
mutate_ev kill 'B2 an issue is classed as a probe' \
    's|        case EventKind::Issue:   return EventClass::Issue;|        case EventKind::Issue:   return EventClass::Probe;|'
# The fallback the comment in event.h warns about, and it is the one wrong
# answer available: a kind silently dispatched at class 0 reorders the run
# against itself and the result still looks like a result.
mutate_ev kill 'B2 an unknown kind gets a fallback class' \
    's|    throw std::logic_error("class_of: unknown EventKind");|    return EventClass::Fill;|'
mutate_ev kill 'B2 an unknown kind is a runtime_error' \
    's|throw std::logic_error("class_of: unknown EventKind");|throw std::runtime_error("class_of: unknown EventKind");|'
# The enumerator VALUES are the order, so renumbering them is renumbering 3.6.
mutate_ev kill 'B2 Fill is renumbered' \
    's|    Fill = 0,|    Fill = 9,|'
mutate_ev kill 'B2 Barrier and Probe collide' \
    's|    Barrier = 1,|    Barrier = 2,|'
mutate_ev kill 'B2 EventClass widens' \
    's|enum class EventClass : std::uint8_t {|enum class EventClass : std::int32_t {|'
mutate_ev kill 'B2 EventKind widens' \
    's|enum class EventKind : std::uint8_t {|enum class EventKind : std::int32_t {|'

echo "== B2: EventQueue, the total order (event.h)"
# One case per field of `(time, class, effective_age, core_id, seq)`, dropped
# and reversed. D11 asks for a TOTAL order rather than a stable one because
# under LRU the service order IS the recency stack (D7): one flipped tie leaves
# a different victim and every access after it diverges.
mutate_ev kill 'B2 key_less drops the time' \
    '/    if (!(a.time == b.time)) return a.time < b.time;/d'
mutate_ev kill 'B2 key_less drops the class' \
    '/    if (a.cls != b.cls)      return a.cls < b.cls;/d'
mutate_ev kill 'B2 key_less drops the age' \
    '/    if (!(a.age == b.age))   return a.age < b.age;/d'
mutate_ev kill 'B2 key_less drops the core' \
    '/    if (!(a.core == b.core)) return a.core < b.core;/d'
mutate_ev kill 'B2 key_less reverses the class' \
    's|    if (a.cls != b.cls)      return a.cls < b.cls;|    if (a.cls != b.cls)      return a.cls > b.cls;|'
mutate_ev kill 'B2 key_less reverses the age' \
    's|    if (!(a.age == b.age))   return a.age < b.age;|    if (!(a.age == b.age))   return a.age > b.age;|'
mutate_ev kill 'B2 key_less reverses the seq' \
    's|    return a.seq < b.seq;|    return a.seq > b.seq;|'
# The seq is the LAST discriminator and the one that makes the order total. A
# comparison that stops before it leaves ties for std::priority_queue to break,
# and its arrangement is unspecified.
mutate_ev kill 'B2 key_less stops before the seq' \
    's|    return a.seq < b.seq;|    return false;|'
mutate_ev kill 'B2 the age is compared before the class' \
    's|    if (a.cls != b.cls)      return a.cls < b.cls;|    if (!(a.age == b.age))   return a.age < b.age;\n    if (a.cls != b.cls)      return a.cls < b.cls;|'
# The one inversion in the file lives at the single point the container demands
# it. Undo it and the engine dispatches the LATEST event first, which is not a
# discrete-event simulation at all.
mutate_ev kill 'B2 the queue is a max-heap' \
    's|            return key_less(b.key, a.key);|            return key_less(a.key, b.key);|'

echo "== B2: EventQueue, schedule and pop_min (event.h)"
mutate_ev kill 'B2 P1 is dropped, the past is schedulable' \
    's|        if (time < now_) {|        if (time < SimTime{0}) {|'
# The other direction, and the one that would break the DEFAULT configuration:
# at 2.5b's zero latencies whole chains run inside one timestamp, so scheduling
# AT now is ordinary rather than exotic.
mutate_ev kill 'B2 scheduling at now is refused' \
    's|        if (time < now_) {|        if (time <= now_) {|'
mutate_ev kill 'B2 the seq counter does not advance' \
    '/^        ++next_seq_;$/d'
mutate_ev kill 'B2 the first seq is 1' \
    's|EventSeq{next_seq_}|EventSeq{next_seq_ + 1}|'
mutate_ev kill 'B2 the age never reaches the key' \
    's|EventKey{time, class_of(kind), age, core, EventSeq{next_seq_}}|EventKey{time, class_of(kind), NoRefusal, core, EventSeq{next_seq_}}|'
mutate_ev kill 'B2 the core never reaches the key' \
    's|EventKey{time, class_of(kind), age, core, EventSeq{next_seq_}}|EventKey{time, class_of(kind), age, CoreId{0}, EventSeq{next_seq_}}|'
mutate_ev kill 'B2 pop_min does not advance now' \
    '/        now_ = e.key.time;/d'
mutate_ev kill 'B2 an empty pop is an out_of_range' \
    's|throw std::logic_error("EventQueue::pop_min: the queue is empty")|throw std::out_of_range("EventQueue::pop_min: the queue is empty")|'
mutate_ev kill 'B2 now() starts below zero' \
    's|    SimTime now_{0};|    SimTime now_{-1};|'
mutate_ev kill 'B2 scheduled() reports the queue depth' \
    's|    std::int64_t scheduled() const { return next_seq_; }|    std::int64_t scheduled() const { return static_cast<std::int64_t>(q_.size()); }|'
mutate_ev kill 'D4 an empty peek is an out_of_range' \
    's|throw std::logic_error("EventQueue::peek_min: the queue is empty")|throw std::out_of_range("EventQueue::peek_min: the queue is empty")|'

echo "== B3: MshrFile, 3.8's write-once stamp (src/mshr.cpp)"
mutate_mshr kill 'B3 mark_refused overwrites an existing stamp' \
    's|    if (r.refusal == NoRefusal) {|    if (true) {|'
mutate_mshr kill 'B3 mark_refused does not record the reason' \
    '/r.reason[[:space:]]*= reason;/d'
mutate_mshr kill 'B3 mark_refused does not stamp at all' \
    '/        r.refusal = counter.next();/d'
mutate_mshr kill 'B3 the first stamp is 1' \
    's|    const RefusalOrder stamp{next_};|    const RefusalOrder stamp{next_ + 1};|'
mutate_mshr kill 'B3 the refusal counter does not advance' \
    '/^    ++next_;$/d'
mutate_mshr_h kill 'B3 issued() reports one too many' \
    's|    std::int64_t issued() const { return next_; }|    std::int64_t issued() const { return next_ + 1; }|'
mutate_mshr_h kill 'B3 the request key is reversed' \
    's|inline bool key_less(const Request\& a, const Request\& b) { return a.refusal < b.refusal; }|inline bool key_less(const Request\& a, const Request\& b) { return a.refusal > b.refusal; }|'

echo "== B3: MshrFile, the constructor"
mutate_mshr kill 'B3 capacity may be zero' \
    's|    at_least_or_reject("capacity", capacity, 1);|    at_least_or_reject("capacity", capacity, 0);|'
mutate_mshr kill 'B3 tgts_per_mshr may be zero' \
    's|    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 1);|    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 0);|'
mutate_mshr kill 'B3 demand_reserve may be negative' \
    's|    at_least_or_reject("demand_reserve", demand_reserve, 0);|    at_least_or_reject("demand_reserve", demand_reserve, -1);|'
# `demand_reserve == capacity` is the DEFAULT demand-only configuration (4.2),
# not an edge case, so a constructor that rejected equality would reject the
# shipped defaults.
mutate_mshr kill 'B3 demand_reserve equal to capacity is refused' \
    's|    if (demand_reserve > capacity) {|    if (demand_reserve >= capacity) {|'
mutate_mshr kill 'B3 the demand_reserve relation is dropped' \
    's|    if (demand_reserve > capacity) {|    if (demand_reserve > 1000000) {|'
mutate_mshr kill 'B3 tgts is checked before capacity' \
    's|    at_least_or_reject("capacity", capacity, 1);|    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 1);\n    at_least_or_reject("capacity", capacity, 1);|'
mutate_mshr kill 'B3 demand_reserve is checked before tgts' \
    's|    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 1);|    at_least_or_reject("demand_reserve", demand_reserve, 0);\n    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 1);|'
mutate_mshr kill 'B3 the config rejection is a logic_error' \
    's|    throw std::invalid_argument("MshrFile: " + what);|    throw std::logic_error("MshrFile: " + what);|'
mutate_mshr kill 'B3 the caller rejection is an invalid_argument' \
    's|    throw std::logic_error("MshrFile::" + std::string(verb) + ": " + what);|    throw std::invalid_argument("MshrFile::" + std::string(verb) + ": " + what);|'

echo "== B3: MshrFile, has_slot and the demand reserve"
# Without this case a grantee is refused by its own reservation, the freed slot
# is never consumed, and the run stalls on a credit that exists.
mutate_mshr kill 'B3 a grantee is refused by its own reservation' \
    '/    if (r.reserved) return true;/d'
mutate_mshr kill 'B3 has_slot ignores the reserved credits' \
    's|    const std::int32_t free = capacity_ - live() - reserved_;|    const std::int32_t free = capacity_ - live();|'
# The condition is `is_prefetch_at_issue(r)`, so the PREFETCH arm is the `?`
# side and the DEMAND arm is the `:` side. Mind which arm each case is aiming
# at: reading the `?` side as the demand arm mutates the opposite behaviour
# from the one the case name claims, and the case would still report a kill.
mutate_mshr kill 'B3 has_slot admits one demand too many' \
    's@is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;@is_prefetch_at_issue(r) ? free > demand_reserve_ : free >= 0;@'
# 4.6's whole guarantee: a prefetch may never take the last `demand_reserve`
# entries, so a demand burst can always allocate. Dropped, off by one, and with
# the two branches swapped.
mutate_mshr kill 'B3 a prefetch ignores the reserve' \
    's@is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;@is_prefetch_at_issue(r) ? free > 0 : free > 0;@'
mutate_mshr kill 'B3 the prefetch bound is off by one' \
    's@is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;@is_prefetch_at_issue(r) ? free >= demand_reserve_ : free > 0;@'
mutate_mshr kill 'B3 the demand and prefetch branches swap' \
    's@is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;@is_prefetch_at_issue(r) ? free > 0 : free > demand_reserve_;@'

echo "== B3: MshrFile, allocate"
mutate_mshr kill 'B3 allocate does not check for a live entry' \
    's|    if (entries_.find(line) != entries_.end()) {|    if (false) {|'
mutate_mshr kill 'B3 allocate does not check has_slot' \
    's|    if (!has_slot(primary)) {|    if (false) {|'
# The primary occupies targets[0], which is what makes 4.1's per-entry bound
# exact and what puts it through the same retire loop as every later merge.
mutate_mshr kill 'B3 the primary is not a target' \
    '/    entry.targets.push_back(&primary);/d'
mutate_mshr kill 'B3 an entry is always born demand' \
    's|    Mshr entry{line, primary.core, primary.demand, !primary.demand, primary.issued_at, {}, {}};|    Mshr entry{line, primary.core, true, !primary.demand, primary.issued_at, {}, {}};|'
mutate_mshr kill 'B3 an entry records the wrong core' \
    's|    Mshr entry{line, primary.core, primary.demand, !primary.demand, primary.issued_at, {}, {}};|    Mshr entry{line, CoreId{0}, primary.demand, !primary.demand, primary.issued_at, {}, {}};|'
# A leaked reservation is a credit the file never hands back, so the grant loop
# stops one waiter short for the rest of the run and the symptom is a stall
# attributed to the MSHR bound.
mutate_mshr kill 'B3 allocate does not spend the reservation' \
    's|    if (primary.reserved) {|    if (false) {|'
mutate_mshr kill 'B3 allocate leaves the reservation flag set' \
    '/        primary.reserved = false;/d'

echo "== B3: MshrFile, add_target: I3 and 4.6's promotion"
mutate_mshr kill 'B3 the target bound is off by one' \
    's|    if (as_count(e.targets.size()) >= tgts_per_mshr_) return false;|    if (as_count(e.targets.size()) > tgts_per_mshr_) return false;|'
mutate_mshr kill 'B3 add_target refuses everything' \
    's|    if (as_count(e.targets.size()) >= tgts_per_mshr_) return false;|    if (true) return false;|'
mutate_mshr kill 'B3 add_target reports success without merging' \
    '/    e.targets.push_back(&r);/d'
# The promotion, in the three ways an `or` can be got wrong. The middle one is
# the dangerous direction: a prefetch merging onto a demand entry must NOT
# demote it, because a core IS waiting on that line and the fill would then
# notify nobody.
mutate_mshr kill 'B3 a merging target overwrites the demand bit' \
    's@    e.demand = e.demand || r.demand;@    e.demand = r.demand;@'
mutate_mshr kill 'B3 promotion is an and' \
    's@    e.demand = e.demand || r.demand;@    e.demand = e.demand \&\& r.demand;@'
mutate_mshr kill 'B3 promotion is dropped' \
    '/    e.demand = e.demand || r.demand;/d'

echo "== B3: MshrFile, the drop rule (N16, I15)"
# The one rule keeping the waiting population backed one-for-one by demand
# credits, which is the whole of 4.1's argument. Both indices, separately,
# because a guard removed from one leaves the other rejecting and a single case
# would report a pass.
mutate_mshr kill 'B3 push_line_wait queues a prefetch' \
    '/^void MshrFile::push_line_wait/,/^}/ s|if (is_prefetch_at_issue(r)) {|if (false) {|'
mutate_mshr kill 'B3 push_slot_wait queues a prefetch' \
    '/^void MshrFile::push_slot_wait/,/^}/ s|if (is_prefetch_at_issue(r)) {|if (false) {|'
mutate_mshr kill 'B3 push_line_wait stamps the slot reason' \
    '/^void MshrFile::push_line_wait/,/^}/ s|WaitReason::Line|WaitReason::Slot|'
mutate_mshr kill 'B3 push_slot_wait stamps the line reason' \
    '/^void MshrFile::push_slot_wait/,/^}/ s|WaitReason::Slot|WaitReason::Line|'
# A push that skipped the stamp would put an UNSTAMPED request into a population
# ordered by stamp, where NoRefusal sorts it last forever: starvation, arriving
# by omission rather than by a rule.
mutate_mshr kill 'B3 push_line_wait does not stamp' \
    '/^void MshrFile::push_line_wait/,/^}/ {/    mark_refused/d}'
mutate_mshr kill 'B3 push_slot_wait does not stamp' \
    '/^void MshrFile::push_slot_wait/,/^}/ {/    mark_refused/d}'
mutate_mshr kill 'B3 push_line_wait does not push' \
    '/    e.line_wait.push_back(\&r);/d'
mutate_mshr kill 'B3 push_slot_wait does not push' \
    '/    slot_wait_.push_back(\&r);/d'

echo "== B3: MshrFile, release_reservation"
mutate_mshr kill 'B3 release reports a credit it did not free' \
    's|    if (!r.reserved) return false;|    if (!r.reserved) return true;|'
mutate_mshr kill 'B3 release does not return the credit' \
    '/^    --reserved_;$/d'
mutate_mshr kill 'B3 release leaves the flag set' \
    '/^    r.reserved = false;$/d'

echo "== B3: MshrFile, the grant loop (I7, 3.8)"
# 3.8's counterexample is exactly what these two cost: a slot waiter can outlive
# the allocation of an entry it later merges onto, so the index is NOT in age
# order and taking the front grants the wrong request.
mutate_mshr kill 'B3 the grant loop takes the front of the index' \
    's|        const auto oldest = std::min_element(|        const auto oldest = slot_wait_.begin(); (void)std::min_element(|'
mutate_mshr kill 'B3 the grant loop takes the newest' \
    's|            \[\](const Request\* a, const Request\* b) { return key_less(\*a, \*b); });|            [](const Request* a, const Request* b) { return key_less(*b, *a); });|'
mutate_mshr kill 'B3 the grant loop over-grants by one' \
    's|    while (live() + reserved_ < capacity_ \&\& !slot_wait_.empty()) {|    while (live() + reserved_ <= capacity_ \&\& !slot_wait_.empty()) {|'
mutate_mshr kill 'B3 a grant reserves nothing' \
    '/^        ++reserved_;$/d'
mutate_mshr kill 'B3 a grantee is not marked reserved' \
    '/r->reserved[[:space:]]*= true;/d'
mutate_mshr kill 'B3 the grant loop does not pop the index' \
    '/        slot_wait_.erase(oldest);/d'

echo "== B3: MshrFile, retire, and the order inside it"
# THE ordering claim of 3.4 and of mshr.h: erase first, so the credit this
# retire freed is the one the loop can hand out. Collecting first grants one
# waiter fewer at EVERY retire, which is a stall the sweep would attribute to
# the MSHR depth. Written as a three-step swap so the two statements really
# trade places rather than one being duplicated.
mutate_mshr kill 'B3 retire grants before it erases' \
    's|    entries_.erase(it);|@@ERASE@@|; s|    collect_grants(out.wake);|    entries_.erase(it);|; s|@@ERASE@@|    collect_grants(out.wake);|'
mutate_mshr kill 'B3 retire loses the line waiters' \
    's|out.wake[[:space:]]*= e.line_wait;|out.wake.clear();|'
mutate_mshr kill 'B3 retire loses the targets' \
    's|    out.targets = e.targets;|    out.targets.clear();|'
# `out` is REPLACED, not appended to, so a caller may reuse one buffer. An
# appending version hands a later retire an earlier one's wake list a second
# time, which reinjects a request that is already in flight.
mutate_mshr kill 'B3 retire appends to the wake buffer' \
    's|out.wake[[:space:]]*= e.line_wait;|out.wake.insert(out.wake.end(), e.line_wait.begin(), e.line_wait.end());|'
mutate_mshr kill 'B3 retire appends to the target buffer' \
    's|    out.targets = e.targets;|    out.targets.insert(out.targets.end(), e.targets.begin(), e.targets.end());|'
mutate_mshr kill 'B3 retire does not sort the wake list' \
    '/    std::stable_sort(out.wake.begin(), out.wake.end(),/,+1d'
mutate_mshr allow 'B3 the wake sort is not stable' \
    's|    std::stable_sort(out.wake.begin(), out.wake.end(),|    std::sort(out.wake.begin(), out.wake.end(),|' \
    'an equivalent mutant: no two members of a wake list can compare equivalent, so stable and unstable agree elementwise'
# The proof, written out rather than asserted, in B99's shape. Stability only
# ever matters for elements the comparator calls EQUIVALENT, and 3.8's key over
# a wake list has none: every member of `e.line_wait` and of `slot_wait_` got
# there through `push_line_wait` or `push_slot_wait`, both of which call
# `mark_refused` before pushing, and `mark_refused` draws from a strictly
# increasing counter that is never reset. So every member carries a distinct
# stamp and the comparator is a strict total order on the list, under which
# stable_sort and sort produce the same sequence by definition. The one way a
# duplicate stamp could appear is the same request pushed onto two indices at
# once (I5 forbids it, and this class does not enforce it), and even then the
# two elements are the SAME pointer, so the two sequences are still identical.
# mshr.cpp says this in its own comment -- "they cannot tie today ... which is
# exactly why the weaker guarantee is free" -- and the value of stable_sort is
# that it keeps the answer a function of insertion order IF that ever changes,
# which is a property about a future, not a behaviour a test can reach today.
mutate_mshr kill 'B3 the wake list is sorted newest first' \
    's|                     \[\](const Request\* a, const Request\* b) { return key_less(\*a, \*b); });|                     [](const Request* a, const Request* b) { return key_less(*b, *a); });|'
mutate_mshr kill 'B3 retire does not erase the entry' \
    '/    entries_.erase(it);/d'
# The IDENTITY half of the guard, not the lookup half: a `retire` that only
# asked whether the line has an entry would erase the real one when handed a
# different Mshr object naming the same line, report someone else's targets as
# satisfied, and drop a fill.
mutate_mshr kill 'B3 retire checks only that the line is live' \
    's@    if (it == entries_.end() || \&it->second != \&e) {@    if (it == entries_.end()) {@'

echo "== B3: MshrFile, the readers and the request defaults"
mutate_mshr kill 'B3 live() counts the reservations too' \
    's|std::int32_t MshrFile::live() const { return as_count(entries_.size()); }|std::int32_t MshrFile::live() const { return as_count(entries_.size()) + reserved_; }|'
mutate_mshr kill 'B3 slot_wait_depth() always reports zero' \
    's|std::int32_t MshrFile::slot_wait_depth() const { return as_count(slot_wait_.size()); }|std::int32_t MshrFile::slot_wait_depth() const { return 0; }|'
mutate_mshr kill 'B3 find never answers' \
    's|    return it == entries_.end() ? nullptr : \&it->second;|    return nullptr;|'
# 3.3's defaults on a fresh Request. Each of these is silently true of EVERY
# request in the run: a fresh request that is a prefetch never waits, one born
# refused is never stamped, one born at the L2 re-enters at the wrong level
# (3.5), and one born holding a reservation is admitted by has_slot forever.
mutate_mshr_h kill 'B3 a fresh request is a prefetch' \
    's|    bool demand = true;|    bool demand = false;|'
mutate_mshr_h kill 'B3 a fresh request is born refused' \
    's|    RefusalOrder refusal = NoRefusal;|    RefusalOrder refusal = RefusalOrder{0};|'
mutate_mshr_h kill 'B3 a fresh request re-enters at the L2' \
    's|    Level level = Level::L1;|    Level level = Level::L2;|'
mutate_mshr_h kill 'B3 a fresh request holds a reservation' \
    's|    bool reserved = false;|    bool reserved = true;|'
mutate_mshr_h kill 'B3 a fresh request carries an entry' \
    's|    Mshr\* mshr1 = nullptr;|    Mshr* mshr1 = reinterpret_cast<Mshr*>(1);|'
mutate_mshr_h kill 'B3 WaitReason widens' \
    's|enum class WaitReason : std::uint8_t|enum class WaitReason : std::int32_t|'
mutate_mshr_h kill 'B3 Level widens' \
    's|enum class Level : std::uint8_t|enum class Level : std::int32_t|'

# ---------------------------------------------------------------------------
# Phase C: the engine
#
# C1 is CacheLevel and triage, C2 the six event handlers plus retire/reinject,
# C3 the core state machine and the tile barrier, C4 inclusion, C5 prefetching.
# The suites are tests/test_cache_level.cpp, tests/test_engine.cpp and
# tests/test_prefetch.cpp, sharing tests/engine_fixture.h.
#
# Two families dominate, and they are the two the plan itself says are
# load-bearing:
#
#   the ORDER   3.5's re-entry level, 3.6's classes, 3.8's stamp order, and the
#               merge-and-sort at every retire. Under LRU the service order IS
#               the eviction order (D7), so an ordering mutation is a wrong
#               answer that is perfectly reproducible -- which is decision
#               B121's lesson and the reason these cases are checked against
#               ORACLES rather than against a second run.
#   the RULES   4.5's self-timed recurrence, 4.6's four drops and the credit
#               budget, and 4.4's inclusion guard, each of which produces a
#               plausible timeline when broken.
# ---------------------------------------------------------------------------
echo "== C1: triage, branch by branch (src/cache_level.cpp)"
mutate_cl kill 'C1 an array hit does not move recency' \
    's|        policy_->on_hit(slot);||'
mutate_cl kill 'D3 an L1 array hit is charged to no bucket (V21)' \
    's|        charge_path(r, level_ == Level::L1 ? StallCause::L1Port : StallCause::L2Port);|        if (level_ == Level::L2) charge_path(r, StallCause::L2Port);|'
mutate_cl kill 'D3 an L1 array hit takes the L2 port bucket (V21)' \
    's|        charge_path(r, level_ == Level::L1 ? StallCause::L1Port : StallCause::L2Port);|        charge_path(r, StallCause::L2Port);|'
mutate_cl kill 'D3 an L2 array hit takes the L1 port bucket (V21)' \
    's|        charge_path(r, level_ == Level::L1 ? StallCause::L1Port : StallCause::L2Port);|        charge_path(r, StallCause::L1Port);|'
mutate_cl kill 'D3 an array hit overwrites the cause of an earlier refusal' \
    's|    if (r.refusal == NoRefusal) r.cause = c;|    r.cause = c;|'
mutate_cl kill 'C1 a prefetch array hit is not dropped' \
    's|        if (at_issue) return TriageOutcome::DroppedArrayHit;||'
mutate_cl kill 'C1 a prefetch merges onto a matching entry' \
    's|        if (at_issue) return TriageOutcome::DroppedEntry;||'
mutate_cl kill 'C1 the two no-slot drops are swapped' \
    's|return free > 0 ? TriageOutcome::DroppedReserve : TriageOutcome::DroppedNoSlot;|return free > 0 ? TriageOutcome::DroppedNoSlot : TriageOutcome::DroppedReserve;|'
mutate_cl kill 'C1 a forwarded request does not take its entry' \
    's|        r.mshr1 = &e;||'
# 3.5's trap, at the one place the field is written: a request that re-enters at
# the L1 finds its OWN entry, merges into itself, and waits for a fill nobody
# will request. The symptom is D12's deadlock, several thousand events later.
mutate_cl kill 'C1 a forwarded request re-enters at the L1' \
    's|        r.level = Level::L2;||'
mutate_cl kill 'C1 the re-entry rule is applied at the L2 instead' \
    's|    if (level_ == Level::L1) {|    if (level_ == Level::L2) {|'
mutate_cl kill 'C1 granted is appended to rather than replaced' \
    's|    granted.clear();||'
mutate_cl kill 'C1 a released reservation does not re-run the grant loop' \
    's|        if (mshrs_.release_reservation(r)) mshrs_.collect_grants(granted);|        (void)mshrs_.release_reservation(r);|'
mutate_cl kill 'C1 I5 is not refused at the only place it can break' \
    's|        refuse_if_waiting("triage", r);||'
mutate_cl kill 'C1 install does not refuse a duplicate line' \
    's@    if (array_->probe(line) != NoSlot) {@    if (false) {@'
mutate_cl kill 'C1 install ignores free ways' \
    's|    SlotId slot = array_->free_slot(line);|    SlotId slot = NoSlot;|'
mutate_cl kill 'C1 install does not tell the policy' \
    's|    policy_->on_fill(slot);||'
mutate_cl kill 'C1 bank_of takes the wrong end of the set index' \
    's|bank_high_bits_ ? set / sets_per_bank_ : set % banks;|bank_high_bits_ ? set % banks : set / sets_per_bank_;|'
# The third intentional `allow` in this file, in B99's shape: unreachable, not
# untested. At `banks == 1` the shortcut and the arithmetic agree for every
# line, by two identities rather than by inspection: `set % 1 == 0` for every
# set, and `sets_per_bank_ == num_sets_ / 1 == num_sets_`, so
# `set / sets_per_bank_ == 0` for every set index, which `locate` bounds at
# `[0, num_sets)`. Both branches therefore return 0, and the clamp below cannot
# fire because 0 < 1. The only difference is one extra `locate` call, which is
# not observable through any interface the engine has: `locate` is const, it
# throws only for a line outside the layer, and a line outside the layer cannot
# reach `bank_of` because `expand` refused it first. So the mutation is
# equivalent and no test can kill it.
mutate_cl allow 'C1 bank_of loses its single-bank shortcut' \
    's|    if (banks == 1) return 0;  // the L1, and the L2 at its 2.5b default||' \
    'equivalent at banks == 1: set % 1 and set / num_sets are both 0 for every set'

echo "== C1: the outcome set itself (include/wcache/cache_level.h)"
mutate_cl_h kill 'C1 is_dropped forgets DroppedArrayHit' \
    's@    return o == TriageOutcome::DroppedArrayHit || o == TriageOutcome::DroppedEntry ||@    return o == TriageOutcome::DroppedEntry ||@'
mutate_cl_h kill 'C1 is_dropped forgets DroppedReserve' \
    's@           o == TriageOutcome::DroppedNoSlot || o == TriageOutcome::DroppedReserve;@           o == TriageOutcome::DroppedNoSlot;@'
mutate_cl_h kill 'C1 Merged and BlockedTargets collapse' \
    's|    BlockedTargets  = 2,|    BlockedTargets  = 1,|'

echo "== C2: the loop and the six handlers (src/engine.cpp)"
mutate_eng kill 'C2 dispatch sends an L1 fill to the L2 handler' \
    's|        case EventKind::L1Fill:  on_l1_fill(\*e.payload.entry, now); return;|        case EventKind::L1Fill:  on_l2_fill(*e.payload.entry, now); return;|'
mutate_eng kill 'C2 reinject always re-enters at the L1 (3.5)' \
    's|    if (r.level == Level::L1) {|    if (true) {|'
mutate_eng kill 'C2 reinject resets the refusal stamp (3.8, I10)' \
    's|, r.refusal, r.core,|, NoRefusal, r.core,|'
mutate_eng kill 'C2 the wake list is reinjected in reverse (I7b)' \
    's|    for (Request\* w : wake) reinject(\*w, now);|    for (auto it = wake.rbegin(); it != wake.rend(); ++it) reinject(**it, now);|'
mutate_eng kill 'C2 an L1 hit does not complete the core line' \
    's|            core_line_done(r, now);||'
mutate_eng kill 'C2 a dropped prefetch does not return its credit' \
    's|        --stats_.pf_outstanding.at(idx(r.core));||'
mutate_eng kill 'C2 grants are never reinjected' \
    's|^    reinject_all(granted_, now);||'
mutate_eng kill 'C2 the return leg is not charged on a fill' \
    's|        queue_.schedule(now + params_.l2_to_l1_latency, EventKind::L1Fill, NoRefusal, t->core,|        queue_.schedule(now, EventKind::L1Fill, NoRefusal, t->core,|'
mutate_eng kill 'C2 the return leg is not charged on an L2 hit' \
    's|            queue_.schedule(now + params_.l2_to_l1_latency, EventKind::L1Fill, NoRefusal, r.core,|            queue_.schedule(now, EventKind::L1Fill, NoRefusal, r.core,|'
mutate_eng kill 'C2 an L1 fill does not install the line' \
    's|    lvl.install(line);||'
mutate_eng kill 'C2 a filled prefetch does not return its credit' \
    's|        if (!t->demand) --stats_.pf_outstanding.at(idx(t->core));||'
# The dangling-pointer obligation plan unit B3 recorded against C2. Without this
# loop the request is released while still carrying a pointer into an entry that
# `retire` has just erased, which the arena refuses by name.
mutate_eng kill 'C2 mshr1 is not cleared before the entry is erased' \
    's|        t->mshr1 = nullptr;||'
mutate_eng kill 'C2 the engine sizes tile_origin without its final entry' \
    's|    tile_origin_.assign(static_cast<std::size_t>(n_tiles) + 1, SimTime{0});|    tile_origin_.assign(static_cast<std::size_t>(n_tiles), SimTime{0});|'
# The fourth intentional `allow`, and the reason is I6 rather than the test
# suite: the guard fires only in a state the engine cannot construct. `mshr1`
# and `level` are written together in `CacheLevel::triage` at the one site that
# forwards, and cleared together in `on_l1_fill` before the entry is erased, so
# every request reaching `on_l2_probe` -- whether forwarded there or reinjected
# from an L2 wait index -- holds its L1 entry by construction. Removing a check
# that never fires cannot change any run, which is the definition of an
# equivalent mutant. The behaviour it guards IS tested: test_engine.cpp's V11
# fixture drives a request through an L2 slot-wait and back.
mutate_eng allow 'C2 the I6 guard at the L2 is removed' \
    's@    if (r.level != Level::L2 || r.mshr1 == nullptr) {@    if (false) {@' \
    'a guard over a state I6 makes unreachable; removing it changes no run'

# Task 4's park point. The whole value of `run_to_barrier` is WHERE it stops:
# one event later and the driver is handed control after `start_tile` has
# already read the next tile, which is the read a shared trace window has to
# happen before. The seeding is here too, since a run whose tile 0 never reaches
# the queue ends immediately with every tile_origin still at zero.
#
# There is no case for "seeded on every call". That mutation makes `run` spin on
# a barrier it re-queues and never dispatches, so it hangs the suite instead of
# failing it, and a case that has to be killed by a timeout is not a result.
mutate_eng kill 'D4 run_to_barrier parks after the barrier, not before' \
    's|        if (queue_.peek_min().kind == EventKind::Barrier) return queue_.peek_min().payload.tile;|        if (queue_.peek_min().kind == EventKind::Barrier) { const std::int32_t bt = queue_.peek_min().payload.tile; const Event<EventPayload> be = queue_.pop_min(); dispatch(be); return bt; }|'
mutate_eng kill 'D4 run_to_barrier never parks at all' \
    's|        if (queue_.peek_min().kind == EventKind::Barrier) return queue_.peek_min().payload.tile;||'
mutate_eng kill 'D4 tile 0 is never seeded' \
    's|        if (trace_.n_tiles() > 0) start_tile(0, SimTime{0});||'
mutate_eng kill 'D4 the D12 checks are skipped when the queue empties' \
    's|    check_no_work_outstanding();||'

echo "== C4: inclusion (src/engine.cpp)"
mutate_eng kill 'C4 back-invalidation is not guarded by the knob' \
    's|res.evicted && params_.inclusion == Inclusion::Inclusive|res.evicted|'
mutate_eng kill 'C4 back-invalidations are not counted' \
    's|            ++stats_.back_invalidations;||'
mutate_eng kill 'C4 the scan stops at the first L1 holding the line' \
    's|            ++stats_.back_invalidations;|            ++stats_.back_invalidations;\n            return;|'
mutate_eng kill 'C4 the invalidated line is not invalidated' \
    's|            l1_\[c\].array().invalidate(s);||'

echo "== C3: the core state machine and the barrier (src/engine_core.cpp)"
mutate_engc kill 'C3 the service floor does not stop at the tile seam' \
    's|    const SimTime want = cs.cursor == BurstIndex{0}|    const SimTime want = false|'
mutate_engc kill 'C3 the cursor is not reset at a tile start' \
    's|        cs.cursor        = BurstIndex{0};||'
mutate_engc kill 'C3 the prefetch cursor is not reset at a tile start' \
    's|        prefetcher_->on_tile_start(cid);||'
mutate_engc kill 'C3 a core with no bursts never clears the barrier' \
    's|        if (trace_.n_bursts(cid, tile) == 0) {|        if (false) {|'
mutate_engc kill 'C3 the barrier fires one core early' \
    's|    if (cores_remaining_ > 0) return;|    if (cores_remaining_ > 1) return;|'
mutate_engc kill 'C3 the tile tail is not charged (Q10)' \
    's|    queue_.schedule(now + as_duration(trace_.tile_tail(tile)), EventKind::Barrier, NoRefusal,|    queue_.schedule(now, EventKind::Barrier, NoRefusal,|'
mutate_engc kill 'C3 tile_origin is written to the tile that just ended' \
    's|    tile_origin_.at(static_cast<std::size_t>(tile) + 1) = now;|    tile_origin_.at(static_cast<std::size_t>(tile)) = now;|'
mutate_engc kill 'C3 issued_at is not recorded' \
    's|^    cs.issued_at     = now;||'
mutate_engc kill 'C3 the core is not marked stalled (I16)' \
    's|^    cs.phase         = Phase::Stalled;||'
mutate_engc kill 'C3 core_stall is not accumulated' \
    's|    stats_.core_stall.at(idx(c)) += stall;||'
mutate_engc kill 'C3 served_time is not advanced' \
    's|^    cs.served_time = now;||'
mutate_engc kill 'C3 the barrier is reached one burst late' \
    's|    if (cs.cursor.get() == trace_.n_bursts(c, cs.tile)) {|    if (cs.cursor.get() > trace_.n_bursts(c, cs.tile)) {|'
# N14 and D13, as a mutation: scheduling the next issue at `now` rather than at
# `now + max(gap, ii)` discards the trace spacing entirely, which is the same
# class of error as v2 adding it to an absolute tick.
mutate_engc kill 'C3 the next issue carries no spacing (N14)' \
    's|    queue_.schedule(now + step_after(c, cs.tile, BurstIndex{cs.cursor.get() - 1}),|    queue_.schedule(now,|'
mutate_engc kill 'C3 the service floor takes the minimum' \
    's|    return gap < params_.core_accept_ii ? params_.core_accept_ii : gap;|    return gap < params_.core_accept_ii ? gap : params_.core_accept_ii;|'

echo "== C5: the prefetch sink (src/engine_core.cpp)"
mutate_engc kill 'C5 the prefetcher is never called' \
    's|    prefetcher_->on_demand_issue(\*this, c, k, now);||'
mutate_engc kill 'C5 the budget is off by one (I14)' \
    's|        if (in_fly >= cap) {|        if (in_fly > cap) {|'
mutate_engc kill 'C5 the demand reserve is not subtracted from the budget' \
    's|    const std::int32_t cap = lvl.mshrs().capacity() - lvl.mshrs().demand_reserve();|    const std::int32_t cap = lvl.mshrs().capacity();|'
mutate_engc kill 'C5 prefetch lines in flight are not counted' \
    's|        ++in_fly;||'
mutate_engc kill 'C5 a prefetch is issued as a demand request (I15)' \
    's|        Request& r = acquire(core, line, k, false, now);|        Request\& r = acquire(core, line, k, true, now);|'
mutate_engc kill 'C5 the tile length is read from the next tile' \
    's|    return trace_.n_bursts(core, cs.tile);|    return trace_.n_bursts(core, cs.tile + 1);|'

echo "== C5: next_burst(d) itself (src/prefetcher.cpp)"
mutate_pf kill 'C5 the cursor is allowed to fall behind the core' \
    's|    if (cursor < next) cursor = next;||'
mutate_pf kill 'C5 the fetch-ahead is one burst short' \
    's|    while (cursor <= last && cursor < n_burst) {|    while (cursor < last \&\& cursor < n_burst) {|'
mutate_pf kill 'C5 the fetch-ahead runs one burst past the tile' \
    's@    while (cursor <= last && cursor < n_burst) {@    while (cursor <= last \&\& cursor <= n_burst) {@'
mutate_pf kill 'C5 a budget refusal is ignored (N16)' \
    's|        if (!mem.issue_prefetch(core, BurstIndex{cursor}, now)) return;|        (void)mem.issue_prefetch(core, BurstIndex{cursor}, now);|'
mutate_pf kill 'C5 on_tile_start does not reset the cursor' \
    's|    pf_cursor_.at(static_cast<std::size_t>(core.get())) = 0;||'
mutate_pf kill 'C5 distance 0 is accepted as next_burst' \
    's|    if (distance < 1) {|    if (distance < 0) {|'
mutate_pf kill 'C5 none is built as next_burst' \
    's|            return std::make_unique<NoPrefetcher>();|            return std::make_unique<NextBurstPrefetcher>(1, n_cores);|'
mutate_pf kill 'C5 the fetch-ahead distance is ignored' \
    's|    const std::int32_t last    = k.get() + distance_;|    const std::int32_t last    = k.get() + 1;|'

echo "== D2a: the stall breakdown and the Part 8 counters (src/engine_core.cpp)"
mutate_engc kill 'D2a stall_total is not accumulated (V21)' \
    's|    stats_.stall_total.at(idx(c)) += stall;||'
mutate_engc kill 'D2a the channel bucket is never charged (V21)' \
    's|        case StallCause::Channel: stats_.stall_channel.at(idx(c)) += stall; break;|        case StallCause::Channel: break;|'
mutate_engc kill 'D2a the L2 slot bucket takes the L1 slot cause (V21)' \
    's|        case StallCause::L1Slot:  stats_.stall_l1_slot.at(idx(c)) += stall; break;|        case StallCause::L1Slot:  stats_.stall_l2_slot.at(idx(c)) += stall; break;|'
mutate_engc kill 'D3 the L1 port bucket is never charged (V21)' \
    's|        case StallCause::L1Port:  stats_.stall_l1_port.at(idx(c)) += stall; break;|        case StallCause::L1Port:  break;|'
mutate_engc kill 'D2a the burst is attributed to the FIRST line, not the last' \
    's|    serve(r.core, now, r.cause);|    serve(r.core, now, StallCause::None);|'
mutate_engc kill 'D2a barrier slack is not charged (V21)' \
    's|        stats_.stall_barrier\[c\] += slack;||'
mutate_engc kill 'D2a barrier slack is charged to the bucket only' \
    's|        stats_.stall_total\[c\] += slack;||'
mutate_engc kill 'D2a the coverage ceiling counts the first burst too' \
    's|    if (k.get() > 0) ++stats_.pf_bursts_eligible;|    ++stats_.pf_bursts_eligible;|'
mutate_engc kill 'D2a prefetches issued are not counted' \
    's|        ++stats_.pf_issued;||'

echo "== D2b: ruling R8, the line anchor (src/engine_core.cpp)"
mutate_engc kill 'D2b the burst anchor is never lowered (R8)' \
    's|    if (anchor < cs.burst_anchor) cs.burst_anchor = anchor;||'
mutate_engc kill 'D2b the burst anchor takes the LAST line, not the earliest' \
    's|    if (anchor < cs.burst_anchor) cs.burst_anchor = anchor;|    cs.burst_anchor = anchor;|'
mutate_engc kill 'D2b the anchor is not reset at the burst issue' \
    's|^    cs.burst_anchor  = now;||'
mutate_engc kill 'D2b fetch_latency reverts to the demand issue (pre-R8)' \
    's|    stats_.fetch_latency.at(idx(c)) += (now - cs.burst_anchor).get();|    stats_.fetch_latency.at(idx(c)) += (now - cs.issued_at).get();|'

echo "== D2a/D2b: the counters and the anchor at their sites (src/engine.cpp)"
mutate_eng kill 'D2a l1 hits are counted on every outcome' \
    's|        if (result == TriageOutcome::Hit) ++stats_.l1_hits;|        ++stats_.l1_hits;|'
mutate_eng kill 'D2a l2 hits are counted on every outcome' \
    's|        if (result == TriageOutcome::Hit) ++stats_.l2_hits;|        ++stats_.l2_hits;|'
mutate_eng kill 'D2a channel traffic is not counted' \
    's|            ++stats_.dram_accesses;||'
mutate_eng kill 'D2a events are not counted' \
    's|    ++stats_.events;||'
mutate_eng kill 'D2a the timely prefetch is not counted (4.6)' \
    's|        ++stats_.pf_timely;||'
mutate_eng kill 'D2a the late prefetch is not counted (4.6)' \
    's|            ++stats_.pf_late;||'
mutate_eng kill 'D2a a promoted prefetch entry is called timely instead of late' \
    's|        if (was_promoted) {|        if (false) {|'
mutate_eng kill 'D2a an evicted prefetched line is not charged as waste' \
    's|    if (res.evicted) note_line_left_l1(e.core, res.evicted_line);||'
mutate_eng kill 'D2a the pollution term is not charged' \
    's|    if (pf_evicted_.at(idx(r.core)).erase(r.line) != 0) ++stats_.pf_pollution_evictions;||'
mutate_eng allow 'D2a a surviving prefetch is not charged as waste' \
    's|        stats_.pf_wasted += static_cast<std::int64_t>(resident.size());||' \
    'no fixture leaves one: next_burst(d) never fetches a burst the core does not reach, so every prefetched line is demanded or evicted first. The branch is what makes the four-state sum total rather than conditional on that argument'
mutate_eng kill 'D2b a demand hit on a prefetched line loses the anchor (R8)' \
    's|        return first_request;|        return r.issued_at;|'
mutate_eng kill 'D2b the fill anchor ignores who opened the entry (R8)' \
    's|        core_line_done(\*t, now, pf_opened ? first_request : t->issued_at);|        core_line_done(*t, now, t->issued_at);|'
mutate_eng allow 'D2a a downgraded hit is not counted (D4, V6)' \
    's|    if (woken_onto_resident \&\& result != TriageOutcome::Hit) ++stats_.hits_downgraded_to_miss;||' \
    'no fixture yet evicts a line between a line waiter waking and re-probing; V6 is the fixture that would'

echo "== D2b: the anchor is written once, at allocate (src/mshr.cpp)"
mutate_mshr kill 'D2b the entry does not record its first request (R8)' \
    's|primary.issued_at, {}, {}};|SimTime{0}, {}, {}};|'
mutate_mshr kill 'D2b every entry claims a prefetch opened it (R8)' \
    's|primary.demand, !primary.demand, primary.issued_at|primary.demand, true, primary.issued_at|'
mutate_mshr kill 'D2b a line waiter is not marked as woken onto its line (D4)' \
    's|        w->line_resident_at_wake = true;||'
mutate_mshr kill 'D2b the slot waiters are marked too (D4)' \
    's|    collect_grants(out.wake);|    collect_grants(out.wake); for (Request* g_ : out.wake) g_->line_resident_at_wake = true;|'

echo "== C5: the interface (include/wcache/prefetcher.h)"
mutate_pf_h kill 'C5 issue_prefetch stops reporting the budget' \
    's|    virtual bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) = 0;|    virtual void issue_prefetch(CoreId core, BurstIndex k, SimTime now) = 0;|'
mutate_pf_h kill 'C5 on_tile_start loses the core it is about' \
    's|    virtual void on_tile_start(CoreId core) = 0;|    virtual void on_tile_start() = 0;|'
mutate_pf_h kill 'C5 the prefetcher may read the memory system by value' \
    's|    virtual void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) = 0;|    virtual void on_demand_issue(PrefetchIssuer mem, CoreId core, BurstIndex k, SimTime now) = 0;|'

echo "== C3: the one crossing from trace time to simulated time (include/wcache/engine.h)"
mutate_eng_h kill 'C3 as_duration loses the offset' \
    's|constexpr SimTime as_duration(LocalTick d) { return SimTime{0} + d; }|constexpr SimTime as_duration(LocalTick d) { (void)d; return SimTime{0}; }|'

echo "== A3: TileTrace, whose whole content is its shape (include/wcache/trace.h)"
mutate_tr kill 'A3 gap loses its const' \
    's|    virtual LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const = 0;|    virtual LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) = 0;|'
mutate_tr kill 'A3 gap returns a SimTime instead of a spacing' \
    's|    virtual LocalTick gap(CoreId core|    virtual SimTime gap(CoreId core|'
mutate_tr kill 'A3 local_tick takes a raw integer core' \
    's|    virtual LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const = 0;|    virtual LocalTick local_tick(std::int64_t core, std::int32_t tile, BurstIndex k) const = 0;|'
mutate_tr kill 'A3 burst is returned by value' \
    's|    virtual const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const = 0;|    virtual Burst burst(CoreId core, std::int32_t tile, BurstIndex k) const = 0;|'

echo "== B3: the two fields Phase C added to the MSHR file"
mutate_mshr_h kill 'B3 is_prefetch_at_issue ignores the entry it holds (P1)' \
    's@    return !r.demand && r.mshr1 == nullptr;@    return !r.demand;@'
mutate_mshr kill 'B3 wait-index membership is not recorded (I5)' \
    's|    r.on_wait_index = true;||'
mutate_mshr kill 'B3 a granted request is left marked as waiting' \
    's|        r->on_wait_index = false;||'
mutate_mshr kill 'B3 line waiters are left marked as waiting' \
    's|    for (Request\* w : out.wake) w->on_wait_index = false;||'
mutate_mshr kill 'B3 the demand reserve is applied to the wrong requests' \
    's|    return is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;|    return is_prefetch_at_issue(r) ? free > 0 : free > demand_reserve_;|'

echo "== D2c: the coverage denominator (src/engine_core.cpp)"
mutate_engc kill 'D2c demand bursts are not counted, so coverage has no denominator' \
    's|    ++stats_.demand_bursts;||'
mutate_engc kill 'D2c the coverage ceiling counts every burst as prefetchable' \
    's|    if (k.get() > 0) ++stats_.pf_bursts_eligible;|    ++stats_.pf_bursts_eligible;|'

echo "== D2c: the results CSV schema (include/wcache/stats.h, src/stats.cpp)"
mutate_stats kill 'D2c a column is dropped from the schema' \
    's|        "max_wait_depth", "hits_downgraded_to_miss", "events", "events_per_cycle",|        "max_wait_depth", "hits_downgraded_to_miss", "events",|'
mutate_stats kill 'D2c two columns are swapped in the schema' \
    's|        "l1_hits", "l1_accesses", "l1_hit_rate",|        "l1_accesses", "l1_hits", "l1_hit_rate",|'
mutate_stats kill 'D2c stretch_cycles adds instead of subtracting' \
    's|    r.i64("stretch_cycles", total_cycles - tick_base_total);|    r.i64("stretch_cycles", total_cycles + tick_base_total);|'
mutate_stats kill 'D2c dram_bytes forgets the line size' \
    's|    r.i64("dram_bytes", es.dram_accesses \* cfg.line_size_bytes());|    r.i64("dram_bytes", es.dram_accesses);|'
mutate_stats kill 'D2c an undefined ratio is emitted rather than left empty' \
    's|        if (den == 0.0) {|        if (false) {|'
mutate_stats kill 'D2c a cell that would break the CSV is accepted' \
    's|!= std::string::npos) {|== std::string::npos) {|'
# Repointed 2026-08-20. The sed used to target `if (l1_latency_ == 0) {`, the
# precondition V21's equality once sat behind. That precondition was removed on
# purpose when `stall_l1_port` took the leftover cycles, and this case was not
# repointed with it, so it matched nothing and covered nothing while the summary
# still read clean. That is the B148-B150 failure mode, caught here only because
# a sed matching nothing is an ERROR rather than a warning. The live guard is
# `check_invariants`'s equality, `src/stats.cpp:369`.
mutate_stats kill 'D2c V21 is never checked as an equality' \
    's|    if (stall_causes_ != stall_total_) {|    if (false) {|'
mutate_stats kill 'D2c a negative hidden_latency passes (R8)' \
    's|    if (hidden_latency_ < 0) {|    if (false) {|'
mutate_stats kill 'D2c the prefetch outcomes need not sum to pf_issued' \
    's|    if (pf_accounted_ != pf_issued_) {|    if (false) {|'
mutate_stats kill 'D2c the occupancy percentile reads unsorted samples' \
    's|    std::sort(s.begin(), s.end());||'
mutate_stats kill 'D2c the oracle arm stops reporting the trace makespan' \
    's|    emit_headline(r, tick_base_total, tick_base_total);|    emit_headline(r, 0, tick_base_total);|'
mutate_stats kill 'D2c pf_coverage_ceiling loses its numerator' \
    's|static_cast<double>(es.pf_bursts_eligible)|static_cast<double>(0)|'
mutate_stats allow 'D2c the emit-position guard is removed' \
    's@        if (cells_.size() >= cols.size().*) {@        if (false) {@' \
    'the guard has no observable effect while the emitter is correct: it exists to catch a FUTURE edit that appends a cell out of order, and no test can exhibit an edit that has not been made. Its removal is caught only by the schema cases above once such an edit exists'

mutate_stats_h kill 'D2c check_invariants drops its const' \
    's|    void check_invariants() const;|    void check_invariants();|'

echo "== D2d: G14's distinct-address diagnostic (include/wcache/hist.h)"
mutate_hist kill 'D2d the sidecar header line changes' \
    's|arch,workload,layer,sample_idx,tile,core,distinct_addresses|arch,workload,layer,sample,tile,core,distinct|'
mutate_hist kill 'D2d every row claims tile 0' \
    's|        tiles_.push_back(trace.window_tile());|        tiles_.push_back(0);|'
mutate_hist kill 'D2d every core reads core 0 of its tile' \
    's|                               static_cast<std::size_t>(c)\]|                               0]|'
mutate_hist kill 'D2d p50 reports a different quantile' \
    's|    std::int32_t p50() const { return quantile(0.5); }|    std::int32_t p50() const { return quantile(0.95); }|'
mutate_hist kill 'D2d max reports the minimum' \
    's|        return \*std::max_element(counts_.begin(), counts_.end());|        return *std::min_element(counts_.begin(), counts_.end());|'

echo "== D2d: distinct_addresses on the stream reader (src/stream_trace.cpp)"
mutate_st kill 'D2d repeated addresses are counted twice' \
    's|    return static_cast<std::int32_t>(std::unique(keys.begin(), keys.end()) - keys.begin());|    return static_cast<std::int32_t>(keys.size());|'
mutate_st kill 'D2d the address key drops the run length' \
    's|        keys.push_back({b.anchor.kh, b.anchor.kw, b.anchor.cin, b.anchor.cout, b.count});|        keys.push_back({b.anchor.kh, b.anchor.kw, b.anchor.cin, b.anchor.cout, 0});|'
mutate_st kill 'D2d distinct_addresses answers with an empty window' \
    's|    if (window_ < 0) {|    if (false) {|'

echo "== Task 15: finish, the end of a run a driver parked (src/engine.cpp)"
mutate_eng kill 'T15 finish is a no-op, so the last barrier is never dispatched' \
    's|^    run();|    return;|'
mutate_eng kill 'T15 finish takes one step instead of draining' \
    's|^    run();|    (void)run_to_barrier();|'

echo "== Task 15: wcache_run (apps/wcache_run.cpp)"
mutate_app kill 'T15 finish is never called, so the makespan is never written' \
    's|^        engine.finish();||'
mutate_app kill 'T15 the header line is not csv_header' \
    's|    if (opt.header) text = csv_header() + "\\n";|    if (opt.header) text = "run_id\\n";|'
mutate_appsup kill 'T15 lines_per_burst is the raw span, ignoring the layout' \
    's|    return static_cast<std::int32_t>(lines.size());|    return hdr.burst_span;|'
mutate_appsup kill 'T15 padding_fraction reports a constant' \
    's|        if (fetched == 0) return 0.0;|        if (fetched >= 0) return 0.5;|'
mutate_app kill 'T15 the histogram never observes the engine arm tiles' \
    's|^            hist.observe(trace);||'

echo "== Task 17: step_tile, one tile of progress (src/engine.cpp)"
mutate_eng kill 'T17 step_tile takes no step at all' \
    's|^bool Engine::step_tile() { return run_to_barrier() >= 0; }|bool Engine::step_tile() { return false; }|'
# The plan's own body for step_tile, kept as a case because it is the fixture
# correction this task made: `run_to_barrier` already dispatches the barrier a
# previous call parked on, so popping it here as well runs through TWO barriers
# whenever one immediately follows another, and the engine ends a tile ahead of
# the window it is sharing.
mutate_eng kill 'T17 step_tile dispatches the parked barrier itself as well' \
    's|^bool Engine::step_tile() { return run_to_barrier() >= 0; }|bool Engine::step_tile() { if (!queue_.empty() \&\& queue_.peek_min().kind == EventKind::Barrier) { const Event<EventPayload> ev = queue_.pop_min(); dispatch(ev); } return run_to_barrier() >= 0; }|'

echo "== D3a: BroadcastSweep, lockstep over one stream (include/wcache/sweep.h, src/sweep.cpp)"
mutate_sweep_h kill 'D3a size() reports one engine fewer' \
    's|    std::size_t      size() const { return engines_.size(); }|    std::size_t      size() const { return engines_.size() - 1; }|'
mutate_sweep kill 'D3a every point runs configuration 0' \
    's|to_engine_params(configs_\[i\])|to_engine_params(configs_[0])|'
mutate_sweep kill 'D3a an engine takes two tiles per window' \
    's|                (void)engines_\[i\]->step_tile();|                (void)engines_[i]->step_tile(); (void)engines_[i]->step_tile();|'
mutate_sweep kill 'D3a finish is never called, so the last barrier is never dispatched' \
    's|            engines_\[i\]->finish();||'
mutate_sweep kill 'D3a the tile observer is never called' \
    's|        if (on_tile) on_tile(\*trace_);||'
mutate_sweep kill 'D3a a mixed-layout grid is accepted' \
    's|            c.weight_bytes != first.weight_bytes) {|            false) {|'
mutate_sweep kill 'D3a max_engines is not enforced' \
    's|    if (configs_.size() > static_cast<std::size_t>(max_engines)) {|    if (false) {|'
mutate_sweep kill 'D3a a mapper built for another line size is accepted' \
    's|    if (mapper.line_size_bytes() != first.line_size_bytes()) {|    if (false) {|'

echo "== D3b: the sweep grid (src/config.cpp)"
mutate_cfg kill 'D3b the LAST declared axis varies slowest' \
    's|        for (std::size_t i = axes.size(); i-- > 0;) {|        for (std::size_t i = 0; i < axes.size(); ++i) {|'
mutate_cfg kill 'D3b the cross product is one point wide' \
    's|    for (const GridAxis& a : axes) points \*= a.values.size();|    for (const GridAxis\& a : axes) points *= 1;|'
mutate_cfg kill 'D3b base is dropped, so every point is the default' \
    's|        RunConfig   cfg = base;|        RunConfig   cfg;|'
mutate_cfg kill 'D3b an array grid keeps only its last element' \
    's|                grid.push_back(cfg);|                grid.assign(1, cfg);|'

echo "== Task 18: wcache_sweep (apps/wcache_sweep.cpp)"
mutate_sweep_app kill 'T18 every row reports the first point stats' \
    's|sweep.engine(i).stats()|sweep.engine(0).stats()|'
mutate_sweep_app kill 'T18 the header line is emitted before every row' \
    's|    if (opt.header) text = csv_header() + "\\n";|    if (opt.header) text = "";|'
mutate_sweep_app kill 'T18 the padding meter never sees a tile' \
    's|        padding.observe_tile(window);||'

echo
echo "$((killed + survived + unexpected)) mutations: $killed killed, $survived survived as expected, $unexpected unexpected"
if [ -n "$FILTER" ]; then
    echo "FILTERED run: only files matching '$FILTER', $skipped cases skipped"
fi
[ "$unexpected" -eq 0 ]
