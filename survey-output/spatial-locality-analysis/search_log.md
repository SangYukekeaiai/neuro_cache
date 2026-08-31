# Search log

Topic: **methodologies for measuring and characterizing spatial locality in memory
address traces**, scoped for use on an SNN weight-cache trace study (`neuro_cache`,
`src/wcache`). Date run: 2026-08-31.

## Sources and their behaviour

| Source | Status | Note |
|---|---|---|
| Crossref | working | primary source; ACM/IEEE proceedings resolve cleanly with DOIs |
| OpenAlex | working | broad recall, but full-text matching drags in heavy off-topic noise; title screening was mandatory |
| arXiv | working | thin for this topic; almost nothing recent |
| Semantic Scholar | **unavailable** | rate-limited on every attempt (no API key supplied). Citation counts in this corpus therefore come from Crossref/OpenAlex only |

Family routing (per `venues.md`): computer architecture, plus the performance-analysis
venues (ISPASS, IISWC, MEMSYS, SC, PACT) where locality *measurement* actually publishes.
Not an AI/ML or Nature topic; those recipes were not run.

## Phase 1 queries (frontier, 2022-2026)

| Source | Query | Hits |
|---|---|---|
| Crossref | spatial locality memory access pattern characterization | 40 |
| Crossref | reuse distance analysis cache | 40 |
| Crossref | cache locality metric workload characterization | 40 |
| Crossref | memory access pattern characterization deep learning accelerator | 39 |
| Crossref | locality analysis sparse workload memory | 40 |
| Crossref | data locality profiling tool performance | 36 |
| OpenAlex | spatial locality memory access characterization (2023-2026) | 50 |
| OpenAlex | reuse distance model cache miss rate (2023-2026) | 50 |
| OpenAlex | memory access trace locality analysis (2023-2026) | 50 |
| arXiv | spatial locality memory access analysis | 30 |
| arXiv | reuse distance profiling | 30 |
| Semantic Scholar | 5 queries attempted | 0 (rate limited) |

## Phase 2 queries (full range, incl. roots)

| Source | Query | Hits |
|---|---|---|
| Crossref | cache line size miss ratio evaluation | 40 |
| Crossref | spatial footprint prediction cache | 40 |
| Crossref | stack distance storage hierarchy evaluation techniques | 39 |
| Crossref | reference affinity data layout structure splitting | 40 |
| Crossref | working set model program behavior | 39 |
| Crossref | locality surface workload characterization | 40 |
| Crossref | cache miss equations compiler locality analysis | 40 |
| Crossref | sector cache sub-block spatial locality | 40 |
| Crossref | stride prefetching reference prediction table | 38 |
| Crossref | cache index hashing conflict miss reduction | 40 |
| Crossref | sampling reuse distance approximation StatStack | 38 |
| Crossref | footprint theory higher order locality | 40 |
| Crossref | cache miss rate prediction reuse distance associativity | 40 |
| Crossref | dead block prediction cache line utilization | 40 |
| Crossref | quantifying spatial temporal locality metric | 40 |
| OpenAlex | 4 broad queries, 1970-2026, min 15 citations | 240 |
| Crossref | 20 targeted title lookups (backward snowballing to the seminal roots) | 120 |

## Screening cascade (PRISMA-style)

| Stage | Count |
|---|---|
| Identified (all sources, all queries) | 1399 |
| After de-duplication (title + DOI + arXiv id) | 1123 |
| Title-screened as on-topic | 208 |
| Included in `paper_db.jsonl` (24 seminal roots force-included, remainder ranked by cites-per-year) | 79 |
| Deep-read in full (Phase 3) | see `phase3_deep_dive/selection.md` |

## Known year-field corrections

Crossref returns an indexing/reprint year for several older proceedings. Corrected by DOI
before the DB was built: `micro.1997.645797` to 1997, `isca.1998.694794` to 1998,
`isca.1993.698558` to 1993, `ipdps.2003.1213137` to 2003, `2555289.2555309` to 2013,
`0141-9331(87)90424-8` to 1987.
