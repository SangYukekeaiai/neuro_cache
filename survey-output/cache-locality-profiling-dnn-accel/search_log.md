# Search Log — Cache-vs-Scratchpad & Locality/Reuse Profiling for DNN/SNN Accelerators

Date run: 2026-07-18. Families: computer architecture + ML/systems (ISPASS/IISWC/MLSys, embedded/compiler).
Nature family NOT queried (topic does not touch it; see report Limitations).
Scripts: paper-survey `search_{crossref,openalex,semantic_scholar,arxiv}.py`.

## Phase 1 — Frontier queries (recent window)
| Source | Query | Year range | Hits |
|--------|-------|-----------|------|
| Crossref | cache versus scratchpad DNN accelerator memory | any | 39 |
| OpenAlex | reuse distance locality DNN accelerator dataflow | 2023-2026 | 0* |
| S2 | weight reuse locality tensor accelerator mapping | 2023-2026 | 50 (retry) |
| S2 | cache replacement policy accelerator working set | 2023-2026 | 40 |
| arXiv | reuse distance working set DNN accelerator cache locality | - | 40 |
| OpenAlex | trace driven cache simulation neural network accelerator | 2022-2026 | 40 |
| Crossref | data reuse analysis tiling loop nest accelerator | any | 40 |
| S2 | spiking neural network accelerator memory hierarchy on-chip | 2023-2026 | 40 |
| arXiv | cache versus scratchpad managed memory deep learning accelerator | - | 30 |
| OpenAlex | reuse distance analysis deep learning accelerator on-chip memory | 2022-2026 | 50 |
| OpenAlex | cache scratchpad software managed buffer accelerator | 2021-2026 | 40 |
*OpenAlex initial 0 result re-issued with reworded query (50 hits). S2 initial 0s were transient rate-limits, re-issued.

## Phase 2 — Broadening + roots queries
| Source | Query | Year range | Hits |
|--------|-------|-----------|------|
| Crossref | stack distance reuse distance cache locality model | any | 40 |
| Crossref | Timeloop DNN accelerator evaluation dataflow | any | 23 |
| Crossref | scratchpad memory versus cache embedded on-chip design | any | 30 |
| OpenAlex | reuse distance working set characterization program locality | 1998-2026 | 45 |
| OpenAlex | DNN accelerator dataflow data reuse energy scheduling mapping | 2016-2026 | 50 |
| OpenAlex | Belady optimal replacement cache learned prediction | 2006-2026 | 40 |
| S2 | reuse distance analysis cache miss rate prediction methodology | 2001-2026 | 40 |
| S2 | loop tiling data locality optimization compiler | 1988-2026 | 40 |
| Crossref | CoSA scheduling constrained optimization spatial accelerator | any | 15 |
| Crossref | spiking neural network accelerator on-chip weight memory hardware | any | 29 |
| OpenAlex | polyhedral analytical cache reuse model tiling data movement | 2004-2026 | 33 |
| Crossref | cache prefetching neural network accelerator DRAM traffic | any | 25 |

## Phase 2 — Backward snowball (seminal roots, added after the relevance filter)
Mattson 1970 (stack distance); Ding & Zhong 2003 (reuse distance); MAESTRO MICRO 2019;
Interstellar ASPLOS 2020; Buffets ISCA 2019; ZigZag TC 2021; Eyeriss JSSC 2017;
Belady 1966; Hawkeye/Back-to-the-Future ISCA 2016; Accelergy ICCAD 2019; MAESTRO IEEE Micro 2020;
Program locality analysis using reuse distance (Zhong et al. 2009).

## PRISMA-style screening cascade
| Stage | Count |
|-------|-------|
| Identified (all Phase 1 + Phase 2 source outputs, merged) | 703 |
| After de-duplication | 627 |
| Included after relevance filter (cites-per-year, cap 72) | 72 |
| After dropping off-topic noise (4) + adding 12 seminal roots | 80 (the paper DB) |
| Deep-read in full (Phase 3) | 10 |

## Relation to the prior survey in this project
The sibling run `survey-output/dnn-noc-buffer-sizes/` (127 papers, buffer-SIZE focus) already
deep-read Timeloop, MAESTRO, Interstellar, Buffets, CoSA, Eyeriss, ZigZag, Marvel, SCALE-Sim,
and Data-Cache-Prefetching-via-GHB. Those are CROSS-REFERENCED here for their reuse-quantification
*method* (this survey's angle) rather than re-deep-read for buffer sizes; new deep reads target the
profiling-methodology and cache-vs-scratchpad papers that survey did not cover.