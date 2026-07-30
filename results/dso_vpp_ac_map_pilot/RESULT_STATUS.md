# Stage-0 result validity sentinel

## Defective run: invalid for scientific use

- Status: `INVALID_FOR_SCIENTIFIC_USE`
- Defect timestamp/archive key: `20260730T145810Z`
- Preserved archive: `_archived_stage0_missing_reference_pv_20260730T145810Z/`
- Reason: the original Stage-0 physical-input assembly omitted the fixed reference-PV injection `H × f_t` at bus 13. Solver convergence and replay agreement therefore validated the wrong physical input.
- Affected active filenames: the unsuffixed `stage0_benchmark_points.csv`, `timing_benchmark.csv`, `stage0_data_audit.csv`, `stage0_pv_presence_check.csv`, `stage0_audit_report.md`, and `stage0_audit_bundle.zip`.

## Corrected repair evidence: regression use only

- Status: `VALID_FOR_REPAIR_REGRESSION_ONLY`
- Base commit before repair: `13f22d0e48e950ccf8a127bb3c97f891c2512e19`
- Repair report: `stage0_repair_report.md`
- Corrected point evidence: `stage0_benchmark_points_corrected.csv`
- Corrected timing evidence: `timing_benchmark_corrected.csv`
- Corrected input audit: `stage0_data_audit_corrected.csv`
- Corrected PV-presence evidence: `stage0_pv_presence_check_corrected.csv`
- Before/after comparison: `stage0_before_after_comparison.csv`
- Repair checksums: `SHA256SUMS_REPAIR.txt`
- Repair bundle: `stage0_repair_bundle.zip`

These corrected files reproduce the archived 1,000-point plan with the repaired physical input and support regression/audit conclusions only. They are not a continuous feasible map, hosting-capacity result, production Stage-1 output, or approval to launch Stage 1.
