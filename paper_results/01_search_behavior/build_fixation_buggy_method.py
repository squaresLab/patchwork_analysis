"""Build the search-vs-study GAZE-SHARE analysis.

This code setups the analysis of proportion of gaze time spent fixated on the
buggy method in comparison to the gaze time spent fixated on code that is _not_
the buggy method.  

Note that you probably don't need to run this! The csv it produces from the raw
fixation data is already in this directory.

The denominator is fixation duration over the four non-patch AOIs (Test and
Runtime Feedback, Tests, Source Code, Browser), in the normalized AOI labels of
the project's AOI aggregation (aggregate_gaze.py). Excludes Patch, Project
Explorer, OOB, Popup, and ``-``. Execution Inspection is folded into Test and
Runtime Feedback by the normalization.

The output also shows raw total minutes (buggy_min, other_min, total_fix_min)
for the illustration numbers; they aren't modeled.

Inputs:

1. The per-task FIXATION FILES at
   ``patchwork_data/<PID>/t<task_no>/<PID>_t<task_no>_fixation_filtered.csv``
   (PID with ``_`` rewritten to ``-`` on disk). Each is one row per gaze sample,
   carrying the fixation it belongs to (``fixation_group_id``,
   ``fixation_group_duration``), the AOI it landed on (``AOI``), and whether the
   gaze was on the buggy method (``on_method``). Per-AOI fixation durations are
   re-derived here because the buggy-vs-other ``on_method`` split has no
   pre-computed counterpart.

2. The TASK LIST from ``patchwork_analysis/timing_correctness_data.csv``.

Output: ``fixation_buggy_method_input.csv``, a per-task table written in this
directory and read by ``fixation_buggy_method.R``.

Run (from the repo root, with a Python 3.12+ that has the requirements):
    python3 patchwork_analysis/paper_results/01_search_behavior/build_fixation_buggy_method.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import (
    DATA,
    TIMING_CSV,
    disk_pid,
    fixation_groups,
    recover_ms_clock,
)

HERE = Path(__file__).resolve().parent
TIMING = TIMING_CSV
OUT = HERE / "fixation_buggy_method_input.csv"

SOURCE_AOI = "Source Code"

# Non-patch denominator AOIs, in the normalized AOI labels of the project's AOI
# aggregation (aggregate_gaze.py). "Test and Runtime Feedback" is the
# normalized label that folds in "Execution Inspection" and "Test and Run
# Output".
DENOM_AOIS = {"Test and Runtime Feedback", "Tests", "Source Code", "Browser"}

# P1 t1 is a tracking failure: it has gaze data, but the data are too spotty to
# use (Kaia drops it too).
OUTLIERS = {
    ("P1", 1),
}


def truthy(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).isin(["True", "TRUE", "true", "1"])


def task_props(pid: str, task_no: int) -> tuple[float, float, float] | None:
    """Return (buggy_minutes, other_minutes, nonpatch_fixation_minutes) where the
    denominator is fixation over the four non-patch AOIs (DENOM_AOIS). The
    fixation-group AOI is the per-group majority (mode) over normalized AOI
    labels, matching the project's AOI aggregation (aggregate_gaze.py). Returns
    None if the fixation file is missing/empty."""
    f = DATA / disk_pid(pid) / f"t{task_no}" / f"{disk_pid(pid)}_t{task_no}_fixation_filtered.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, low_memory=False, usecols=[
        "timestamp", "fixation_group_id", "fixation_group_duration",
        "AOI", "on_method"])
    df = df.dropna(subset=["fixation_group_id"])
    if df.empty:
        return None
    df = recover_ms_clock(df, ts_col="timestamp")
    df = df.assign(on_method=truthy(df["on_method"]))
    # Within a Source Code fixation group, the group is "on the buggy method" if
    # any of its samples are. This buggy-vs-other split is layered on top of the
    # shared fixation-group reduction.
    grp = fixation_groups(df, extra_aggs={"any_on": ("on_method", "any")})
    # Denominator: total fixation over the four non-patch AOIs only.
    total_fix = grp.loc[grp["aoi"].isin(DENOM_AOIS), "dur_ms"].sum() / 60000.0
    src = grp[grp["aoi"] == SOURCE_AOI]
    buggy = src.loc[src["any_on"], "dur_ms"].sum() / 60000.0
    other = src.loc[~src["any_on"], "dur_ms"].sum() / 60000.0
    return (float(buggy), float(other), float(total_fix))


def main() -> None:
    tim = pd.read_csv(TIMING)
    # A task has gaze iff Source Code_fixation_count is present
    gaze = tim[tim["Source Code_fixation_count"].notna()]

    rows = []
    for _, r in gaze.iterrows():
        pid, tno = r["PID"], int(r["task_no"])
        if (pid, tno) in OUTLIERS:
            continue
        res = task_props(pid, tno)
        if res is None:
            continue
        buggy, other, total_fix = res
        if total_fix <= 0:
            continue
        rows.append({
            "PID": pid, "task_no": tno, "bug": r["bug"],
            "condition": r["condition"], "correct": r["correct"],
            "buggy_min": buggy, "other_min": other, "total_fix_min": total_fix,
            "buggy_propfix": buggy / total_fix,
            "other_propfix": other / total_fix,
            "source_propfix": (buggy + other) / total_fix,
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"Rows written: {len(out)}")
    print("Per-condition N:")
    print(out.groupby("condition").size())
    print("\nMean fixation-duration proportion (of total fixation) by condition:")
    print(
        out.groupby("condition")[["buggy_propfix", "other_propfix", "source_propfix"]]
        .mean()
        .round(3)
    )
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
