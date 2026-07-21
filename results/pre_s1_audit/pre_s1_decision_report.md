# Pre-S1 decision report: critical days and thermal-data policy

## Locked inputs and non-actions

The starting point is commit `ded7673a43385326729e079b1b42bc5d9b47271e`. This audit changes no S0 or S1 model file, no network data, and no operating parameter. It does not execute S1 and does not rerun the 52,608-interval network calculation.

## Critical-day decision

Use the 32-day deduplicated candidate set in `critical_day_candidates.csv` for the next design review: the current top 30 high-PV/low-load days, the maximum-load day, the maximum-PV day, and the day with minimum load while `pv_profile >= 0.05`. The maximum-PV day is already in the top 30, so three special categories add only two new dates.

The existing stress score is numerically well-defined and its 0.05 denominator floor is inactive in the current data. It is acceptable as a screening metric, but it should not be the only robustness evidence because a daily maximum can be determined by one half-hour observation. No ranking change is authorized here. Before S1 temporal reduction is locked, add formula/floor regression tests and compare selection stability with a predeclared robust companion statistic such as the 95th percentile or a three-interval rolling-median maximum.

## Thermal inventory conclusion

The IEEE 33-bus data used by this repository contain branch resistance and reactance but no positive branch ratings: `smax_kva` is 0 for all branch IDs 1 through 32. In the generic SOCP network builder, both branch constraints are conditional on a positive rating:

\[
\sqrt{P_{ij,t}^2+Q_{ij,t}^2}\le S^{max}_{ij}
\]

and

\[
\ell_{ij,t}\le (S^{max}_{ij}/S_{base})^2.
\]

Therefore the default S1 path (`build_case33_data` followed by `solve_s1_pv_only`) has no active branch apparent-power or current limit.

The separate paper-policy S1 case replaces every raw zero with the same project assumption, 4,000 kVA, on all 32 branches. With the 10 MVA base, this is `smax_pu=0.4` and `ell<=0.16`. Interpreted at nominal 12.66 kV as the code comments specify, it corresponds to 182.417146663 A. This value is not from case33bw, conductor data, a utility rating, or a documented transformer rating. There is no implemented `kappa`, `κ_I`, `κ_tr`, ampacity table, conductor type, or thermal scaling factor. The complete code inventory is in `thermal_limit_inventory.csv`.

## Policy comparison

### A. Central result without a thermal constraint, with explicit missing-data disclosure

This preserves results supported by the available impedance and time-series data and avoids turning a convenient number into a physical claim. It cannot establish thermal adequacy or a physical thermal hosting capacity. This is the recommended central policy for this project.

### B. Synthetic thermal constraint only as a parametric sensitivity

This can show how an assumed uniform rating changes the optimization result, provided several predeclared values are swept and none is labeled as measured. Every resulting quantity must be named **“HC under assumed thermal capacity”**, not physical HC. A single 4 MVA case is insufficient for a central claim and uniform ratings across all 32 electrically different branches are not physically evidenced.

### C. Withhold thermal conclusions until conductor or ampacity data arrive

This is mandatory for any claim about real thermal headroom, overload risk, or physical thermal hosting capacity. Required inputs include at least conductor/cable type and cross-section, installation and ambient conditions, normal/emergency rating convention, branch-specific ampacity or MVA ratings, and transformer rating where relevant. It need not block a clearly labeled non-thermal central study.

## Decision

Adopt **A** for the central S1 result, use **B** only if a clearly labeled parametric sensitivity is useful, and apply **C** to all real-world thermal conclusions. This combination is the most scientifically defensible because it separates what the present data support from what requires missing equipment data.
