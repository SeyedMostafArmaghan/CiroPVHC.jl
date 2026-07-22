# Methodology decisions

## S1-B central voltage-constrained PV hosting capacity

The following decisions are locked for the central S1-B run.

- The fixed candidate buses are 13, 20, 24, and 30.
- One nonnegative installed-capacity vector, `C_PV = [C13, C20, C24, C30]`, is shared by every modeled day and interval. Capacity cannot change between days or intervals.
- The initial optimization contains all 48 half-hour intervals from each of the 32 unique days recorded by the pre-S1 audit, for 1,536 simultaneous operating constraints. Days are not optimized separately and their individual hosting capacities are not combined afterward.
- No site-cap constraint is present. In particular, no large finite surrogate replaces a missing site cap.
- No gamma cap is used in S1-B.
- Curtailment is absent: at every interval and candidate bus, PV injection is installed capacity multiplied by the recorded availability profile.
- Export is allowed and no no-export constraint is present.
- No thermal, ampacity, apparent-power (`Smax`), transformer, or synthetic 4,000 kVA constraint is present. The source network has missing branch ratings, represented by zero, and S1-B does not replace them.
- The fixed root voltage is `V0 = 1.00 p.u.`.
- The voltage-magnitude band is `0.90 <= |V| <= 1.05 p.u.`. Because the model variable is squared voltage, its exact bounds are `0.90^2 = 0.81` and `1.05^2 = 1.1025`.
- The sole S1-B optimization objective is `maximize C13 + C20 + C24 + C30`.
- Because no documented substation/transformer rating exists, the central result is labeled **voltage-only hosting capacity with unconstrained upstream exchange.** It is not complete technical or thermal hosting capacity.
- The archived value 2,766.97 kW is not an S1-B result; it belongs to an earlier policy-limited path.
- The one-day foundation benchmark is validated by an independent phasor-domain radial AC replay that does not reuse optimization constraints or their residual helper. Future full-period validation, if separately authorized, must apply the common capacity vector, zero curtailment, and allowed export to every interval. It cannot perform thermal validation while branch ampacity and transformer-rating data remain unavailable.
- No 32-day or three-year optimization or constraint-generation run is authorized until the nonconvex multi-interval design is separately reviewed.
- No second-stage loss or voltage-quality objective, S1-C policy, gamma-cap sensitivity, no-export sensitivity, curtailment sensitivity, or 4 MVA sensitivity is part of S1-B.

## S1-B formulation decision and risk log (2026-07-21)

- The S1-B SOCP relaxation and every tested active-loss-penalty variant failed to provide AC-feasible hosting capacity on the benchmark day. The tested points remained materially inexact and failed independent AC replay.
- SOCP may remain useful for screening or explicitly non-certified bounds. Under the current formulation it is not the source of achievable hosting capacity.
- S1-B therefore proceeds, subject to a separate scaling review, with the **nonconvex branch-flow AC model for a balanced radial feeder**. It is not a full polar- or rectangular-voltage AC-OPF.
- Ipopt multi-start gives local-solution evidence only. Neither the approximately 10.680 MW result nor the agreement of 13 starts is a global-optimality certificate or mathematical upper bound.
- SOC-gap validation is replaced for the central nonconvex formulation by independent AC replay. Validation remains mandatory; solver termination alone is insufficient.
- No defensible documented substation or transformer MVA rating was found. `baseMVA = 10` is only a per-unit normalization, and the project’s 4,000 kVA values are explicitly synthetic branch assumptions from other study paths. No central transformer constraint is added.
- A future transformer sensitivity, if authorized, must use clearly synthetic bidirectional apparent-power limits, declared in advance and never described as equipment data:

  \[
  P_{sub,t}^2 + Q_{sub,t}^2 \le S_{tr}^2.
  \]

- **Open risk #2 — robust extension:** the planned budgeted-robust extension was built around SOCP and may become computationally or methodologically infeasible after moving to a nonconvex multi-scenario AC formulation. This risk must be prototyped on a small case before claiming that the original R0–R3 architecture remains viable.

## S1-B exact-AC constraint-generation readiness (2026-07-22)

- The independently confirmed one-day foundation remains a best stable AC-feasible **local** solution of 10.680484846 MW; all 13 starts passed independent replay. It is neither a global optimum nor a proven upper bound.
- The production architecture uses a nonconvex branch-flow AC model for a balanced radial feeder, deterministic multi-start, and independent complex backward-forward-sweep replay. The common installed-capacity vector is shared by all active operating points.
- The central label remains **voltage-only hosting capacity with unconstrained upstream exchange.** No defensible documented transformer/substation rating was found and no central `S_tr` limit is activated.
- Synthetic bidirectional `S_tr` limits remain deferred to separately authorized and explicitly labeled sensitivity studies; they must not be presented as equipment data.
- Detailed full-period replay/start tables and resumable checkpoints are local ignored artifacts; compact summaries, configurations, reports, code, and tests are committed under `docs/S1B_OUTPUT_RETENTION_POLICY.md`.
- Ipopt remains a local nonlinear solver. Adding operating points can produce non-monotone accepted objectives across iterations, so every active set retains its own best independently replayed local result and no monotonic/global claim is made.
- **Open robust-optimization risk:** scaling a budgeted-robust formulation over this nonconvex AC model may be computationally or methodologically infeasible. A small prototype and an explicit treatment of local-solution uncertainty are required before retaining any earlier R0–R3 architecture claim.
