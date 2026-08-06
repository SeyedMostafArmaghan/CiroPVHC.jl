# Pre-execution Amendment 3 — Absolute-PCC coordinate correction and probe redesign

**Amendment date:** 2026-08-06. This is additive. It does not delete, regenerate, or numerically reinterpret the locked Phase-B, analytical, or operating-point provenance artifacts.

1. Final DOE coordinates are absolute physical interface powers `P_PCC_abs`, with export positive and import negative.
2. The 850 kW reference PV at bus 13 is TVPP-owned. At the audited timestamp it contributes `777.7133428167988 kW` to `P_PCC_13_abs`.
3. Passive case loads at buses 13 and 30 remain DSO background. They are excluded from `P_PCC_abs` and enter only the DSO equation `p_net=passive_DSO_load-sum(P_PCC_abs)-other_nonload_DSO_injections`.
4. All existing Phase-B and analytical results are `COMMAND_COORDINATES` results. Their numerical scientific content remains valid and immutable.
5. At a fixed timestamp/background state, `P_PCC_abs=P_command+P_PCC_base`, with audited baseline `[777.7133428167988,0] kW`; equivalently `A_cmd_t=A_abs_t-P_PCC_base_t`.
6. A translated command-axis point is classified `TRANSLATED_COMMAND_AXIS_POINT`; it is not automatically a `TRUE_ABSOLUTE_PCC_AXIS_INTERCEPT`. In particular `(0,s30)` commands translate to `(777.7133428167988,s30)` absolute kW.
7. The locked `theta_star_command=76.03090274387165 degrees` and its command-axis scales will not determine the next production probe grid.
8. A new absolute-coordinate design requires origin feasibility, true positive/negative absolute-axis information, a finite domain independent of optimized `H`, and mixed-quadrant coverage before directions are fixed.
9. EV and BESS require import/export and mixed-sign quadrants that remain unscanned by the nonnegative command pilot.
10. No final absolute-PCC DOE, `theta_star_abs`, absolute-domain normalization, radial boundary, or star-shapedness claim is made here.

The present pilot policy is `UNITY_POWER_FACTOR`: `Q_PCC=kappa(P_PCC)=0`. Future fixed `Q(P)` policies must implement the interface-policy abstraction and must never absorb passive-load Q into `Q_PCC`.

`REFERENCE_PV_850_KW_IS_TVPP_OWNED` is selected. Whether final `H_13` means total installed capacity, expansion above the fixed 850 kW, or a replacement variable remains `REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION`.

**The existing command-space pilot results are scientifically valid.**

**The final absolute-PCC DOE has not yet been constructed or validated.**

No production radial/direction probe, AC map, DOE construction, EV/BESS/centralized optimization, constraint generation, or full-period campaign was executed for this amendment.
