# CiroPVHC.jl — Operating Rules

## Git
- Never add Co-Authored-By, Signed-off-by, Generated-by, or other attribution
  trailers to Git commits unless the user explicitly requests them.
- `git add -A` is forbidden. Stage explicit paths only.
- Push to feature branches only. Never merge to main.
- Review the full diff of every patch before committing.

## Execution
- Only ONE Claude Code session may be active on this working tree at a time.
- No subagents, dynamic workflows, parallel Task/agent dispatch, or any
  concurrent execution on this working tree. All work strictly serial.
  If a task looks too large, stop and report — do not parallelize.
- Run `pwd` before any path-sensitive command.
- Every run must tee stdout and stderr to a timestamped file in the scratchpad,
  and record the process exit status in that file.

## Julia script structure (mandatory)
- All logic must live inside `main()` or another function scope. No top-level
  code except the call to `main()`. Julia soft-scope rules silently create a
  new local when a global is assigned inside a top-level loop — this has
  inverted a verdict three times in this project.
- No aggregation inside a global-scope loop. Accumulate with `push!` into a
  collection, then reduce with `all` / `any` / `maximum` outside the loop.
- Recompute every final verdict from the written CSV, not from an in-memory
  variable. The run and the independent recomputation must agree.
- Assert thresholds and row counts explicitly. A silent count mismatch is a
  failure, not a warning.

## Code
- Never reproduce code from memory. Read it from the repository.
- No unaudited code reaches production.
- No tuning for convergence: not solver tolerances, not solver options.
- Do not change formulation, bounds, objective, or tolerances unless the change
  is the explicit subject of the task.

## Locked model invariants (do not change without explicit instruction)
- Voltage band: 0.90 - 1.05 p.u. Justified by a zero-PV annual baseline
  (annual min 0.913090 p.u. at bus 18; 336 intervals below 0.95).
- Strict no-export floor in the OPTIMIZATION MODEL is exactly 0.0.
  Reverting to `>= -tol` is explicitly forbidden.
- `NO_EXPORT_TOL_KW = 1e-3` belongs to replay/audit paths ONLY.
  It must never appear as a constraint bound in the optimization model.
- PV candidate buses: 13, 20, 24, 30 (screening shortlist, not optimal siting).
- Half-hourly steps, dt = 0.5 h, 52608 intervals.

## Data provenance
- Persistent scratchpad: D:\CiroPVHC_scratch\s1c
  Do not write results to AppData\Local\Temp - Windows may delete it.
- Ausgrid data is never modified: no deletion, no interpolation of DST intervals.

## Independent physical-input verification
- Any verification intended to validate physical model inputs must reconstruct
  the bus-injection vector independently from primary inputs and canonical
  source data, including installed capacity `H`, profile factor `f_t`, raw load
  data, and external VPP injection commands. It must not use the main assembled
  injection vector as its sole source. Agreement between two consumers of the
  same assembly validates numerical consistency, not physical input correctness.
- Independent replay and residual checks remain necessary, but they do not
  replace independent reconstruction of physical inputs.

## Claims discipline
- Never claim global optimality. Multistart gives clusters, not proofs.
- The full-period replay uses the same validated AC replay engine; it is a
  separate code path, NOT an independent implementation. Wording in the paper
  must say "separate full-period replay using the same validated AC replay
  engine", never "independent AC validation".
