# Operating-point provenance audit

Primary classification: **ADJACENT_TIMESTAMP_HISTORICAL_TEXT_ERROR**.

The exact value `0.9282211452522351` is the canonical `2012-10-15 12:30:00` PV factor. The next row, `2012-10-15 13:00:00`, contains `0.9149568739021162`. Both Phase B and the analytical audit select the latter row by the exact naive `DateTime` key and produce byte-identical independently reconstructed load and injection vector hashes. The historical retraction therefore attached the adjacent 12:30 peak value to the 13:00 operating point; production timestamp lookup is not defective.

## Complete production paths

Phase B: `run_dso_vpp_export_side_axis_scan.jl:108-123 -> load_canonical_data:85-93 -> Stage0.load_profile:36-44 -> CiroPVHC.read_s1b_profile -> _read_s1b_profile:45-96 -> scan_interval/evaluate_axis_point:145-163 -> evaluate_fixed_injection:104-115 -> Stage0.evaluate_point:297-441 -> assemble_stage0_inputs:89-134 -> primary_power_flow:136-289`.

Analytical audit: `run_dso_vpp_ac_anchored_linear_corner_audit.jl:40-51 -> run_analytical_audit:330-405 -> AxisScan.load_canonical_data -> exact findfirst timestamp lookup:343-345 -> default_baseline_evaluator:318-328 -> AxisScan.evaluate_fixed_injection -> Stage0.evaluate_point -> assemble_stage0_inputs -> primary_power_flow`.

Both paths read `data_processed/ausgrid/ausgrid_halfhour_normalized.csv` (SHA-256 `504dfa1c4d037d7497caa330611b5bb45f9774a2b9a984443753c88cba3de500`). `_read_s1b_profile` parses `yyyy-mm-dd HH:MM:SS` into timezone-naive Julia `DateTime` values, rejects duplicates, requires sorted 30-minute spacing, and performs no sorting, filtering, shifting, resampling, reversal, or deduplication. Pilot selection filters only by the two calendar dates while preserving source order. Source preparation creates 48 naive local labels per date, stably sorts by timestamp, and normalizes timestamp-wise means by global maxima (`prepare_ausgrid_profiles.py:106-159,277-322`); no UTC conversion or explicit DST offset exists.

At each selected index, `assemble_stage0_inputs` multiplies both `pd_kw` and `qd_kvar` by the same load multiplier, computes reference PV as `850 * pv_factor` at bus 13, adds active VPP commands at buses 13 and 30, fixes both reactive commands to zero, and divides net demand by the 10,000-kW base. Phase-B boundary commands are one-axis-at-a-time; the analytical corner is linear algebra and is not passed as the audit baseline AC command.

## Independent checks

The verifier parses the raw canonical CSV and `data_raw/case33bw.m` without calling the production profile, assembly, or coefficient constructors. `case33bw.m` SHA-256 is `60c5d6312a89607e76c86cb62268b548f37d81f1f037c1ff53aca1a8ecaf83c1`. The canonical base is 10 MVA at 12.66 kV. Buses 14-18 total 390 kW and 170 kvar. The baseline squared-voltage separation `v13^2-v14^2` is 0.00064726292998096291, matching the independently determined bus-14 corner margin up to the active equality residual.

P/Q scaling: **P_AND_Q_SCALED_IDENTICALLY**. Canonical P/Q load hashes are `005b502eaea71a65dff980d9b11fc59249111e9efdcc3941e3ab8838881763e6` and `20091698e5459f3d490985cd7279e052f022c7d7e95407053e1565c18ba7dd62`; signed generation-minus-load injection hashes are `ad06151fb3e8b26036af367f3166a349de7d7625cc059ca350badbc7f3f821da` and `31f57721572d62106cabfb82883e4c7d437d502a38ae3a20820a579616e55b77`.

Nearest inactive bus is 14 with margin 0.00064726292998096985. Active/inactive separation is 0.00064726292998096291, defined as the nearest inactive positive margin minus the maximum absolute active-set equality residual. Raw `Delta-v13` and `Delta-v30` are 0.057251473013667287 and 0.10486587407145054.

## Scientific result

The aligned provenance retains `g13=-0.0599480870632274`, `g30=-0.03560321938801625`, squared-voltage boundary residuals 0.0036509859099156383 and 0.0038713969145693916, and `theta_star=76.03090274387165 degrees` as internally valid mixed AC/linear quantities.

In `P13 >= 0, P30 >= 0`, the AC-anchored linear feasible set is exactly the quadrilateral `O=(0,0)`, `A=(640.52368371395187,0)`, `C=(156.89470053621986,1610.2756675516089)`, `B=(0,1677.6571993857481)`. The proof basis is the unique bus-13 axis binding, unique bus-30 axis binding, complete all-bus corner feasibility, convexity of every affine half-space, and intersection of the two active voltage constraints with the nonnegative axes.

`Lambda_lin=(area(quadrilateral)-area(axis-intercept triangle))/area(axis-intercept triangle)=0.20478347541993824`. Its neutral name is **additional linear feasible area beyond the axis-calibrated single-hyperplane triangle**; no DOSS equivalence is asserted.

## Portability and archive

Current Phase-B, analytical-audit, and provenance scientific manifests use repository-relative paths. Legacy `D:\CiroPVHC.jl` strings occur only in repair-only or explicitly invalid archived operational provenance and are classified as non-scientific fields excluded from reproducibility. No scientific absolute-path defect was found. The historical archive exists in the worktree, is tracked from commit `ae24e08180cf154c3c49b136d5babc5f190b6a0c`, and is referenced by committed status/report files; nothing was recreated.

No AC radial scan, LinDistFlow radial scan, intermediate-direction probe, DOE, optimization, Jacobian sensitivity, or prohibited downstream model was invoked.
