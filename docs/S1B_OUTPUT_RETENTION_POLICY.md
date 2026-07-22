# S1-B output retention policy

This policy applies to the exact-AC operating-point constraint-generation workflow. It does not alter the Ausgrid preparation pipeline or any existing S0 result.

## Commit

- Source code, tests, and run scripts.
- The production configuration (`results/s1b_ac_constraint_generation/production_configuration.txt`) after a production run is authorized.
- Compact iteration summaries (`iteration_summary.csv`) containing active-set counts, start outcomes, accepted objectives, replay-failure counts, and worst voltage excess.
- Compact Markdown reports and the final accepted capacity summary.
- Small provenance/configuration files needed to identify the input profile and controls.

## Retain locally but ignore

- `results/s1b_ac_constraint_generation/checkpoints/` and its smoke-test counterpart. These contain resumable state plus per-start and per-interval replay CSVs for every completed iteration.
- `solver_tmp/` directories beneath those two output roots.

The ignored checkpoint directory is operational evidence and should be retained on the machine until the run is accepted and archived. Its state signature prevents resuming with a different validation index set or safety configuration.

## Regenerate on demand

- Full interval-level replay tables and per-iteration start tables after a completed study has been archived.
- Solver scratch/log files.

Regeneration uses the tracked scripts and the tracked normalized input profile at `data_processed/ausgrid/ausgrid_halfhour_normalized.csv`. The narrow ignore rules do not match `data_processed/`, compact summaries, or Markdown reports.

The existing tracked S0 interval table is intentionally unchanged. No history rewrite, Git LFS migration, or deletion is part of this policy.
