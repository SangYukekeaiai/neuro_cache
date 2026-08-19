// MshrFile: the outstanding lines of one cache level, and who is waiting on them.
//
// Plan v3 Part 7, unit B3: "`MshrFile`: entries, `targets`, `line_wait`,
// `slot_wait`, the refusal counter, `find`/`allocate`/`retire`, the grant loop.
// (v3) `Request` carries `burst` and `demand`, `Mshr` carries a mutable
// `demand` for the promotion path, and `allocate` honours `demand_reserve`."
//
// One class for both levels. Part 2.2's "L1 MSHR file" row and Part 2.3's "L2
// MSHR file" row name the same structure with different capacities, and 3.4's
// two triage functions are, in the plan's own words, of "identical shape".
//
// What this unit does NOT do, and the boundary is the unit's definition (Phase
// B is "timing primitives: clock exists, hierarchy does not"): it never
// reserves a port, never schedules an event, and never knows which level it is.
// `retire` therefore reports WHO was satisfied and WHO wakes, in order, and the
// engine decides what that means at its level -- at the L2 an `E_L1Fill` per
// target, at the L1 a `core_line_done` per target (3.4). Two consequences worth
// stating, because both are load-bearing later: this file cannot violate P2 by
// predicting a time, since it holds no clock; and the merge-and-sort that I7b
// rests on happens here, once, rather than in each caller.
//
// P5 is the reason the wait indices below store pointers and nothing else. "A
// request that is refused is already held somewhere: at the L2 by its own L1
// MSHR entry, at the L1 by its core's outstanding-burst registers. A wait list
// therefore stores nothing; it selects." These vectors are selection sets over
// structures the engine already owns, and the requests they point at must
// outlive their membership. Any design that copied a refused request into a
// buffer here would have invented hardware, and 4.1's bound would become an
// argument about simulator memory rather than about credits.
#pragma once

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "wcache/types.h"

namespace wcache {

struct Mshr;

// Which level a woken request re-enters at (3.5).
//
// It is a field on the request rather than a fact about the wait index it sat
// in, because the two L2 indices and the two L1 indices are the same code: a
// request woken from `l2_mshr.slot_wait` re-enters at the L2 and NOT at the top
// of the hierarchy, and a re-triage at the L1 would find its own entry, merge
// the request into itself, and leave it waiting for a fill nobody will request.
enum class Level : std::uint8_t { L1 = 0, L2 = 1 };

// 3.7's wait reason, `{SLOT, LINE(l)}`.
//
// Two indices, one population (3.7, N6). The reason is what prevents the
// livelock: a LINE waiter woken by an unrelated retire re-blocks on the same
// condition, is popped again, and the freed slot is never consumed, so the two
// must stay distinguishable by WHAT RELEASES THEM.
//
// `LINE(l)` carries no line here, and that is deliberate rather than a
// simplification: a request only ever line-waits on the entry matching its own
// address, so the `l` of `LINE(l)` is always `r.line`. Storing it a second time
// would be a field that can disagree with the one beside it, which is the shape
// B89 made unrepresentable for `InsertResult::evicted`.
enum class WaitReason : std::uint8_t { None = 0, Slot = 1, Line = 2 };

// One line request travelling the hierarchy (3.3).
//
// The first three fields have no defaults because the tagged scalars have no
// default constructor (B2): a defaulted CoreId would mean core 0 and a
// defaulted BurstIndex would mean the first burst of the tile, both of which
// are valid values a forgotten initialiser would produce silently. The rest
// carry 3.3's own defaults, so `Request{CoreId{c}, LineId{l}, BurstIndex{k}}`
// is a fresh demand request and `Request{CoreId{c}, LineId{l}, BurstIndex{k},
// false}` is a prefetch.
//
// Not built: 3.3's `seq`. Nothing in Part 3 reads it, and 3.8 records that the
// `seq` of the event key is dead for the class where a refusal stamp exists.
// The `seq` that IS load-bearing is assigned at schedule time and belongs to
// the event (3.6), where event.h's EventSeq carries it; a second int64 counter
// of the same name on the request would be the N12 confusion the tagged types
// exist to stop, in the one place a reader is most likely to conflate them.
struct Request {
    CoreId     core;
    LineId     line;
    BurstIndex burst;  // which burst of the core's tile; a prefetch carries a future one

