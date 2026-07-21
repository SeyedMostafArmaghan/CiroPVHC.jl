# S1-B central decision report

This run evaluates voltage-constrained PV hosting capacity only. It does not establish thermal hosting capacity.

## Mathematical status

- Solver termination: `OPTIMAL`
- Primal status: `FEASIBLE_POINT`
- Dual status: `FEASIBLE_POINT`
- Initial/final optimization intervals: 1536 / 1536
- Constraint-generation iterations: 1
- Voltage-constrained HC: 240084.22889737104 kW
- Bus 13 capacity: 7660.933187226685 kW
- Bus 20 capacity: 97261.2945593653 kW
- Bus 24 capacity: 99539.84295279952 kW
- Bus 30 capacity: 35622.15819797954 kW

## Scope confirmation

Site caps, gamma caps, no-export policy, curtailment, loss caps, thermal limits, ampacity limits, transformer limits, and the synthetic 4 MVA rating are absent. The shared capacity vector is applied without curtailment. Export is allowed. AC validation performs no thermal check.

## Remaining blocker

AC voltage violations remain at interval(s) already present in the SOCP. This is an SOCP-relaxation/AC consistency blocker; no hidden voltage margin was applied.
