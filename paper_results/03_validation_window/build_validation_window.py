"""Build the VALIDATION-WINDOW model input from primary data.

Note that you probably don't need to run this! The csv it produces from the raw
IDE-event and gaze fixation data is already in this directory.

The validation window for a task runs from the LAST source edit
(``t_last_source_edit``) to the end of the task. ``t_last_source_edit`` is the
timestamp of the last edit to a SOURCE ``.java`` file in the IDE event stream;
``t0`` is the task start (the first IDE event). Within that post-fix window we
measure four gaze quantities and compare each to its whole-task counterpart.

It reads only primary data. The IDE event stream gives the post-fix window
boundary; the gaze fixation files give the AOI shares within that window.

Inputs (all local, primary data)
---------------------------------
1. The TASK LIST, condition/bug/correct, gaze presence, and per-task durations
   from ``patchwork_analysis/timing_correctness_data.csv``. The analyzed task set
   is every task with a resolvable IDE log (direct ``t<n>/ide_tracking.xml`` or
   merged ``t<n>_part*`` logs). ``has_gaze`` is true iff the task's
   ``Source Code_fixation_count`` is present. ``time_minutes`` is the
   authoritative task span, also used to cap ``window_dur_min``.
2. The per-task IDE event logs
   ``patchwork_data/<disk_pid>/t<task_no>/ide_tracking.xml`` (or the
   ``t<task_no>_part*`` parts, merged). From each we derive ``t0`` (first event
   timestamp) and ``t_last_source_edit`` (last source-edit timestamp).
   ``has_window`` flags tasks with at least one source edit.
3. The per-task FIXATION FILES
   ``patchwork_data/<disk_pid>/t<task_no>/<disk_pid>_t<task_no>_fixation_filtered.csv``
   for the AOI fixation-time shares within the window and over the whole task.

Edit detection
--------------
Edits are identified by ``<typing>`` elements (char-level keystrokes carrying a
``path``) plus a set of edit ACTION events (paste/backspace/SaveAll/...). An edit
counts toward the source-edit timeline only when its ``path`` is a real project
``.java`` SOURCE file (not test, not JDK/library/archive). The IntelliJ
apply-patch dialog event (``ChangesView.ApplyPatch``) is counted unconditionally
as a source edit (its path is the pseudo-file ``/suggested.patch``).
``t_last_source_edit`` is the max of all source-edit timestamps.

Clock alignment
---------------
The per-sample fixation ``timestamp`` and the IDE event timestamps are the same
Tobii epoch milliseconds, so ``t_last_source_edit`` is a valid absolute boundary
on the fixation timeline. No clock recovery is applied; the window is the raw
millisecond comparison ``timestamp >= t_last_source_edit``.
``window_dur_min`` is the span from the last
edit to the last in-window fixation, clipped to ``[0, real_task_duration]``.

Run (from anywhere; cwd-independent):
    python3 patchwork_analysis/paper_results/03_validation_window/build_validation_window.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import (
    APPLY_ACTION,
    DATA,
    EDIT_ACTIONS,
    TIMING_CSV,
    disk_pid,
    is_source,
    iter_ide_events,
    resolve_logs,
)

HERE = Path(__file__).resolve().parent
OUT = HERE / "validation_window_model_input.csv"


def parse_task(xml_paths: list[Path]) -> dict[str, float | int | None]:
    """Stream the actions + typing elements; return (t0, t_last_source_edit).

    Reduced to the two timestamps the validation window needs. ``t0`` is the
    earliest event timestamp; ``t_last_source_edit`` is the latest source-edit
    timestamp (None if no source edit occurred). Only the edit-related action
    set (``EDIT_ACTIONS``) and the apply-patch action matter here.

    A task split across ``t<n>_part*`` logs passes all its parts here; events
    accumulate across them, and t0/t_last_source_edit are the min/max over the
    union, so the result is independent of part order.
    """
    timestamps: list[int] = []
    source_edit_ts: list[int] = []

    for xml_path in xml_paths:
        for kind, attrs in iter_ide_events(xml_path):
            if kind == "action":
                ev = attrs["key"]
                ts = attrs["timestamp"]
                path = attrs["path"]
                if ts is not None:
                    timestamps.append(ts)
                    if ev == APPLY_ACTION:
                        # Applying the suggested patch via the IntelliJ
                        # Apply-Patch dialog changes source. The action's path is
                        # typically /suggested.patch, so do NOT gate on
                        # is_source(path); count it unconditionally as a source
                        # edit.
                        source_edit_ts.append(ts)
                    elif ev in EDIT_ACTIONS:
                        if is_source(path):
                            source_edit_ts.append(ts)
            elif kind == "typing":
                ts = attrs["timestamp"]
                path = attrs["path"]
                if ts is not None:
                    timestamps.append(ts)
                    if is_source(path):
                        source_edit_ts.append(ts)

    if not timestamps:
        return {"t0": None, "t_last_source_edit": None}
    return {
        "t0": int(min(timestamps)),
        "t_last_source_edit": (
            float(max(source_edit_ts)) if source_edit_ts else None
        ),
    }


def fixation_file(pid: str, task_no: int) -> Path:
    dp = disk_pid(pid)
    return DATA / dp / f"t{task_no}" / f"{dp}_t{task_no}_fixation_filtered.csv"


# Union of the fixation columns the two share computations need. The file is
# read once with this set and the resulting frame is passed to both, so each
# large per-task fixation CSV is read a single time per task.
FIXATION_USECOLS = [
    "timestamp",
    "fixation_group_id",
    "fixation_group_duration",
    "on_method",
    "AOI",
]


def load_fixations(pid: str, task_no: int) -> pd.DataFrame | None:
    """Read the per-task fixation_filtered.csv once, with the union of columns
    both share computations need. Returns the frame with rows lacking a
    ``fixation_group_id`` dropped, or None if the file is missing or holds no
    fixations.
    """
    path = fixation_file(pid, task_no)
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=FIXATION_USECOLS, low_memory=False)
    df = df.dropna(subset=["fixation_group_id"])
    if df.empty:
        return None
    return df


def buggy_method_share(
    df: pd.DataFrame, t_last_edit: float
) -> tuple[float | None, float | None]:
    """Return (window share, whole-task share) of fixation-time on the buggy
    method, from a per-sample fixation frame. Uses one
    fixation_group_duration per fixation_group_id; on_method for a group is
    True if any sample in the group is True.
    """
    # on_method may be string 'True'/'False' or bool; coerce.
    om = df["on_method"]
    if om.dtype == object:
        om = om.map({"True": True, "False": False, True: True, False: False})
    df = df.assign(on_method=om)

    def share(sub: pd.DataFrame) -> float | None:
        if sub.empty:
            return None
        grp = sub.groupby("fixation_group_id").agg(
            dur=("fixation_group_duration", "first"),
            on=("on_method", "max"),  # any True
        )
        total = grp["dur"].sum()
        if total <= 0:
            return None
        on_dur = grp.loc[grp["on"] == True, "dur"].sum()  # noqa: E712
        return float(on_dur / total)

    whole = share(df)
    window = share(df[df["timestamp"] >= t_last_edit])
    return window, whole


def aoi_shares(
    df: pd.DataFrame, t_last_edit: float, real_dur_min: float
) -> dict[str, float | None]:
    """Source-code and Patch fixation-time shares, window and whole-task, plus
    task and window durations.

    The window (last source edit -> task end) is defined on the per-sample
    fixation frame's MILLISECOND timestamps, which are the IDE epoch clock. This
    is robust to the raw-gaze MINUTE clock being glitched.

    Durations use the REAL task duration (real_dur_min == time_minutes), NOT
    max(end_min) from the raw gaze stream. window_dur_min is the time from the
    last edit to the last in-window fixation on the IDE clock, clipped to
    ``[0, real_dur_min]`` so a glitched span cannot leak in and a window can
    never exceed the real task.
    """
    out: dict[str, float | None] = {
        "source_window": None,
        "source_whole": None,
        "patch_window": None,
        "patch_whole": None,
        "task_dur_min": float(real_dur_min),
        "window_dur_min": None,
    }

    def share(sub: pd.DataFrame, aoi: str) -> float | None:
        if sub.empty:
            return None
        # majority AOI per fixation group, weighted by group duration
        grp = sub.groupby("fixation_group_id").agg(
            dur=("fixation_group_duration", "first"),
            aoi=("AOI", lambda s: s.dropna().mode().iloc[0]
                 if not s.dropna().empty else np.nan),
        )
        total = grp["dur"].sum()
        if total <= 0:
            return None
        return float(grp.loc[grp["aoi"] == aoi, "dur"].sum() / total)

    win = df[df["timestamp"] >= t_last_edit]
    out["source_window"] = share(win, "Source Code")
    out["source_whole"] = share(df, "Source Code")
    out["patch_window"] = share(win, "Patch")
    out["patch_whole"] = share(df, "Patch")

    # Window duration on the IDE clock: from last edit to the last fixation,
    # capped at the real task duration. The per-sample timestamps are the IDE
    # epoch, so (max_ts - t_last_edit) is the post-edit span in ms.
    if not win.empty:
        win_ms = float(win["timestamp"].max() - t_last_edit)
        win_min = max(win_ms / 60000.0, 0.0)
        out["window_dur_min"] = float(min(win_min, real_dur_min))
    else:
        out["window_dur_min"] = 0.0
    return out


def main() -> None:
    # The task list, conditions, correctness, gaze presence, and per-task
    # durations all come from the canonical timing CSV. A task is included iff it
    # has a resolvable IDE log (direct or merged parts); a task has gaze iff its
    # Source Code fixation count is present.
    timing = pd.read_csv(TIMING_CSV)
    real_dur = {
        (r.PID, int(r.task_no)): float(r.time_minutes)
        for r in timing.itertuples()
        if pd.notna(r.time_minutes)
    }
    # has_gaze lookup, by the spaced column name (not accessible via itertuples).
    has_gaze_by_task = {
        (row["PID"], int(row["task_no"])): pd.notna(row["Source Code_fixation_count"])
        for _, row in timing.iterrows()
    }

    rows = []
    skipped_no_log = []
    skipped_unparseable = []
    skipped_empty_log = []
    for r in timing.itertuples():
        pid, task_no = r.PID, int(r.task_no)
        # Inclusion criterion: a resolvable IDE log. resolve_logs returns the
        # direct t<n>/ide_tracking.xml when present, otherwise the t<n>_part*
        # logs, which parse_task merges. This is the same log set the other IDE
        # findings use, so the validation task set matches them.
        logs = resolve_logs(pid, task_no)
        if not logs:
            skipped_no_log.append((pid, task_no))
            continue
        try:
            feat = parse_task(logs)
        except ET.ParseError:
            skipped_unparseable.append((pid, task_no))
            continue
        t0 = feat["t0"]
        # t0 (the first event timestamp) is None only for an empty log. An empty
        # or malformed log is skipped rather than crashing the build.
        if t0 is None:
            skipped_empty_log.append((pid, task_no))
            continue
        t_last = feat["t_last_source_edit"]
        has_window = t_last is not None
        has_gaze = has_gaze_by_task[(pid, task_no)]

        rec: dict[str, object] = {
            "PID": pid,
            "task_no": task_no,
            "condition": r.condition,
            "bug": r.bug,
            "correct": (r.correct == "Y"),
            "has_gaze": has_gaze,
            "has_window": bool(has_window),
            "t0": t0,
            "t_last_source_edit": t_last,
        }

        # Read the per-task fixation file ONCE, with the union of columns both
        # the buggy-method share and the AOI shares need, and pass the frame to
        # both. fx is None when the file is missing or has no fixations; both
        # share computations then yield None, matching a file-absent task.
        key = (pid, task_no)
        rdur = real_dur.get(key)
        fx = None
        if has_window and has_gaze:
            fx = load_fixations(pid, task_no)

        # Buggy-method share (per-sample) needs a window, gaze, and fixations.
        if fx is not None:
            bm_win, bm_whole = buggy_method_share(fx, float(t_last))
        else:
            bm_win, bm_whole = (None, None)
        rec["buggy_window"] = bm_win
        rec["buggy_whole"] = bm_whole

        # Source/Patch AOI shares + durations, on the IDE millisecond clock.
        # window_start_min is the last-edit offset on the IDE clock (for record).
        rec["window_start_min"] = (
            (float(t_last) - float(t0)) / 60000.0 if has_window else np.nan
        )
        if has_window and has_gaze and rdur is not None:
            if fx is not None:
                rec.update(aoi_shares(fx, float(t_last), rdur))
            else:
                # File absent or empty: shares are None, durations fall back to
                # the file-absent path of aoi_shares (task_dur_min set, the rest
                # None).
                rec.update(
                    {
                        "source_window": None,
                        "source_whole": None,
                        "patch_window": None,
                        "patch_whole": None,
                        "task_dur_min": float(rdur),
                        "window_dur_min": None,
                    }
                )
        else:
            for k in [
                "source_window",
                "source_whole",
                "patch_window",
                "patch_whole",
                "window_dur_min",
            ]:
                rec[k] = None
            rec["task_dur_min"] = rdur
        rows.append(rec)

    cols = [
        "PID", "task_no", "condition", "bug", "correct", "has_gaze",
        "has_window", "t0", "t_last_source_edit", "buggy_window", "buggy_whole",
        "window_start_min", "source_window", "source_whole", "patch_window",
        "patch_whole", "task_dur_min", "window_dur_min",
    ]
    out = pd.DataFrame(rows)[cols]
    out.to_csv(OUT, index=False)
    print(f"Rows written: {len(out)}   (wrote {OUT})")
    print("Per-condition N:")
    print(out.groupby("condition").size().to_string())
    print(f"has_window True: {int(out['has_window'].sum())}")
    print(f"has_gaze True:   {int(out['has_gaze'].sum())}")
    if skipped_no_log:
        print(f"  skipped (no IDE log): {skipped_no_log}")
    if skipped_unparseable:
        print(f"  skipped (unparseable): {skipped_unparseable}")
    if skipped_empty_log:
        print(f"  skipped (empty log): {skipped_empty_log}")


if __name__ == "__main__":
    main()