    // False for a prefetch: nobody is waiting on it, it never enters a wait
    // index, and it is DROPPED rather than refused (4.6, B11, N16). That single
    // rule is what keeps the waiting population backed one-for-one by demand
    // credits at any `prefetch_distance`, which is the whole of 4.1's argument.
    bool demand = true;

    // The global refusal COUNTER's value at this request's FIRST refusal, not a
    // tick (3.8). Write-once, which is what makes starvation freedom provable
    // (I10): the set of requests with a smaller stamp is finite and never
    // grows.
    RefusalOrder refusal = NoRefusal;

    // The reason of that first refusal, and write-once with it, exactly as
    // 3.8's `mark_refused` spells it. Note what that means and what it does
    // not: a request first refused for a slot and later re-refused onto a
    // line-wait index still reports Slot here, so this field is the reason it
    // ENTERED the waiting population and not the index that currently holds it.
    // Correctness does not rest on it -- what releases a waiter is which vector
    // holds it -- but Part 8's "reported separately by wait reason" does, and
    // that divergence is recorded rather than designed around.
    WaitReason reason = WaitReason::None;

    // Where to RE-ENTER on wake (3.5), not where it is now.
    Level level = Level::L1;

    // The L1 entry this request holds, once it has been FORWARDED at the L1.
    // I6: `r.level == L2 <=> r.mshr1 != null`. It is still held across the whole
    // downstream round trip, which is what makes the L2's wait sets views over
    // structures that already exist rather than storage (4.1, I6b).
    //
    // Non-owning. The entry lives in an MshrFile's map and outlives this
    // pointer by construction, since the request is satisfied or woken by that
    // entry's own retire.
    Mshr* mshr1 = nullptr;

    // Holds a slot-grant reservation handed out by the grant loop (3.8). Not a
    // second queue: it is what stops a wake producing a thundering herd racing
    // for one freed slot.
    bool reserved = false;
};

// One outstanding line (3.3).
//
// `targets` and `line_wait` are public data, in the tree's plain-struct style,
// and are appended to ONLY through MshrFile, which is what keeps I3
// (`|targets| <= tgts_per_mshr`) in one place. Reading them is the point: the
// engine iterates targets at retire and Part 8 reports both depths.
struct Mshr {
    LineId line;
    CoreId core;  // unused at the L2, where entries are not per-core

    // True once anything waiting on this line is a demand request. Mutable
    // rather than fixed at construction, which is 4.6's promotion path: a
    // prefetch entry the core's own demand request later merges onto becomes a
    // demand entry, the late-prefetch case where the fetch started early but
    // not early enough.
    bool demand;

    // The committed subentries, satisfied DIRECTLY by the fill with no
    // re-triage (3.7). The primary occupies the first slot, which is what makes
    // 4.1's per-entry bound `n_cores - tgts_per_mshr` rather than one less, and
    // it is also gem5's meaning of the word (Appendix B).
    //
    // At the L2 the plan stores the waiting L1 ENTRY here instead of the
    // request. This holds the request either way, and the two are the same
    // object by I6b, which says the map from an L2 waiter to its `mshr1` is
    // injective: no two requests on any L2 wait index share an L1 entry. One
    // storage type rather than two turns that bijection from a structural
    // assumption into something a fixture can check, and the engine reaches the
    // entry with `r.mshr1` at the one site that needs it.
    std::vector<Request*> targets;

