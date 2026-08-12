# DOE boundary-design audit: Git state

## Initial state captured before any audit file change

```text
git status --short
<empty>

git status -sb
## codex/dso-vpp-ac-map-pilot...origin/codex/dso-vpp-ac-map-pilot [ahead 5]

git branch --show-current
codex/dso-vpp-ac-map-pilot

git rev-parse HEAD
8ce89e4de76a14ecbe8de29611f112d5695854da

git log --oneline --decorate -10
8ce89e4 (HEAD -> codex/dso-vpp-ac-map-pilot) docs: preregister absolute-PCC probe redesign
a89d9ad refactor: distinguish command and absolute PCC coordinates
461892d docs: clarify multi-interface TVPP architecture
5fc6ac1 docs: amend probe metrics after provenance audit
4c47823 test: verify Phase-B operating-point provenance
d8e1bb0 (origin/codex/dso-vpp-ac-map-pilot) docs: preregister analytically identified corner directions
beb7df9 feat: audit AC-anchored linear corner structure
79d92dc docs: preregister fixed radial normalization
24138a3 feat: make export-side AC axis scan reproducible
ae24e08 Repair Stage 0 reference PV propagation

git remote -v
origin https://github.com/SeyedMostafArmaghan/CiroPVHC.jl.git (fetch)
origin https://github.com/SeyedMostafArmaghan/CiroPVHC.jl.git (push)

git branch -vv
* codex/dso-vpp-ac-map-pilot 8ce89e4 [origin/codex/dso-vpp-ac-map-pilot: ahead 5] docs: preregister absolute-PCC probe redesign
  main                       282663d [origin/main] Lock S1 and S2 baseline before protection proxy

git ls-remote --heads origin codex/dso-vpp-ac-map-pilot
d8e1bb0a7909711b4124f95673fb3a4802ae783a refs/heads/codex/dso-vpp-ac-map-pilot
```

The remote query was executed successfully at audit start. All five requested commits are local objects, ancestors of the initial HEAD, and absent from the remote branch tip:

| commit | local status | remote status | subject |
|---|---|---|---|
| `4c478232428dcb8f28be2d85ed12cf1c84fc7925` | present; ancestor of initial HEAD | absent; remote tip predates it | test: verify Phase-B operating-point provenance |
| `5fc6ac12fe115acf2de282b5c10c821d400e0cc7` | present; ancestor of initial HEAD | absent; remote tip predates it | docs: amend probe metrics after provenance audit |
| `461892dcae37b16c1e640d430ab0df92957fc5cd` | present; ancestor of initial HEAD | absent; remote tip predates it | docs: clarify multi-interface TVPP architecture |
| `a89d9ad254a19ac9098b326e78e2ecd8b8ed092b` | present; ancestor of initial HEAD | absent; remote tip predates it | refactor: distinguish command and absolute PCC coordinates |
| `8ce89e4de76a14ecbe8de29611f112d5695854da` | present; ancestor of initial HEAD | absent; remote tip predates it | docs: preregister absolute-PCC probe redesign |

**`LOCAL_SCIENTIFIC_PROVENANCE_NOT_YET_BACKED_UP_TO_REMOTE`**

## Audit working-tree state after deterministic generation

```text
git diff --name-only
<empty: no tracked scientific artifact changed>

git status --short
?? results/dso_vpp_ac_map_pilot/doe_boundary_design_audit/
```

No push, rebase, amend, merge, or history rewrite was performed by this audit.
