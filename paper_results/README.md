# paper_results

Five process/gaze analyses, each self-contained and reproducible from the raw
study data. Every finding follows the same shape: a Python **builder** turns the
raw per-task data into one tidy input CSV, and an R **model** fits that CSV and
writes a results JSON to `results/`.

The results JSONs are the source of truth for every number. This README does not
repeat them; to see a finding's estimates, read its `results/results_<finding>.json`
(or rerun its model). Each JSON records the contrast estimates, p-values, BH-
adjusted p-values, the random-effect structure actually used, and the per-cell
counts.

## Setup (running on another machine)

Nothing is hardcoded to one laptop.

1. **Paths.** Two environment variables, each with a default:
   - `PATCHWORK_ROOT` — repo root. Defaults to the nearest ancestor directory
     named `patchwork_analysis`, so it usually needs no setting.
   - `PATCHWORK_DATA` — the raw per-task gaze/IDE data (the large
     `patchwork_data/<PID>/t<n>/` files). Defaults to `$PATCHWORK_ROOT/patchwork_data`.
     Set it if the data lives apart from the code.
2. **Python deps.** `python3 -m pip install -r requirements.txt` (pandas, numpy).
3. **R deps.** `Rscript install.R` (lme4, lmerTest, emmeans, jsonlite, MASS).
   `lme4` needs a C/C++/Fortran toolchain to compile.

Interpreters are overridable in the `Makefile` (`PY ?= python3`, `RS ?= Rscript`);
run e.g. `make PY=/path/to/python3` to point at a specific Python 3.12+.

## Run it

```
make all          # every finding: build inputs, fit models, write results/ + logs/
make <finding>    # just one: search, editing, validation, debugger, browser
make clean        # remove generated results JSONs and input CSVs
```

A builder reads only the raw data under `$PATCHWORK_DATA` plus the task list from
`patchwork_analysis/timing_correctness_data.csv`. It writes its input CSV next to
the model that consumes it. Nothing depends on the `explorations/` tree. The
committed input CSVs let the models run without rebuilding; rebuild on demand by
running a builder (each prints a "you probably don't need to run this" note,
because its CSV is already committed).

## Layout

```
lib/
  patchwork_io.py      shared paths/PID/project-file/IDE-log/gaze-clock helpers
  model_helpers.R      RE-dropping fallback fitter, planned contrasts, JSON writer
01_search_behavior/    does a patch reduce the developer's SEARCH?
  build_fixation_buggy_method.py -> fixation_buggy_method.R   (gaze: buggy vs other-method fixation share)
  build_ide_navigation.py        -> ide_navigation.R          (IDE: navigation events, files opened)
02_patch_editing/      how does a developer use the suggested patch?
  build_patch_usage.py -> patch_editing_models.R
  PATCH_USAGE_METHOD.md   full writeup of the patch_usage categorization
03_validation_window/  is there more fix-validation behavior under a patch?
  build_validation_window.py -> validation_window_models.R
04_debugger_use/       does a patch change debugger use?
  build_debugger_use.py -> debugger_use_models.R
05_browser_engagement/ late-task browser look-up by condition
  build_browser_engagement.py -> browser_engagement_models.R
results/   results_<finding>.json  (the source of truth for every number)
logs/      per-run build/model logs (gitignored)
```

## Modeling conventions (in `lib/model_helpers.R`)

- Crossed random intercepts `(1|PID)+(1|bug)`, with a fallback when not estimable:
  try full, then drop `(1|bug)`, then drop `(1|PID)`, then plain `lm`/`glm`. The
  structure actually used is recorded in every JSON record, so it is auditable
  rather than a hidden degree of freedom.
- Planned contrasts from the condition factor. Most findings use
  `patch_vs_control` and `correct_vs_overfit`. The patch-editing finding has no
  control condition, so its contrast is overfitting-vs-correct; a few findings add
  a finding-specific contrast. Each JSON names its own contrasts.
- BH correction within a finding's family of contrasts, never across findings.
- Odds/rate ratios via `exp()` for logistic and count models; continuous outcomes
  reported on their natural scale.

## Findings

| Finding (`make` target) | Question | Builder → model | Results |
|---|---|---|---|
| **search** | Does a patch shift gaze away from non-buggy code, and reduce IDE search? | `build_fixation_buggy_method.py` → `fixation_buggy_method.R`; `build_ide_navigation.py` → `ide_navigation.R` | `results_fixation_buggy_method.json`, `results_ide_navigation.json` |
| **editing** | When/how does a developer take, rework, or replace the suggested patch, and does that relate to correctness? | `build_patch_usage.py` → `patch_editing_models.R` | `results_patch_editing.json` |
| **validation** | In the window after the last fix edit, is there more validation behavior under a patch? | `build_validation_window.py` → `validation_window_models.R` | `results_validation_window.json` |
| **debugger** | Does having a patch change whether developers use the debugger? | `build_debugger_use.py` → `debugger_use_models.R` | `results_debugger_use.json` |
| **browser** | Do developers consult the browser more late in the task under a deceptive patch? | `build_browser_engagement.py` → `browser_engagement_models.R` | `results_browser_engagement.json` |

The gaze findings normalize by fixation over the four non-patch AOIs
(Test-and-Runtime-Feedback, Tests, Source Code, Browser), matching Kaia's AOI
analyses in the manuscript; the Patch AOI is excluded because it exists only in
the patch conditions. The patch_usage categorization is documented in
`02_patch_editing/PATCH_USAGE_METHOD.md`.

## Caveats (read the JSON for the numbers)

- **browser is suggestive, and method-dependent.** The correct-vs-overfit
  difference is borderline under the model and clears nothing under a permutation
  test; both p-values are in the JSON. No confirmatory bounded-proportion model was
  feasible (glmmTMB needs gfortran; Stan is absent). Treat it as a trend.
- **patch-editing own-fix contrasts are small-N and unstable.** Several cells are
  tiny, so the odds ratios can be separation-driven; the JSON flags each contrast's
  stability and carries the descriptive rates, which are what to report.
- **counts use all recorded IDE actions.** The IDE builders count actions whether
  they appear under an `event=` or an `id=` attribute (the six P*_0 participants
  use `id=`); both are tallied.