    // Requests that arrived after the target list filled, waiting on THIS
    // entry's line (D5). Released by this entry retiring and by nothing else,
    // all of them at once, as hits.
    //
    // A target list in a read-only cache never drains incrementally, so nothing
    // is ever promoted from here into `targets`: the whole set resolves at
    // retire. A model that promoted on a free target slot would be modelling a
    // drain that cannot happen (3.7).
    std::vector<Request*> line_wait;
};

// The global stamp source of 3.8. One per run, shared by every MshrFile, because
// a request refused at the L1 and again at the L2 keeps its original stamp and
// so carries L2 seniority reflecting how long it has genuinely waited.
class RefusalCounter {
public:
    // The next stamp, and the counter advances. 64-bit (Q8, closed): a run's
    // total refusals over a full trace at 256 cores can exceed 32 bits, and a
    // wrap would silently reorder the FIFO.
    RefusalOrder next();

    // How many stamps have been issued, which is also the value of the next
    // one. V18 asserts that every waiter's stamp is written exactly once and is
    // unique across the run; this is the count that check compares against.
    std::int64_t issued() const { return next_; }

private:
    std::int64_t next_ = 0;
};

// 3.8's `mark_refused`, write-once at the FIRST refusal at any level.
//
// A free function rather than a method because it belongs to neither the
// counter nor the file: it is the rule joining them. MshrFile calls it on every
// push onto a wait index, so the pairing cannot drift.
void mark_refused(Request& r, WaitReason reason, RefusalCounter& counter);

// 3.8's key, `key(r) = (r.refusal == NONE, r.refusal)`, collapsed to one
// compare. NoRefusal is INT64_MAX (B3), so a fresh request sorts after every
// refused one under plain `<` and the refused bit is not a second field.
inline bool key_less(const Request& a, const Request& b) { return a.refusal < b.refusal; }

// What a retire hands back to the engine, in the two groups 3.4 separates.
//
// Two vectors and not one, because the two are released differently and acting
// on them alike is D5's livelock in the other direction: a target is satisfied
// directly by the fill and never re-triages, while a woken waiter goes back
// through its level's port and re-probes (3.7, N5).
struct RetireResult {
    // The entry's committed subentries, the primary first, in the order they
    // merged. Satisfied directly: at the L2 the engine schedules an `E_L1Fill`
    // for each, at the L1 it calls `core_line_done` (3.4).
    std::vector<Request*> targets;

    // Everything that wakes, in ONE key-ordered list: this entry's line waiters,
    // all of them, plus the slot waiters the grant loop could pay for. The
    // engine reinjects them in this order.
    //
    // The merge is mandatory rather than tidy, and the sort is not redundant.
    // Reinjection reserves a port, so iterating the two indices separately
    // would stagger the wake by loop order instead of by age; and a wait set is
    // NOT already in age order, because a slot waiter can outlive the
    // allocation of an entry it later merges onto and arrive carrying an older
    // stamp than what is already there (3.8's counterexample).
    std::vector<Request*> wake;
};

// The file itself: a CAM over outstanding line addresses, bounded by capacity.
//
// Allocated on a primary miss and freed on fill ARRIVAL, held across the whole
// downstream round trip (2.2). That is what makes L1 MSHR occupancy mean the
// full round trip including L2 queueing delay (4.2), and it is what makes the
// L2's wait sets free.
class MshrFile {
public:
    // `capacity` is `l1_mshrs` or `l2_mshrs`, `tgts_per_mshr` is
    // `l1_tgts_per_mshr` or `l2_tgts_per_mshr`, and `demand_reserve` is
    // `l1_demand_reserve` or `l2_demand_reserve` (2.5b). All three are config
    // fields, so every rejection is a `throw` and not an `assert`: the sweep
    // build is -DNDEBUG and a sweep grid is a cross product.
    //
    // The order of the checks is load-bearing and is therefore stated rather
    // than left to be inferred, in B62's shape:
    //
    //   1. `capacity >= 1`. A file that can hold nothing forwards nothing, and
    //      every check after this one compares against it.
    //   2. `tgts_per_mshr >= 1`. The primary occupies a target slot, so a zero
    //      here is an entry that cannot record its own allocator.
    //   3. `demand_reserve >= 0`.
    //   4. `demand_reserve <= capacity`, which is a relation between two fields
    //      and only means anything once both have been accepted.
    //
    // `demand_reserve == capacity` is ACCEPTED, and that is the default
    // configuration rather than an edge case: `l1_demand_reserve` defaults to
    // `lines_per_burst`, so at `l1_mshrs == lines_per_burst` the prefetch budget
    // is exactly zero and prefetching is off however `prefetch_distance` is set
    // (4.2). D1's stricter rule, that `demand_reserve >= mshrs` throws, is a
    // rule about a config that ALSO claims `prefetch_policy = next_burst`, which
    // is a field this class never sees.
    //
    // Throws std::invalid_argument, naming the offending value.
    MshrFile(std::int32_t capacity,
             std::int32_t tgts_per_mshr,
             std::int32_t demand_reserve,
             RefusalCounter& counter);

