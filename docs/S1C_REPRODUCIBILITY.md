# S1-C reproducibility and evidence retention

## Curated repository package

The compact S1-C package is under
`results/s1c_curtailment_benchmark/`. It contains:

- the 20-point, three-year bus-13 annual sweep;
- definitions of the 11 screened configurations;
- zero-curtailment HC results;
- normalized H=810, 850, 975, and 1075 kW probe summaries;
- the common-bracket checks;
- descriptive 1% interpolation results;
- the materiality summary; and
- `evidence_manifest.csv`, which records sizes and SHA-256 checksums for both
  curated files and the retained external evidence.

For `storage=git` rows, byte sizes and SHA-256 values use LF-normalized text so
they are stable across Git checkout line-ending settings. For
`storage=external` rows, sizes and SHA-256 values cover the preserved raw
bytes.

Run the fast repository validator from the repository root:

```powershell
julia --project=. scripts/validate_s1c_curated.jl
```

That command reads CSVs and verifies summaries only. It does not build an
optimization model or launch Ipopt.

Where the preserved primary evidence is available beneath a common local
directory, add the optional external base to verify every external entry
listed in the curated manifest:

```powershell
julia --project=. scripts/validate_s1c_curated.jl --external-base=<external-evidence-root>
```

The value is a local provenance parameter and is deliberately not embedded in
tracked files.

## External evidence

Three complete evidence sets are retained outside Git:

- `s1c_bundle_20260727_v2`;
- `s1c_supplement_part2_20260728`; and
- `s1c_h810_probe_20260728_132637`.

Their top-level manifest SHA-256 values are, respectively:

- `fb4586b079cf5f8eb62d55cf7aad98e6865dffc9ff4b5e43e5b6129724e31446`;
- `8ce3b9210e17ff85db212d7cf7e45fb6266965ea63b9cdc480052817d593aad1`;
  and
- `c9a61420af8c9cd3716a1a05ed5d5590a19e924cb1dd23d90713668276d295e8`.

The first two manifests validate 52 and 25 entries. The H=810 manifest
validates 61 entries. The 27-row Part 2 and 11-row H=810 completion markers
bind their result CSVs to SHA-256 values
`33d8828806c4132b4835c5bd999951fb11b18e3d8f3f86b0f2ccb19edb6c583e`
and
`1167d0008943c8ea2267926e342c98ec4f2d85c686d3d41093e6a16f24715629`.

The external sets retain interval-level output, solver-level output, exact run
scripts, dependency snapshots, logs, completion markers, methodology notes,
and provenance. Raw 52,608-interval CSVs are intentionally excluded from Git.
The repository summaries support audit of the reported conclusions; the
external manifests identify the complete preserved calculation record.

The verified safety locations are copies on the same storage volume. They are
not an independent disaster-recovery copy. Verification of an independent
USB, cloud, or other separate-media copy remains a manual prerequisite.

## Accepted execution configuration

The accepted H=810 execution used:

- Julia 1.12.6;
- JuMP 1.30.1;
- Ipopt 1.15.0;
- Clarabel 0.11.1;
- 1 Julia thread;
- 12 logical CPUs reported by the system;
- 6 BLAS threads reported by Julia;
- approximately 850.74 MiB peak observed RAM;
- approximately 177 seconds foreground wall time; and
- approximately 157.25 seconds summed per-siting runtime.

Execution was serial at the Julia orchestration level, while BLAS reported
multiple threads. No solver attributes or tolerances were changed.

PowerShell orchestration produced 12 development-time anomalies before the
accepted numerical execution. They were caught before the accepted
calculation. Accepted outputs passed a separate summary recomputation, no
numerical evidence was contaminated, and repository state remained unchanged
during the accepted run.

## Model and validation wording

The strict no-export optimization floor is exactly 0.0 kW. The 0.001 kW
tolerance applies only to replay/audit checks. Voltage magnitude is limited to
0.90–1.05 p.u.; PV uses unity power factor; and no validated transformer or
branch thermal ratings are imposed.

Full-period validation is described as a **separate full-period replay using
the same validated AC replay engine**. It is not described as independent AC
validation. Ipopt multistart supplies local-solution evidence only; no global
optimality claim is made.

## Future execution architecture

For S2 and later stages, numerical logic, validation, checkpointing,
aggregation, and verdict generation belong in Julia. PowerShell remains a thin
launcher/logger.
