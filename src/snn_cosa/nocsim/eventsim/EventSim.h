// EventSim.h — discrete-event NoC latency simulator.
//
// Design (see PLAN_eventsim_latency.md for the full rationale):
//   - Coarse link occupancy: a unicast/multicast claims its entire route
//     for its full duration (no per-flit pipelining).
//   - Multicast: farthest-only. A multicast occupies only the links on the
//     path to its single farthest destination (same route used for its
//     cost, per Plan 1's static metric) -- closer branches are not
//     separately tracked.
//   - DRAM-touching transactions (src or dest == dram_port): duration is
//     size * dram_latency, with NO link/hop term -- DRAM traffic does not
//     use NoC mesh links (see transactions/dram.py), matching Plan 1's
//     dram_cost formula exactly.
//   - Each actor_id (port) runs at most one transaction at a time.
//   - A transaction dispatches once its dependencies have all finished
//     (event-driven) AND its actor + every link on its route are free
//     (resource contention) -- ties among simultaneously-ready
//     transactions broken by ascending tc_id for determinism.
#pragma once

#include <algorithm>
#include <map>
#include <queue>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "NoC.h"
#include "Transaction.h"

constexpr int FLITS_PER_PACKET = 4;  // must match core/transaction.py

struct SimResult {
    long long total_cycles     = 0;
    long long unicast_cycles   = 0;
    long long multicast_cycles = 0;
    long long count_cycles     = 0;
    long long dram_cycles      = 0;
};

inline bool touches_dram(const Transaction& tc, int dram_port) {
    if (tc.actor_id == dram_port) return true;
    for (int d : tc.dests) {
        if (d == dram_port) return true;
    }
    return false;
}

inline SimResult simulate(const std::vector<Transaction>& tcs, const NoC& noc,
                           int dram_port, long long dram_latency) {
    const int n = static_cast<int>(tcs.size());

    std::unordered_map<int, int> id_to_idx;
    id_to_idx.reserve(n * 2);
    for (int i = 0; i < n; ++i) {
        if (!id_to_idx.emplace(tcs[i].tc_id, i).second) {
            throw std::runtime_error("duplicate tc_id " + std::to_string(tcs[i].tc_id));
        }
    }

    std::vector<int> remaining_deps(n, 0);
    std::vector<std::vector<int>> dependents(n);
    for (int i = 0; i < n; ++i) {
        remaining_deps[i] = static_cast<int>(tcs[i].deps.size());
        for (int dep_tc_id : tcs[i].deps) {
            auto it = id_to_idx.find(dep_tc_id);
            if (it == id_to_idx.end()) {
                throw std::runtime_error("tc_id " + std::to_string(tcs[i].tc_id) +
                                          " depends on unknown tc_id " + std::to_string(dep_tc_id));
            }
            dependents[it->second].push_back(i);
        }
    }

    std::map<int, long long> actor_free_time;
    std::map<Link, long long> link_free_time;

    auto get_actor_free = [&](int actor) -> long long {
        auto it = actor_free_time.find(actor);
        return it == actor_free_time.end() ? 0 : it->second;
    };
    auto get_link_free = [&](const Link& l) -> long long {
        auto it = link_free_time.find(l);
        return it == link_free_time.end() ? 0 : it->second;
    };

    // Ready queue: indices with remaining_deps == 0, not yet dispatched.
    // Ordered by ascending tc_id for a deterministic dispatch tie-break.
    auto cmp = [&](int a, int b) { return tcs[a].tc_id > tcs[b].tc_id; };
    std::priority_queue<int, std::vector<int>, decltype(cmp)> ready(cmp);
    for (int i = 0; i < n; ++i) {
        if (remaining_deps[i] == 0) ready.push(i);
    }

    using Event = std::pair<long long, int>;  // (finish_time, index)
    std::priority_queue<Event, std::vector<Event>, std::greater<Event>> completions;

    SimResult res;
    int dispatched = 0;

    while (!ready.empty() || !completions.empty()) {
        while (!ready.empty()) {
            int i = ready.top();
            ready.pop();
            const Transaction& tc = tcs[i];

            long long start;
            long long duration;
            std::vector<Link> route;
            bool is_dram = (tc.op != 2) && touches_dram(tc, dram_port);

            if (tc.op == 2) {
                // COUNT: only the actor matters, no links.
                start    = get_actor_free(tc.actor_id);
                duration = tc.size;
            } else if (is_dram) {
                // DRAM-touching unicast/multicast: no hop term, matches
                // Plan 1's dram_cost formula exactly.
                start    = get_actor_free(tc.actor_id);
                duration = tc.size * dram_latency;
            } else {
                int dest;
                if (tc.op == 0) {
                    if (tc.dests.empty()) {
                        throw std::runtime_error("unicast tc_id " +
                                                  std::to_string(tc.tc_id) + " has no dest");
                    }
                    dest = tc.dests[0];
                } else {
                    if (tc.dests.empty()) {
                        throw std::runtime_error("multicast tc_id " +
                                                  std::to_string(tc.tc_id) + " has no dests");
                    }
                    // Farthest-only: route to whichever destination is
                    // farthest by Manhattan distance from the source.
                    dest = *std::max_element(
                        tc.dests.begin(), tc.dests.end(), [&](int a, int b) {
                            return noc.manhattan(tc.actor_id, a) < noc.manhattan(tc.actor_id, b);
                        });
                }
                route = noc.hops_single(tc.actor_id, dest);

                start = get_actor_free(tc.actor_id);
                for (const auto& l : route) start = std::max(start, get_link_free(l));

                duration = static_cast<long long>(route.size()) + tc.size * FLITS_PER_PACKET;
            }

            long long finish = start + duration;
            actor_free_time[tc.actor_id] = finish;
            for (const auto& l : route) link_free_time[l] = finish;

            if (tc.op == 2) res.count_cycles += duration;
            else if (is_dram) res.dram_cycles += duration;
            else if (tc.op == 0) res.unicast_cycles += duration;
            else res.multicast_cycles += duration;

            res.total_cycles = std::max(res.total_cycles, finish);

            completions.push({finish, i});
            ++dispatched;
        }

        if (!completions.empty()) {
            auto [finish_time, i] = completions.top();
            (void)finish_time;
            completions.pop();
            for (int dep_idx : dependents[i]) {
                if (--remaining_deps[dep_idx] == 0) {
                    ready.push(dep_idx);
                }
            }
        }
    }

    if (dispatched != n) {
        throw std::runtime_error("unresolved dependency cycle -- only " +
                                  std::to_string(dispatched) + " of " + std::to_string(n) +
                                  " transactions completed");
    }

    return res;
}
