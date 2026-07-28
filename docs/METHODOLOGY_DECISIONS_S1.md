# S1 methodology and decision record

This record closes S1 under the model and evidence available on 2026-07-28. It
separates measured facts, modeling assumptions, empirical observations, and
limitations. The conclusions are scoped to this study; they are not global
optimality or universal network-design claims.

## Locked common assumptions

- The voltage-magnitude band is 0.90–1.05 p.u. The lower bound is supported by
  the zero-PV annual baseline, whose minimum was 0.913090 p.u. at bus 18 and
  which contained 336 intervals below 0.95 p.u.
- The strict no-export optimization floor is exactly 0.0 kW. The 0.001 kW
  tolerance is used only in replay and audit paths.
- The candidate buses are 13, 20, 24, and 30. They form a screening shortlist,
  not an optimal siting set.
- The temporal model has 52,608 half-hour intervals across the three
  Ausgrid-derived years, with `dt = 0.5 h`.
- PV operates at unity power factor in S1-C.
- No validated transformer or branch thermal ratings are imposed. The modeled
  voltage constraints remain active feasibility requirements.
- Ipopt multistart results provide local-solution evidence, not a certificate
  of global optimality.
- Full-period validation is a separate full-period replay using the same
  validated AC replay engine. It is not an independent AC implementation.

## Decision S1-1 — Voltage and upstream exchange

### Facts

- In the export-allowed AC study, the best stable AC-feasible solution was
  approximately 10.680484846 MW under the modeled voltage constraints and
  unconstrained upstream exchange.
- No defensible transformer or branch thermal ratings were available.
- In the strict no-export benchmark, the approximately 644.0813 kW
  zero-curtailment benchmark was dominated by the PCC active-power balance;
  voltage was not capacity-limiting.

### Decision and limitation

The export-allowed value is a **voltage-only result with unconstrained upstream
exchange**, not a complete thermal hosting-capacity result. The available
record does not justify saying that voltage was necessarily the active limiting
constraint; that statement would require archived active-constraint evidence.

## Decision S1-2 — Siting materiality

### Scope and assumptions

This conclusion applies only to the 11 pre-specified screened configurations:
four single-bus configurations, six two-bus equal-share configurations, and one
four-bus equal-share configuration. It assumes:

- strict no-export;
- equal PV sharing within every multi-bus configuration;
- unity-power-factor PV operation;
- the current modeled voltage constraints;
- no validated transformer or branch thermal ratings;
- the current three-year Ausgrid-derived profiles; and
- candidate buses 13, 20, 24, and 30.

It does not cover arbitrary unequal allocations or global siting optimization.

### Measured facts

All 11 configurations satisfy

`r_i(810 kW) < 1% < r_i(850 kW)`.

All accepted 810 kW rows contain 52,608 classified intervals, no solver or
replay failures, and 2012 as the limiting year. The sampled annual-curtailment
response increases at H0, 810, 850, 975, and 1075 kW for every screened
configuration.

### Formal conditional result

Assuming annual curtailment is monotone over the crossing interval,

`HC_i,1% ∈ (810, 850) kW`.

The common bracket therefore gives the set-level relative-spread bound

`40 / 810 × 100% = 4.938271605%`.

This monotonicity-based bracket bound is the formal decision basis. Continuous
monotonicity is empirically supported at the sampled capacities but has not
been mathematically proved.

### Descriptive interpolation

Configuration-specific linear interpolation between the measured 810 and
850 kW points gives:

- minimum: approximately 833.4346 kW at `13+20+24+30`;
- maximum: approximately 847.1595 kW at `13`;
- mean: approximately 838.2402 kW; and
- relative spread: approximately 1.6374%.

These interpolated values are descriptive estimates, not exact threshold
solutions. They supersede the earlier broad H0-to-850 segment estimates for
description, but they do not remove the unresolved lack of a mathematical
continuous-monotonicity proof or convert interpolation into an exact 1%
annual-curtailment hosting-capacity calculation.

### Empirical pattern and interpretation

Within this screened set, every single-bus configuration ranks above every
equal-share multi-bus configuration, and the four-bus equal-share
configuration ranks lowest. Higher losses under strict no-export are a
physically plausible interpretation of that pattern, not a universal theorem.

### Approved conclusion

> Under strict no-export, unity-power-factor PV operation, and the modeled
> voltage constraints without validated thermal ratings, siting had a
> non-material effect on annual-curtailment hosting capacity across the 11
> screened single-bus and equal-share multi-bus configurations.

## Decision S1-3 — Paper framing and next-stage rationale

### Facts and empirical interpretation

- Under strict no-export and the current model, hosting capacity behaves
  primarily as a PCC power-balance quantity.
- Electrical voltage constraints retain feasibility relevance but do not
  determine the approximately 644.0813 kW zero-curtailment benchmark.
- Siting variation within the screened set remains below the project's 5%
  materiality threshold under the monotonicity-based bracket bound.

### Decision

Within the scope and assumptions of this paper, meaningful hosting-capacity
enhancement will be sought through operational flexibility rather than further
refinement of this restricted siting screen. This decision is the bridge to:

- S2 unmanaged EV charging;
- S3 coordinated EV flexibility;
- S4 BESS; and
- S5 DOE/TVPP and robust coordination.

Operational flexibility is the selected mechanism for S2–S5 in this paper. It
is not claimed to be the only possible enhancement mechanism in every network.

## Engineering decision for S2–S5

Numerical logic, validation, checkpointing, aggregation, and verdict
generation must reside in Julia. PowerShell is limited to a thin
launcher/logger. This follows the S1-C experience in which 12 PowerShell
orchestration anomalies occurred before the accepted numerical execution.