    // The entry for `line`, or null when there is none. 3.4's `F.entries.find`,
    // the second step of the probe order after the array and before the next
    // level, and the step that makes a secondary miss cost zero downstream
    // traffic.
    Mshr* find(LineId line);

    // Whether `r` may allocate an entry now. 3.4's `has_slot(F, r)`.
    //
    // Three answers in one predicate, and the middle one is the reservation
    // system working: a request that already holds a grant is admitted
    // unconditionally, because the credit it is about to spend is the one
    // `collect_grants` set aside for it and is already counted in `reserved`.
    // Without that case a grantee would be refused by its own reservation.
    //
    // A demand request needs one free credit. A prefetch needs one more than
    // `demand_reserve`, so it can never take the last `demand_reserve` entries
    // and a demand burst can always allocate (4.6, B12).
    bool has_slot(const Request& r) const;

    // Allocates the entry for `line` with `primary` as its first target, and
    // spends `primary`'s reservation if it held one.
    //
    // The plan writes the spend as a separate `consume_reservation(r, F)` call
    // after every allocate, at both levels and with no exception. Folding it in
    // removes a pairing a caller can forget, in the same spirit as I3 living
    // inside `add_target`: a leaked reservation is a credit the file never
    // hands back, so the grant loop stops one waiter short for the rest of the
    // run and the symptom is a stall attributed to the MSHR bound.
    //
    // Throws std::logic_error when `line` already has an entry (I1: at most one
    // live Mshr per line per level) or when `has_slot(primary)` is false. Both
    // are caller errors -- 3.4 checks `find` and `has_slot` first, in that
    // order -- which B27 puts in the programmer-error tier. A throw and not an
    // assert, because a second entry for one line double-fetches it and a
    // silently over-full file reports an occupancy the sweep is measuring.
    Mshr& allocate(LineId line, Request& primary);

    // Merges `r` onto `e` as a committed subentry, and promotes `e` to a demand
    // entry if `r` is a demand request. Returns false, changing nothing, when
    // the target list is already at `tgts_per_mshr`, which is the caller's
    // signal to line-wait instead (3.4's BLOCKED_TARGETS).
    //
    // The bound lives here so I3 cannot be violated by a caller that checked it
    // and then pushed anyway, and the promotion lives here so 4.6's late-
    // prefetch path cannot be forgotten at one of its call sites. Promotion is
    // idempotent by construction rather than by discipline: it is an or, so a
    // demand entry stays demand and merging a prefetch onto a demand entry
    // changes nothing.
    bool add_target(Mshr& e, Request& r);

    // Registers `r` as waiting on `e`'s line (3.4's BLOCKED_TARGETS) or on any
    // free entry (BLOCKED_POOL), stamping its first refusal on the way in.
    //
    // The stamp and the push are one call for the reason `allocate` spends the
    // reservation: 3.8's `mark_refused` immediately precedes every push in the
    // plan, at both levels and on both indices, and a push that skipped it
    // would put an unstamped request into a population ordered by stamp, where
    // NoRefusal sorts it last forever.
    //
    // Both throw std::logic_error for a request with `demand == false`. A
    // refused prefetch is DROPPED, never queued (N16, B11), and that is the one
    // rule keeping the waiting population backed one-for-one by demand credits;
    // I15 states it as an invariant, and it is cheaper to make it
    // unrepresentable here than to look for it in a sweep.
    void push_line_wait(Mshr& e, Request& r);
    void push_slot_wait(Request& r);

