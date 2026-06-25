"""Build the VALIDATION-WINDOW model input from primary data.

Note that you probably don't need to run this! The csv it produces from the raw
IDE-event and gaze fixation data is already in this directory.

The validation window for a task runs from the LAST source edit
(``t_last_source_edit``) to the end of the task. ``t_last_source_edit`` is the
timestamp of the last edit to a SOURCE ``.java`` file in the IDE event stream;
``t0`` is the task start (the first IDE event). Within that post-fix window we
measure four gaze quantities and compare each to its whole-task counterpart.

This builder is self-contained. It combines two stages that upstream lived in
separate scripts (``parse_ide_events.py`` for the IDE boundary, then
``validation_window.py`` for the gaze shares). It reads only primary data.

Inputs (all local, primary data)
---------------------------------
1. The TASK LIST, condition/bug/correct, gaze presence, and per-task durations
   from ``patchwork_analysis/timing_correctness_data.csv``. The analyzed task set
   is every task whose ``t<n>/ide_tracking.xml`` exists on disk. ``has_gaze`` is
   true iff the task's ``Source Code_fixation_count`` is present. ``time_minutes``
   is the authoritative task span, also used to cap ``window_dur_min``.
2. The per-task IDE event logs
   ``patchwork_data/<disk_pid>/t<task_no>/ide_tracking.xml``. From each we derive
   ``t0`` (first event timestamp) and ``t_last_source_edit`` (last source-edit
   timestamp). ``has_window`` flags tasks with at least one source edit.
3. The per-task FIXATION FILES
   ``patchwork_data/<disk_pid>/t<task_no>/<disk_pid>_t<task_no>_fixation_filtered.csv``
   for the AOI fixation-time shares within the window and over the whole task.

Edit detection (ported verbatim from parse_ide_events.py)
---------------------------------------------------------
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
on the fixation timeline. NO clock recovery is applied (matching the upstream
producer ``validation_window.py``); the window is the raw millisecond comparison
``timestamp >= t_last_source_edit``. ``window_dur_min`` is the span from the last
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
from patchwork_io import DATA, TIMING_CSV, disk_pid, is_source

HERE = Path(__file__).resolve().parent
OUT = HERE / "validation_window_model_input.csv"

# --- IDE event taxonomy (ported verbatim from parse_ide_events.py) -----------
# Only the edit-related sets matter for t_last_source_edit; the others are
# retained for fidelity but unused here.
EDIT_ACTIONS = {
    "EditorPaste", "EditorBackSpace", "EditorDeleteToWordStart", "EditorCut",
    "EditorEnter", "SaveAll", "CommentByLineComment", "EditorChooseLookupItem",
    "EditorChooseLookupItemReplace",
}

def parse_task(xml_path: Path) -> dict[str, float | int | None]:
    """Stream the actions + typing elements; return (t0, t_last_source_edit).

    Ported from parse_ide_events.parse_task, reduced to the two timestamps the
    validation window needs. Uses iterparse to keep memory flat over the
    9-14 MB logs. ``t0`` is the earliest event timestamp; ``t_last_source_edit``
    is the latest source-edit timestamp (None if no source edit occurred).
    """
    timestamps: list[int] = []
    source_edit_ts: list[int] = []

    for _event, elem in ET.iterparse(xml_path, events=("end",)):
        tag = elem.tag
        if tag == "action":
            ev = elem.get("event", "")
            ts = elem.get("timestamp")
            path = elem.get("path", "") or ""
            if ts is not None:
                ts = int(ts)
                timestamps.append(ts)
                if ev == "ChangesView.ApplyPatch":
                    # Applying the suggested patch via the IntelliJ Apply-Patch
                    # dialog changes source. The action's path is typically
                    # /suggested.patch, so do NOT gate on is_source(path); count
                    # it unconditionally as a source edit.
                    source_edit_ts.append(ts)
                elif ev in EDIT_ACTIONS:
                    if is_source(path):
                        source_edit_ts.append(ts)
            elem.clear()
        elif tag == "typing":
            ts = elem.get("timestamp")
            path = elem.get("path", "") or ""
            if ts is not None:
                ts = int(ts)
                timestamps.append(ts)
                if is_source(path):
                    source_edit_ts.append(ts)
            elem.clear()

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


def buggy_method_share(
    pid: str, task_no: int, t_last_edit: float
) -> tuple[float | None, float | None]:
    """Return (window share, whole-task share) of fixation-time on the buggy
    method, from the per-sample fixation_filtered.csv. Uses one
    fixation_group_duration per fixation_group_id; on_method for a group is
    True if any sample in the group is True. Returns (None, None) if the file
    is missing or has no fixations.
    """
    path = fixation_file(pid, task_no)
    if not path.exists():
        return None, None
    df = pd.read_csv(
        path,
        usecols=[
            "timestamp",
            "fixation_group_id",
            "fixation_group_duration",
            "on_method",
        ],
        low_memory=False,
    )
    df = df.dropna(subset=["fixation_group_id"])
    if df.empty:
        return None, None
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
    pid: str, task_no: int, t_last_edit: float, real_dur_min: float
) -> dict[str, float | None]:
    """Source-code and Patch fixation-time shares, window and whole-task, plus
    task and window durations.

    The window (last source edit -> task end) is defined on the per-sample
    fixation file's MILLISECOND timestamps, which are the IDE epoch clock. This
    is robust to the raw-gaze MINUTE clock being glitched.

    Durations use the REAL task duration (real_dur_min == time_minutes), NOT
    max(end_min) from the raw gaze stream. window_dur_min is the time from the
    last edit to the last in-window fixation on the IDE clock, clipped to
    ``[0, real_dur_min]`` so a glitched span cannot leak in and a window can
    never exceed the real task.
    """
    path = fixation_file(pid, task_no)
    out: dict[str, float | None] = {
        "source_window": None,
        "source_whole": None,
        "patch_window": None,
        "patch_whole": None,
        "task_dur_min": float(real_dur_min),
        "window_dur_min": None,
    }
    if not path.exists():
        return out
    df = pd.read_csv(
        path,
        usecols=["timestamp", "fixation_group_id", "fixation_group_duration", "AOI"],
        low_memory=False,
    )
    df = df.dropna(subset=["fixation_group_id"])
    if df.empty:
        return out

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
    # durations all come from the canonical timing CSV. A task has an IDE log iff
    # t<n>/ide_tracking.xml exists on disk (the inclusion criterion); a task has
    # gaze iff its Source Code fixation count is present.
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
    for r in timing.itertuples():
        pid, task_no = r.PID, int(r.task_no)
        xml = DATA / disk_pid(pid) / f"t{task_no}" / "ide_tracking.xml"
        if not xml.exists():
            continue  # no IDE log -> not in the validation-window analysis
        feat = parse_task(xml)
        t0 = feat["t0"]
        # Every analyzed task has IDE events, so t0 (the first event timestamp) is
        # always set; t0 is None only for an empty log, which does not occur here.
        assert t0 is not None
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

        # Buggy-method share (per-sample) needs a window and gaze.
        if has_window and has_gaze:
            bm_win, bm_whole = buggy_method_share(pid, task_no, float(t_last))
        else:
            bm_win, bm_whole = (None, None)
        rec["buggy_window"] = bm_win
        rec["buggy_whole"] = bm_whole

        # Source/Patch AOI shares + durations, on the IDE millisecond clock.
        key = (pid, task_no)
        rdur = real_dur.get(key)
        # window_start_min is the last-edit offset on the IDE clock (for record).
        rec["window_start_min"] = (
            (float(t_last) - float(t0)) / 60000.0 if has_window else np.nan
        )
        if has_window and has_gaze and rdur is not None:
            rec.update(aoi_shares(pid, task_no, float(t_last), rdur))
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


if __name__ == "__main__":
    main()
