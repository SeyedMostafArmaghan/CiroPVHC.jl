# Substantive AC interior validation report

## OBSERVED AC RESULTS

All 128 configuration controls matched. The frozen substantive mesh completed 65494 / 65494 points: 56074 feasible, 9420 converged-infeasible, and 0 unresolved. Retained unique AC attempt rows: 65622; physical AC calls including checkpoint-recovery replay: 66122; retry attempts: 0.

Maximum voltage violation was 0.00014224810923857412 p.u. at VP_T010_000635, timestamp 2011-02-05 17:30:00, P13=3204.2235947278846 kW, P30=-729.9158723549914 kW, mechanism VMAX13, source BOUNDARY_INTER_RAY, provenance NO_CELL_MEMBERSHIP.

## PREREGISTERED DIAGNOSTIC HYPOTHESES

- H1: `SUPPORTED_BY_OBSERVED_MESH` — VMAX boundary failures=7060/10406; VMIN boundary failures=0/10636.
- H2: `SUPPORTED_BY_OBSERVED_MESH` — boundary/edge-like failure fraction=0.2853248523398455; strict-interior failure fraction=0.0.
- H3: `SUPPORTED_BY_OBSERVED_MESH` — strict-interior failures=0.
- H4: `SUPPORTED_BY_OBSERVED_MESH` — quantitative forecasts did not alter execution or decision semantics.
- H5: `SUPPORTED_BY_OBSERVED_MESH` — no physical-mechanism inference made.

## HEURISTIC FORECAST ASSESSMENT

- E1: `MIXED` — VMAX failure median violation=5.7652001633767824e-6.
- E2: `SUPPORTED_BY_OBSERVED_MESH` — total converged-infeasible=9420.
- E3: `SUPPORTED_BY_OBSERVED_MESH` — VMAX failures=9420; VMIN failures=0.

## CAMPAIGN DECISION CLASSIFICATION

`MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`

## INTERPRETATION LIMITS

This is a finite preregistered falsification mesh, not a continuous AC proof, global certification, or proof of AC safety. Guard and fallback results are descriptive only; the fallback is not AC-certified or promoted. VMAX concentration alone does not establish a physical loss mechanism. No geometry repair, adaptive probing, or optimization was performed.

Runtime: setup=10.7999451 s, controls=0.1695415999999999 s, substantive=7.707099700000157 s, checkpoint/I/O=193.0670898 s, postprocessing=7.1946395 s, total=393.033326 s.
