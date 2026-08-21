#include "wcache/mshr.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

namespace wcache {
namespace {

// One spelling of each prefix, so every message this file produces is findable
// by grepping for the class name and no two of them disagree about the
// punctuation. block_pack.cpp sets the convention; the verb is a parameter here
// because one class carries several of them.
[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("MshrFile: " + what);
}

[[noreturn]] void caller_error(const char* verb, const std::string& what) {
    throw std::logic_error("MshrFile::" + std::string(verb) + ": " + what);
}

// One spelling of the positivity rule, for set_associative.cpp's reason: the
// cases below differ only in which quantity they name, and hand-written
// messages are chances for them to drift apart. The value is always printed,
// because a 0 from a config field nobody set and a negative from one decoded
// wrong look nothing alike in a log.
void at_least_or_reject(const char* name, std::int32_t v, std::int32_t floor) {
    if (v < floor) {
        reject(std::string(name) + " must be >= " + std::to_string(floor) + ", got " +
               std::to_string(v));
    }
}

// std::vector and std::unordered_map report their sizes with an unsigned
// size_type, so every count this class compares against a config field converts
// on the way out. The one such conversion goes through here, which keeps the
// arithmetic above it signed: with the cast spread across expressions instead,
// -Wsign-conversion would be answered with several casts rather than one
// reviewable site. The counts fit an int32 because the constructor bounds
// `capacity` at one, and nothing here can exceed it: entries are refused past
// capacity, and the wait indices are bounded by the credit supply (4.1).
std::int32_t as_count(std::size_t v) { return static_cast<std::int32_t>(v); }

}  // namespace

RefusalOrder RefusalCounter::next() {
    const RefusalOrder stamp{next_};
    ++next_;
    return stamp;
}

// Write-once, at the FIRST refusal, at any level, and `reinject` never touches
// it. So a request enters the waiting population exactly once and is served in
// stamp order forever after, however many times it is re-refused and whichever
// index holds it. That is FIFO by first refusal (3.8), and it is what makes
// starvation freedom provable: if the stamp were reset on a wake, an aged
// request would lose to every fresh arrival at high load, forever (I10).
void mark_refused(Request& r, WaitReason reason, RefusalCounter& counter) {
    if (r.refusal == NoRefusal) {
        r.refusal = counter.next();
        r.reason  = reason;
    }
}

MshrFile::MshrFile(std::int32_t capacity,
                   std::int32_t tgts_per_mshr,
                   std::int32_t demand_reserve,
                   RefusalCounter& counter)
    : capacity_(capacity),
      tgts_per_mshr_(tgts_per_mshr),
      demand_reserve_(demand_reserve),
      counter_(counter) {
    at_least_or_reject("capacity", capacity, 1);
    at_least_or_reject("tgts_per_mshr", tgts_per_mshr, 1);
    at_least_or_reject("demand_reserve", demand_reserve, 0);

    // A reserve larger than the file would make the prefetch budget negative,
    // which is not "prefetching is off" but a bound that reads backwards.
    // Equal is legal and is the default demand-only configuration (4.2).
    if (demand_reserve > capacity) {
        reject("demand_reserve " + std::to_string(demand_reserve) +
               " exceeds the file's capacity of " + std::to_string(capacity) + " entries");
    }
}

std::int32_t MshrFile::live() const { return as_count(entries_.size()); }

std::int32_t MshrFile::slot_wait_depth() const { return as_count(slot_wait_.size()); }

Mshr* MshrFile::find(LineId line) {
    const auto it = entries_.find(line);
    return it == entries_.end() ? nullptr : &it->second;
}

bool MshrFile::has_slot(const Request& r) const {
    // A grantee spends the credit the grant loop already counted, so admitting
    // it does not push `live + reserved` past the capacity: the reservation
    // becomes an entry and the two totals trade one for one (I4).
    if (r.reserved) return true;

    const std::int32_t free = capacity_ - live() - reserved_;
    // A prefetch may never take the last `demand_reserve` entries, so one
    // demand burst can always allocate: prefetching can delay demand but never
    // starve it (B12). At `demand_reserve == capacity` this is false for every
    // prefetch, which is the budget being zero rather than a special case.
    //
    // The reserve applies to a prefetch AT ISSUE. A prefetch that has already
    // been forwarded holds an L1 entry and is a fetch this file cannot cancel,
    // so refusing it here would strand that entry rather than save a credit; see
    // `is_prefetch_at_issue`.
    return is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0;
}

Mshr& MshrFile::allocate(LineId line, Request& primary) {
    if (entries_.find(line) != entries_.end()) {
        caller_error("allocate", "line " + std::to_string(line.get()) +
                                     " already has a live entry");
    }
    if (!has_slot(primary)) {
        // The prefetch half of the message is not decoration: at
        // `demand_reserve > 0` a prefetch is refused while free entries remain,
        // so a message reporting only the counts would read as arithmetic that
        // does not add up.
        std::string why = "no free entry: " + std::to_string(live()) + " live plus " +
                          std::to_string(reserved_) + " reserved of " +
                          std::to_string(capacity_);
        if (!primary.demand) {
            why += ", and a prefetch may not take the last " +
                   std::to_string(demand_reserve_) + " entries";
        }
        caller_error("allocate", why);
    }

    // The primary occupies the first target slot, so it is satisfied by the
    // fill through the same loop as every later merge and there is no second
    // path that could satisfy it differently. It is also what makes 4.1's
    // per-entry bound `n_cores - tgts_per_mshr` exact rather than off by one.
    // `pf_opened` and `first_request` are written here and never again: R8's
    // anchor is the FIRST request for the line, so a later demand promoting the
    // entry must leave both alone or the head start it measures disappears.
    Mshr entry{line, primary.core, primary.demand, !primary.demand, primary.issued_at, {}, {}};
    entry.targets.push_back(&primary);

    // Spent here rather than by a second call the caller must remember (see the
    // header). Written as the reservation's own release so the credit cannot be
    // both reserved and live at once.
    if (primary.reserved) {
        primary.reserved = false;
        --reserved_;
    }

    return entries_.emplace(line, std::move(entry)).first->second;
}

bool MshrFile::add_target(Mshr& e, Request& r) {
    if (as_count(e.targets.size()) >= tgts_per_mshr_) return false;
    e.targets.push_back(&r);
    // 4.6's promotion, as an or: a demand request merging onto a prefetch entry
    // makes the entry a demand entry, and every other combination leaves it as
    // it was. Idempotent by construction, which is B3's exit criterion.
    e.demand = e.demand || r.demand;
    return true;
}

void MshrFile::push_line_wait(Mshr& e, Request& r) {
    if (is_prefetch_at_issue(r)) {
        caller_error("push_line_wait", "a prefetch is dropped, never queued (N16)");
    }
    mark_refused(r, WaitReason::Line, counter_);
    r.on_wait_index = true;
    e.line_wait.push_back(&r);
}

void MshrFile::push_slot_wait(Request& r) {
    if (is_prefetch_at_issue(r)) {
        caller_error("push_slot_wait", "a prefetch is dropped, never queued (N16)");
    }
    mark_refused(r, WaitReason::Slot, counter_);
    r.on_wait_index = true;
    slot_wait_.push_back(&r);
}

bool MshrFile::release_reservation(Request& r) {
    if (!r.reserved) return false;
    r.reserved = false;
    --reserved_;
    return true;
}

// Pops at most `capacity - live - reserved` waiters, oldest first, and reserves
// a credit for each. Terminates because every iteration strictly increases
// `reserved_` while the loop's own bound is fixed (I7).
//
// `std::min_element` under 3.8's key rather than a pop from the front: the
// index is NOT in age order, because a slot waiter can outlive the allocation
// of an entry it later merges onto and be pushed back carrying an older stamp
// than what is already there (3.8's counterexample). Taking the front would
// grant the wrong request in exactly that case, and the sort in `retire` would
// then order a wake list that already had the wrong members in it.
void MshrFile::collect_grants(std::vector<Request*>& out) {
    while (live() + reserved_ < capacity_ && !slot_wait_.empty()) {
        const auto oldest = std::min_element(
            slot_wait_.begin(), slot_wait_.end(),
            [](const Request* a, const Request* b) { return key_less(*a, *b); });
        Request* r = *oldest;
        slot_wait_.erase(oldest);
        // Off the index and holding a credit instead. One of the two places a
        // request leaves an index, so one of the two places I5's bit is cleared.
        r->on_wait_index = false;
        r->reserved      = true;
        ++reserved_;
        out.push_back(r);
    }
}

void MshrFile::retire(Mshr& e, RetireResult& out) {
    const auto it = entries_.find(e.line);
    if (it == entries_.end() || &it->second != &e) {
        caller_error("retire", "line " + std::to_string(e.line.get()) +
                                   " is not a live entry of this file");
    }

    // Replaces rather than appends, and both halves are read out before the
    // entry is erased. `out.targets` is assigned rather than swapped so a
    // caller reusing one buffer keeps its capacity.
    out.targets = e.targets;
    out.wake    = e.line_wait;

    // The other place a request leaves an index: this entry's line waiters all
    // leave together, since a target list never drains incrementally and the
    // whole set resolves at retire (3.7). I5's bit is cleared here rather than
    // by the engine because the exit is here.
    //
    // Every one of them was woken by the fill of the line it was waiting on, so
    // the line is resident at this instant and the re-probe that follows is a
    // hit unless something evicts it first (D4, V6). The bit records that,
    // before `collect_grants` appends slot waiters, which carry no such
    // guarantee.
    for (Request* w : out.wake) {
        w->on_wait_index         = false;
        w->line_resident_at_wake = true;
    }

    entries_.erase(it);

    // After the erase, so the credit this retire freed is one the loop can hand
    // out. Before the sort, because the granted waiters are part of the same
    // ordered wake list: reinjection reserves a port, so collecting them into a
    // second loop would stagger the wake by loop order rather than by age,
    // which is what I7b forbids.
    collect_grants(out.wake);

    // Stable, so that if two stamps ever tie the result is still a function of
    // insertion order rather than of the sort's internals. They cannot tie
    // today -- every member of both indices was stamped by the write-once
    // counter (I2) -- and that is exactly why the weaker guarantee is free.
    std::stable_sort(out.wake.begin(), out.wake.end(),
                     [](const Request* a, const Request* b) { return key_less(*a, *b); });
}

}  // namespace wcache
