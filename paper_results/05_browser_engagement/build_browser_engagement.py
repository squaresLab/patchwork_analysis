"""Build the late-task BROWSER-ENGAGEMENT analysis input.

This splits each task's gaze timeline into early / mid / late thirds (by time)
and measures the share of fixation duration that lands on the Browser AOI in
each third. The finding of interest is late-task browser look-up: whether a
deceptive (overfitting) patch prompts more late browser engagement to verify a
distrusted suggestion.

Note that you probably don't need to run this! The csv it produces from the raw
fixation data is already in this directory (``browser_engagement_input.csv``).

How the measure is computed
---------------------------
Each per-task fixation file is one row per gaze sample, carrying the fixation it
belongs to (``fixation_group_id``, ``fixation_group_duration``) and the AOI it
landed on (``AOI``). Samples are collapsed to one row per fixation group. The
group's AOI is the MAJORITY (mode) AOI over its samples; its duration is
``fixation_group_duration`` (constant within the group); its time is the first
sample's ``timestamp``. The task timeline is [min, max] of the fixation-group
start times, split into equal-time thirds. For each third we sum Browser
fixation duration and total fixation duration (minutes) and report the Browser
share. ``whole`` is the same share over the whole task. ``late_any`` is 1 iff
the late third has any Browser fixation. ``span`` is the timeline length in
minutes; ``n_fix`` is the number of fixation groups.

Where the data is and where it came from
----------------------------------------
Two local inputs, both primary project data:

1. The per-task FIXATION FILES at
   ``patchwork_data/<PID>/t<task_no>/<PID>_t<task_no>_fixation_filtered.csv``
   (PID with ``_`` rewritten to ``-`` on disk).
2. The TASK LIST from ``patchwork_analysis/timing_correctness_data.csv`` (PID,
   task_no, bug, condition, correct; a task has gaze iff
   ``Source Code_fixation_count`` is present).

This builder reads nothing under ``explorations/``.

Output: ``browser_engagement_input.csv``, written in this directory and read by
``browser_engagement_models.R``.

Run (from any directory, with a Python 3.12+ that has the requirements):
    python3 patchwork_analysis/paper_results/05_browser_engagement/build_browser_engagement.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import DATA, TIMING_CSV, disk_pid, recover_ms_clock

HERE = Path(__file__).resolve().parent
OUT = HERE / "browser_engagement_input.csv"

BROWSER_AOI = "Browser"

# P1 t1 is a tracking failure: it has gaze data, but the data are too spotty to
# use (Kaia drops it too).
OUTLIERS = {
    ("P1", 1),
}


def _mode_aoi(s: pd.Series) -> str:
    """Majority AOI over a fixation group's samples (most frequent value).

    ``pandas.Series.mode`` breaks ties alphabetically (it returns the sorted set
    of most-frequent values), so the assignment is deterministic regardless of
    sample order."""
    return s.mode().iloc[0]


def task_thirds(pid: str, task_no: int) -> dict[str, float] | None:
    """Per-task browser-engagement measures, or None if the fixation file is
    missing/empty. Splits the fixation-group timeline into equal-time thirds and
    returns the Browser share in each, plus whole-task share, late-third browser
    and total fixation minutes, the late_any indicator, span (min) and n_fix."""
    f = (
        DATA
        / disk_pid(pid)
        / f"t{task_no}"
        / f"{disk_pid(pid)}_t{task_no}_fixation_filtered.csv"
    )
    if not f.exists():
        return None
    df = pd.read_csv(
        f,
        low_memory=False,
        usecols=["timestamp", "fixation_group_id", "fixation_group_duration", "AOI"],
    )
    df = df.dropna(subset=["fixation_group_id"])
    if df.empty:
        return None
    df = recover_ms_clock(df, ts_col="timestamp")

    grp = df.groupby("fixation_group_id").agg(
        dur_ms=("fixation_group_duration", "first"),
        ts=("timestamp", "mean"),
    )
    grp["aoi"] = df.groupby("fixation_group_id")["AOI"].agg(_mode_aoi)
    if grp.empty:
        return None

    # The timeline spans all gaze samples in the task, not just fixation-group
    # start times, so the third boundaries match the full recording length. A
    # fixation group is assigned to a third by the MEAN timestamp of its samples.
    t0 = float(df["timestamp"].min())
    t1 = float(df["timestamp"].max())
    span_ms = t1 - t0
    b1 = t0 + span_ms / 3.0
    b2 = t0 + 2.0 * span_ms / 3.0
    ts = grp["ts"].to_numpy()
    third = np.where(ts < b1, "early", np.where(ts < b2, "mid", "late"))
    grp = grp.assign(third=third)

    def share(g: pd.DataFrame) -> tuple[float, float, float]:
        br = float(g.loc[g["aoi"] == BROWSER_AOI, "dur_ms"].sum()) / 60000.0
        tot = float(g["dur_ms"].sum()) / 60000.0
        return br, tot, (br / tot if tot > 0 else 0.0)

    parts = {th: grp[grp["third"] == th] for th in ("early", "mid", "late")}
    early_share = share(parts["early"])[2]
    mid_share = share(parts["mid"])[2]
    late_br, late_tot, late_share = share(parts["late"])
    whole_share = share(grp)[2]

    return {
        "whole": whole_share,
        "early": early_share,
        "mid": mid_share,
        "late": late_share,
        "late_browser_dur": late_br,
        "late_total_dur": late_tot,
        "late_any": 1 if late_br > 0 else 0,
        "span": span_ms / 60000.0,
        "n_fix": int(len(grp)),
    }


def main() -> None:
    tim = pd.read_csv(TIMING_CSV)
    # A task has gaze iff Source Code_fixation_count is present.
    gaze = tim[tim["Source Code_fixation_count"].notna()]

    rows = []
    for _, r in gaze.iterrows():
        pid, tno = r["PID"], int(r["task_no"])
        if (pid, tno) in OUTLIERS:
            continue
        res = task_thirds(pid, tno)
        if res is None:
            continue
        rows.append(
            {
                "PID": pid,
                "task_no": tno,
                "condition": r["condition"],
                "whole": res["whole"],
                "early": res["early"],
                "mid": res["mid"],
                "late": res["late"],
                "late_browser_dur": res["late_browser_dur"],
                "late_total_dur": res["late_total_dur"],
                "late_any": res["late_any"],
                "span": res["span"],
                "n_fix": res["n_fix"],
                "bug": r["bug"],
                "correct": r["correct"],
            }
        )

    out = pd.DataFrame(rows)
    # Lexicographic PID-string then task_no order, matching the directory-walk
    # order of the upstream producer. The permutation test in the R model draws
    # its random permutations in CSV row order under a fixed seed, so the row
    # order is part of reproducing the reported permutation p-value.
    out = out.sort_values(
        by=["PID", "task_no"], key=lambda c: c.astype(str) if c.name == "PID" else c
    ).reset_index(drop=True)
    out.to_csv(OUT, index=False)
    print(f"Rows written: {len(out)}")
    print("Per-condition N:")
    print(out.groupby("condition").size())
    print("\nP(any late browser) by condition:")
    print(out.groupby("condition")["late_any"].mean().round(3))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
