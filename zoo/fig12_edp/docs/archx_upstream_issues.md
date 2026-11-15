# archx characterization issues

Observed with archx checkout `49449c4` (read-only source).

- `src/archx/interface/csv_cmos_32nm/include/csv/noc_router.csv` reports
  `dynamic_uw=0.00008017835`, `leakage_uw=0`, bandwidth 64 bits and
  frequency 400 MHz. Using archx's CSV mW/MHz convention gives
  `2.00445875e-7 nJ` per 64-bit cycle before process scaling. At 7 nm,
  the documented scaling yields `8.8545456e-8 nJ` per 320-bit packet
  (about 0.28 aJ/bit). These magnitudes suggest a source-unit error;
  zero leakage also lacks usable characterization. Please establish the
  source report, units and normalization. Fig12 retains the estimate as
  audit metadata and uses a null router placeholder until validated.
- `src/archx/interface/cacti7/ddr4.cfg` uses `-dram_type` and `-iostate`,
  while CACTI's parser expects `-dram type` and `-io state`
  (`interface/cacti7/include/cacti7/io.cc:704,737`), so the configured
  keys can never match and the setting is silently ignored: CACTI falls
  back to the parser default, observed as DDR3 in the reports. Fig12
  corrects its run-local config
  copies to `-dram type "DDR4"` and `-io state "READ"` / `"IDLE"`, and
  rejects a report whose `io_type` is not DDR4. Please correct the
  upstream template and validate the effective interface in the wrapper.

Evidence: `energy/shared_stub/ddr4_READ.rpt`, `ddr4_IDLE.rpt`, their
run-local configs, and `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/shared_harvest.py`. No archx source was edited.