    // Releases a grant `r` turned out not to need, because it re-triaged into a
    // hit or a merge (3.8). Returns true when a credit was actually freed, so
    // the caller knows to run the grant loop again and hand it to the next
    // waiter; a request that held no reservation is not an error, since 3.4
    // calls this on every hit and merge whether or not one was held.
    //
    // It does not re-grant by itself, because granting reinjects and
    // reinjection reserves a port, which is the hierarchy this unit does not
    // have.
    bool release_reservation(Request& r);

    // Retires `e`: its targets are reported as satisfied, the entry is erased,
    // and everything that wakes is collected and sorted into one key-ordered
    // list. `out` is REPLACED, not appended to, so a caller may reuse one
    // buffer across retires.
    //
    // The internal order is load-bearing and is 3.4's:
    //
    //   1. copy the targets out, before the entry is erased.
    //   2. take the line waiters, all of them: they need no slot and will all
    //      hit, since the line is resident by the time they re-probe.
    //   3. ERASE the entry, and only then run the grant loop, so the credit
    //      this retire freed is the one the loop can hand out. Collecting
    //      first would grant one waiter fewer at every retire.
    //   4. sort the merged list by 3.8's key.
    //
    // Throws std::logic_error when `e` is not an entry of this file.
    void retire(Mshr& e, RetireResult& out);

    std::int32_t capacity() const { return capacity_; }
    std::int32_t tgts_per_mshr() const { return tgts_per_mshr_; }
    std::int32_t demand_reserve() const { return demand_reserve_; }

    // Live entries and outstanding grants. Part 8's headline instrument is the
    // MSHR occupancy histogram per level, which is sampled from `live()`, and
    // I4 (`|entries| + reserved <= capacity`) is checked from both.
    std::int32_t live() const;
    std::int32_t reserved() const { return reserved_; }

    // The slot-wait index's current depth. Part 8 reports the wait population
    // by reason, and I11's global bound is checked against this plus the
    // per-entry line-wait depths.
    std::int32_t slot_wait_depth() const;

private:
    // Pops as many slot waiters as there are free credits, oldest first,
    // reserving one credit for each (3.8's `collect_grants`). Appends to `out`;
    // it does not inject, because injection is the engine's.
    void collect_grants(std::vector<Request*>& out);

    std::int32_t capacity_;
    std::int32_t tgts_per_mshr_;
    std::int32_t demand_reserve_;

    // Granted-but-not-yet-spent slots. Grant is reservation-based rather than
    // optimistic (3.8), so a wake never produces a thundering herd racing for
    // one slot.
    std::int32_t reserved_ = 0;

    RefusalCounter& counter_;

    // `line -> Mshr`, which is what bounds a core to at most one entry per line
    // and therefore at most one request per core reaching the L2 for any given
    // line (I6b, 4.1).
    //
    // A node-based map rather than a vector, because `Request::mshr1` and every
    // `Mshr&` handed to a caller must stay valid while other entries are
    // allocated and retired around them; std::unordered_map guarantees exactly
    // that, and a vector reallocating would leave every held entry dangling.
    // Nothing ever ITERATES it, which is what keeps its unspecified order out
    // of the run: every read is a lookup by line or a size.
    std::unordered_map<LineId, Mshr> entries_;

    // The requests refused for want of any entry (D5's SLOT), released by ANY
    // entry retiring. A selection set over structures the engine already owns
    // (P5), which is why it holds pointers and has no depth limit: at the L1
    // its members live in the core's outstanding-burst registers, at the L2 in
    // the L1 MSHR entries they still hold.
    std::vector<Request*> slot_wait_;
};

}  // namespace wcache
