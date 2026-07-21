# S1-B one-day method decision benchmark

## Scope and common configuration

Both methods use all 48 half-hour intervals on 2010-12-21, one shared capacity vector at buses 13/20/24/30, the same load and PV availability, 10 MVA/12.66 kV bases, V0=1.00 p.u., and 0.90-1.05 p.u. voltage limits. Curtailment, site caps, gamma caps, no-export, loss caps, thermal ratings, and transformer limits are absent. This is a one-day diagnostic, not the three-year result.

## Nonconvex branch-flow AC multistart

- Starts executed: 13; accepted AC-feasible local solutions: 13.
- Best locally optimal AC-feasible HC: 10680.484846163 kW (C13=733.640257286, C20=4681.670271374, C24=3988.773998170, C30=1276.400319333).
- Independent replay: Vmin=0.974427788, Vmax=1.050000005, max import=1171.305187 kW, max export=9469.200668 kW, max active loss=502.200418 kW.
- Maximum NLP constraint residual 2.988e-16; maximum NLP/replay voltage difference 1.821e-14 p.u.
- No global optimum is claimed.
- Spatial non-uniqueness among near-best starts: false; maximum allocation spread=1.864464138634503e-11 kW.
  This is evidence across the declared starts, not a proof of global spatial uniqueness.

## Strengthened SOCP sweep

The dimensionless objective is `HC/3715 - lambda * mean_active_loss/3715`. The predeclared exactness gate requires maximum normalized SOC residual <=1e-5, zero AC voltage violations at 1e-5 p.u., and maximum SOCP/AC voltage difference <=1e-4 p.u.

- Lambda=0 convex relaxation objective: 240084.200108895 kW; relative SOC gap 9.998e-01; AC feasible=no. It is an upper bound, not achievable HC while non-exact.
- Approximately exact sweep points: 0 of 9; stable adjacent exact pairs: 0.
- Best gap in the sweep occurs at lambda=1 and is still 9.995430e-01; AC feasible=no.
- At lambda=10, HC falls 94.783% from the lambda=0 upper bound to 12524.755432 kW, but the point remains non-exact and AC-infeasible.
- The strongest-penalty SOCP point is 17.268% above the best nonconvex branch-flow AC HC, but it is not achievable under AC validation.
- lambda=0: HC=240084.200109 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753128].
- lambda=1e-06: HC=240084.191466 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753133].
- lambda=1e-05: HC=240084.190282 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753132].
- lambda=0.0001: HC=240084.190122 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753124].
- lambda=0.001: HC=240084.194895 kW, rel_gap=9.999e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753115].
- lambda=0.01: HC=240084.193126 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753122].
- lambda=0.1: HC=240084.178941 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974530, 1.753024].
- lambda=1: HC=240080.609622 kW, rel_gap=9.995e-01, AC=infeasible, exact=no, AC V=[0.974531, 1.751491].
- lambda=10: HC=12524.755432 kW, rel_gap=9.998e-01, AC=infeasible, exact=no, AC V=[0.974429, 1.061940].

## Decision

**move S1-B to nonconvex branch-flow AC**

The nonconvex branch-flow AC model produced a repeatable independently replayed solution, while the penalty sweep did not provide a stable, approximately exact, AC-feasible region within 1% of it. Choosing a single penalty would therefore be fragile or would materially alter HC.

## Scientific limitations

The nonconvex branch-flow AC result is local, not globally certified. This benchmark covers one critical day only and has no thermal validation because real ampacity data are absent. It does not run the 32-day design, three-year validation, constraint generation, robust optimization, S1-C, or sensitivity cases. The earlier invalid SOCP result remains preserved in its original commit and files.
