# Locked Decision Rules

1. Preserve `MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE` permanently.
2. No AC result from calibration may be relabelled as evidence about the independent holdout.
3. Enrich the corrected 41-edge low-sample set with the 130 locked fractions before calibration.
4. Construct each retreat with the original inward normal: `n_in · (x-a) >= d_e`. Projection is forbidden, including all 65 mixed-sign normals.
5. Determine `d_i*` and `d_e*` only from future AC calls. Signed interpolation and LinDistFlow scaling may order anchors but are never authoritative.
6. `d_i*` is the smallest tested retreat on the locked 0.25 kW grid that meets both design limits (`Vmin >= 0.90015000`, `Vmax <= 1.04985000`).
7. Initial `d_e*` is the maximum interior-point `d_i*` on that edge. Rebuild all cells from tightened original halfspaces, then re-evaluate all 24004 calibration memberships.
8. Any local PASS→FAIL transition with increasing retreat at the locked 0.25 kW stencil is `REENTRY_BLOCKER`; this diagnostic is not a global monotonicity proof.
9. Reject `d_e* >= cap_e`, any nonconvex/degenerate combined cell, budget exhaustion, unresolved nonconvergence, or failed original-limit calibration. Geometry cap is a bound, not the primary falsification path.
10. Report original-limit and headroom assessments separately. A headroom failure must not erase an original-limit pass, and an original-limit failure always blocks repair freeze.
11. Generate H1/H2 only after repaired geometry freeze. Calibration/holdout coordinate overlap must be exactly zero at componentwise `1e-08 kW` tolerance.
12. Holdout points are never used to modify retreat. Any holdout original-limit failure falsifies the repaired candidate; any holdout headroom-only failure rejects only the headroom claim unless preregistered otherwise.
13. Safe Box extraction is forbidden until final repaired coupled DOE freeze.
