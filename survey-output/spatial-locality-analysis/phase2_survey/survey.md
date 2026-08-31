# Survey: methodologies for spatial locality analysis of memory address traces

Date: 2026-08-31 | Papers in DB: 79

## Themes

### A. Stack/reuse distance: the exact single-pass measurement (18 papers)
- [Evaluation techniques for storage hierarchies, 1970](https://doi.org/10.1147/sj.92.0078) - IBM Systems Journal
- [LRU Stack Processing, 1975](https://doi.org/10.1147/rd.194.0353) - IBM Journal of Research and Development
- [Stack processing techniques in delayed-staging storage hierarchies, 1983](https://doi.org/10.1145/182.358467) - Communications of the ACM
- [Predicting whole-program locality through reuse distance analysis, 2003](https://doi.org/10.1145/780822.781159) - ACM SIGPLAN Notices
- [Miss Rate Prediction Across Program Inputs and Cache Configurations, 2007](https://doi.org/10.1109/tc.2007.50) - IEEE Transactions on Computers
- [Accelerating multicore reuse distance analysis with sampling and parallelizati, 2010](https://doi.org/10.1145/1854273.1854286) - Proceedings of the 19th international confer
- [Is Reuse Distance Applicable to Data Locality Analysis on Chip Multiprocessors, 2010](https://doi.org/10.1007/978-3-642-11970-5_15) - Lecture Notes in Computer Science
- [Linear-time Modeling of Program Working Set in Shared Cache, 2011](https://doi.org/10.1109/pact.2011.66) - 2011 International Conference on Parallel Ar
- [A higher order theory of locality, 2012](https://doi.org/10.1145/2247684.2247697) - Proceedings of the 2012 ACM SIGPLAN Workshop
- [Locality Principle Revisited: A Probability-Based Quantitative Approach, 2012](https://doi.org/10.1109/ipdps.2012.93) - 2012 IEEE 26th International Parallel and Di
- [PARDA: A Fast Parallel Reuse Distance Analysis Algorithm, 2012](https://doi.org/10.1109/ipdps.2012.117) - 2012 IEEE 26th International Parallel and Di
- [FractalMRC: Online Cache Miss Rate Curve Prediction on Commodity Systems, 2012](https://doi.org/10.1109/ipdps.2012.121) - 2012 IEEE 26th International Parallel and Di
- [Beyond reuse distance analysis, 2013](https://doi.org/10.1145/2555289.2555309) - ACM Transactions on Architecture and Code Op
- [A modeling framework for reuse distance-based estimation of cache performance, 2015](https://doi.org/10.1109/ispass.2015.7095785) - 2015 IEEE International Symposium on Perform
- [Analytical Miss Rate Calculation of L2 Cache from the RD Profile of L1 Cache, 2018](https://doi.org/10.1109/tc.2017.2723878) - IEEE Transactions on Computers
- [Detecting the phase behavior on cache performance using the reuse distance vec, 2018](https://doi.org/10.1016/j.sysarc.2018.09.001) - Journal of Systems Architecture
- [Accurate Probabilistic Miss Ratio Curve Approximation for Adaptive Cache Alloc, 2022](https://doi.org/10.23919/date54114.2022.9774516) - 2022 Design, Automation &amp; Test in Europe
- [TTLs Matter: Efficient Cache Sizing with TTL-Aware Miss Ratio Curves and Worki, 2024](https://doi.org/10.1145/3627703.3650066) - Proceedings of the Nineteenth European Confe

### B. Sampling and approximation (3 papers)
- [StatCache: A probabilistic approach to efficient and accurate data locality an, 2004](https://doi.org/10.1109/ispass.2004.1291352) - IEEE International Symposium on - ISPASS Per
- [StatStack: Efficient modeling of LRU caches, 2010](https://doi.org/10.1109/ispass.2010.5452069) - 2010 IEEE International Symposium on Perform
- [Pinpointing data locality bottlenecks with low overhead, 2013](https://doi.org/10.1109/ispass.2013.6557169) - 2013 IEEE International Symposium on Perform

### C. Line size and the classical cache design sweeps (4 papers)
- [Cache Memories, 1982](https://doi.org/10.1145/356887.356892) - ACM Computing Surveys
- [Line (block) size choice for CPU cache memories, 1987](https://doi.org/10.1016/0141-9331(87)90424-8) - Microprocessors and Microsystems
- [Evaluating associativity in CPU caches, 1989](https://doi.org/10.1109/12.40842) - IEEE Transactions on Computers
- [A new cache architecture based on temporal and spatial locality, 2000](https://doi.org/10.1016/s1383-7621(00)00035-7) - Journal of Systems Architecture

### D. Spatial footprint / line utilization / dead blocks (9 papers)
- [Exploiting spatial locality in data caches using spatial footprints, 1998](https://doi.org/10.1109/isca.1998.694794) - Proceedings. 25th Annual International Sympo
- [Increasing the Cache Efficiency by Eliminating Noise, 2006](https://doi.org/10.1109/hpca.2006.1598121) - The Twelfth International Symposium on High-
- [Line Distillation: Increasing Cache Capacity by Filtering Unused Words in Cach, 2007](https://doi.org/10.1109/hpca.2007.346202) - 2007 IEEE 13th International Symposium on Hi
- [Cache bursts: A new approach for eliminating dead blocks and increasing cache , 2008](https://doi.org/10.1109/micro.2008.4771793) - 2008 41st IEEE/ACM International Symposium o
- [Sampling Dead Block Prediction for Last-Level Caches, 2010](https://doi.org/10.1109/micro.2010.24) - 2010 43rd Annual IEEE/ACM International Symp
- [Decoupled compressed cache, 2013](https://doi.org/10.1145/2540708.2540715) - Proceedings of the 46th Annual IEEE/ACM Inte
- [Decoupled Compressed Cache: Exploiting Spatial Locality for Energy Optimizatio, 2014](https://doi.org/10.1109/mm.2014.42) - IEEE Micro
- [Dirty page prediction by machine learning methods based on temporal and spatia, 2023](https://doi.org/10.1109/cscwd57460.2023.10152768) - 2023 26th International Conference on Comput
- [Rethinking Dead Block Prediction for Intermittent Computing, 2025](https://doi.org/10.1109/hpca61900.2025.00061) - 2025 IEEE International Symposium on High Pe

### E. Locality metrics and scores (7 papers)
- [A Characterization of Temporal Locality and Its Portability across Memory Hier, 2001](https://doi.org/10.1007/3-540-48224-5_11) - Lecture Notes in Computer Science
- [Evaluating synthetic trace models using locality surfaces, 2002](https://doi.org/10.1109/wwc.2002.1226491) - 2002 IEEE International Workshop on Workload
- [Quantifying locality effect in data access delay: memory logP, 2003](https://doi.org/10.1109/ipdps.2003.1213137) - Proceedings International Parallel and Distr
- [Quantifying Locality In The Memory Access Patterns of HPC Applications, 2005](https://doi.org/10.1109/sc.2005.59) - ACM/IEEE SC 2005 Conference (SC'05)
- [A component model of spatial locality, 2009](https://doi.org/10.1145/1542431.1542446) - Proceedings of the 2009 international sympos
- [Cache Utilization as a Locality Metric - A Case Study on the Mantevo Suite, 2016](https://doi.org/10.1109/csci.2016.0110) - 2016 International Conference on Computation
- [Data-driven spatial locality, 2018](https://doi.org/10.1145/3240302.3240417) - Proceedings of the International Symposium o

### F. Layout, affinity and index/conflict engineering (12 papers)
- [A data locality optimizing algorithm, 1991](https://doi.org/10.1145/113445.113449) - n/a
- [A case for two-way skewed-associative caches, 1993](https://doi.org/10.1145/165123.165152) - Proceedings of the 20th annual international
- [Compiler optimizations for improving data locality, 1994](https://doi.org/10.1145/195473.195557) - n/a
- [Improving data locality with loop transformations, 1996](https://doi.org/10.1145/233561.233564) - ACM Transactions on Programming Languages an
- [Cache miss equations, 1997](https://doi.org/10.1145/263580.263657) - Proceedings of the 11th international confer
- [Code placement techniques for cache miss rate reduction, 1997](https://doi.org/10.1145/268424.268469) - ACM Transactions on Design Automation of Ele
- [Cache-conscious structure layout, 1999](https://doi.org/10.1145/301631.301633) - ACM SIGPLAN Notices
- [An algorithm for optimally exploiting spatial and temporal locality in upper m, 1999](https://doi.org/10.1109/12.752656) - IEEE Transactions on Computers
- [Automatic memory layout transformations to optimize spatial locality in parame, 2000](https://doi.org/10.1145/346023.346031) - ACM SIGARCH Computer Architecture News
- [Static locality analysis for cache management, 2002](https://doi.org/10.1109/pact.1997.644022) - Proceedings 1997 International Conference on
- [Array regrouping and structure splitting using whole-program reference affinit, 2004](https://doi.org/10.1145/996893.996872) - ACM SIGPLAN Notices
- [Cache conscious data layout organization for conflict miss reduction in embedd, 2005](https://doi.org/10.1109/tc.2005.2) - IEEE Transactions on Computers

### G. Runtime detection and prefetch-adjacent (7 papers)
- [Run-time spatial locality detection and optimization, 1997](https://doi.org/10.1109/micro.1997.645797) - Proceedings of 30th Annual International Sym
- [Achieving Non-Inclusive Cache Performance with Inclusive Caches: Temporal Loca, 2010](https://doi.org/10.1109/micro.2010.52) - 2010 43rd Annual IEEE/ACM International Symp
- [Spatial Locality-Aware Cache Partitioning for Effective Cache Sharing, 2015](https://doi.org/10.1109/icpp.2015.24) - 2015 44th International Conference on Parall
- [Reuse Distance-Based Probabilistic Cache Replacement, 2016](https://doi.org/10.1145/2818374) - ACM Transactions on Architecture and Code Op
- [A Spatial and Temporal Locality-Aware Adaptive Cache Design With Network Optim, 2017](https://doi.org/10.1109/tvlsi.2017.2712366) - IEEE Transactions on Very Large Scale Integr
- [Reuse Distance-based Victim Cache for Effective Utilisation of Hybrid Main Mem, 2020](https://doi.org/10.1145/3380732) - ACM Transactions on Design Automation of Ele
- [HBPB, applying reuse distance to improve cache efficiency proactively, 2024](https://doi.org/10.1016/j.jpdc.2024.104919) - Journal of Parallel and Distributed Computin

### H. Applied characterization (GPU, graph, DNN, sparse) (14 papers)
- [Cache Miss Analysis for GPU Programs Based on Stack Distance Profile, 2011](https://doi.org/10.1109/icdcs.2011.16) - 2011 31st International Conference on Distri
- [Reducing the overall cache miss rate using different cache sizes for Heterogen, 2012](https://doi.org/10.1109/reconfig.2012.6416783) - 2012 International Conference on Reconfigura
- [A detailed GPU cache model based on reuse distance theory, 2014](https://doi.org/10.1109/hpca.2014.6835955) - 2014 IEEE 20th International Symposium on Hi
- [Revealing Critical Loads and Hidden Data Locality in GPGPU Applications, 2015](https://doi.org/10.1109/iiswc.2015.23) - 2015 IEEE International Symposium on Workloa
- [Locality Exists in Graph Processing: Workload Characterization on an Ivy Bridg, 2015](https://doi.org/10.1109/iiswc.2015.12) - 2015 IEEE International Symposium on Workloa
- [A reuse distance based performance analysis on GPU L1 data cache, 2016](https://doi.org/10.1109/pccc.2016.7820638) - 2016 IEEE 35th International Performance Com
- [Efficient Cache Performance Modeling in GPUs Using Reuse Distance Analysis, 2018](https://doi.org/10.1145/3291051) - ACM Transactions on Architecture and Code Op
- [GPUs Cache Performance Estimation using Reuse Distance Analysis, 2019](https://doi.org/10.1109/ipccc47392.2019.8958760) - 2019 IEEE 38th International Performance Com
- [Analyzing data locality in GPU kernels using memory footprint analysis, 2019](https://doi.org/10.1016/j.simpat.2018.12.003) - Simulation Modelling Practice and Theory
- [Locality Analysis of Graph Reordering Algorithms, 2021](https://doi.org/10.1109/iiswc53511.2021.00020) - 2021 IEEE International Symposium on Workloa
- [Data Locality Aware Computation Offloading in Near Memory Processing Architect, 2023](https://doi.org/10.1109/hipc58850.2023.00019) - 2023 IEEE 30th International Conference on H
- [Characterization of Memory Access in Deep Learning and Its Implications in Mem, 2023](https://doi.org/10.32604/cmc.2023.039236) - Computers, Materials &amp; Continua
- [SLAWS: Spatial Locality Analysis and Workload Orchestration for Sparse Matrix , 2026](https://doi.org/10.1145/3779212.3790222) - Proceedings of the 31st ACM International Co
- [Sequential Memory Access Characterization and Schedule Optimization for Deep N, 2026](https://doi.org/10.2139/ssrn.6835478) - n/a

### Unclustered (5)
- [The working set model for program behavior, 1967](https://doi.org/10.1145/800001.811670)
- [False sharing and spatial locality in multiprocessor caches, 1994](https://doi.org/10.1109/12.286299)
- [Architecting On-Chip DRAM Cache for Simultaneous Miss Rate and Latency Reducti, 2016](https://doi.org/10.1109/tcad.2015.2488488)
- [Identifying optimal multicore cache hierarchies for loop-based parallel progra, 2012](https://doi.org/10.1145/2247684.2247687)
- [Identifying Power-Efficient Multicore Cache Hierarchies via Reuse Distance Ana, 2016](https://doi.org/10.1145/2851503)

## Year distribution (by decade)

- 1960s: 1
- 1970s: 2
- 1980s: 4
- 1990s: 11
- 2000s: 16
- 2010s: 34
- 2020s: 11

## Venue / family distribution

- Computer architecture + performance analysis: the whole corpus. No AI/ML or Nature-family work qualified.
- Peer-reviewed: 79 of 79. No preprints survived screening, which is itself informative: this methodology literature is conference/journal-published and pre-arXiv-era for its roots.

## Initial observations

1. The measurement methodology was essentially finished by 2013. Everything after is application or actuation.
2. Temporal locality has an exact, capacity-complete measurement (stack distance). Spatial locality has no equivalent: it is measured indirectly, through a chosen line size, or through a score that discards the capacity axis.
3. The one theory that treats spatial locality as a first-class dimension rather than a side effect is the footprint/component-model line out of Rochester.
4. Set-index and conflict analysis is a separate literature from locality analysis and the two rarely cite each other, which matters directly for a study whose measured hit rate was destroyed by index-bit selection.
