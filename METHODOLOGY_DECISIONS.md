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
- The result is called **voltage-constrained PV hosting capacity**, not complete technical or thermal hosting capacity.
- The archived value 2,766.97 kW is not an S1-B result; it belongs to an earlier policy-limited path.
- Independent AC validation applies the common capacity vector, zero curtailment, and allowed export to all 52,608 half-hour intervals. It performs no thermal validation because branch ampacity data are unavailable.
- If AC validation finds a voltage-violating interval that is not already modeled, the interval is added and the common-capacity SOCP is solved again. If a violation remains at an already modeled interval, it is reported as an SOCP/AC consistency blocker; no hidden cap or voltage margin is introduced.
- No second-stage loss or voltage-quality objective, S1-C policy, gamma-cap sensitivity, no-export sensitivity, curtailment sensitivity, or 4 MVA sensitivity is part of S1-B.
