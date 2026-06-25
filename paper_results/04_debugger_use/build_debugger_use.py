"""Build the debugger-use input for the debugger_use finding.

This emits one per-task row of IDE-event counts and ordering flags, read from
the IntelliJ event stream (``ide_tracking.xml``) for each participant-task. The
debugger_use model consumes ``n_debugger`` (binarized to "any debugger use")
together with the join keys ``PID``, ``task_no``, ``condition``, ``bug``. The
remaining columns reproduce the schema of the input the model historically read,
so the model runs unchanged.

Note that you probably don't need to run this! The csv it produces from the raw
IDE events data is already in this directory.

How the IDE log encodes the events this reads:

  - Test execution, debugger, edit, navigation, undo, and apply-patch events are
    ``<action>`` elements carrying an ``event``/``id`` attribute and a
    ``timestamp``. Edits also arrive as ``<typing>`` elements with a ``path``.
  - The six P*_0 participants write some actions with ``id="..."`` instead of
    ``event="..."``; both attributes are checked when scanning actions.
  - Edits are tagged source vs test by ``path``, requiring a real project
    ``.java`` file and excluding JDK / library / archive paths.
  - Applying the suggested patch through the IntelliJ Apply-Patch dialog
    (``ChangesView.ApplyPatch``) changes source; its path is the patch
    pseudo-file, so it is counted as a source edit unconditionally and tracked
    separately as ``n_apply_patch``.

Task set. Every task in ``patchwork_analysis/timing_correctness_data.csv`` with a
resolvable ``ide_tracking.xml``. Split tasks (``t<n>_part1`` / ``t<n>_part2``)
are merged across parts. ``condition``, ``bug``, and ``correct`` come from the
timing CSV.

Run: python3 patchwork_analysis/paper_results/04_debugger_use/build_debugger_use.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import TIMING_CSV, is_source, is_test, resolve_logs

HERE = Path(__file__).resolve().parent
OUT = HERE / "ide_events.csv"

TEST_RUN = {"Run", "Rerun", "RunClass", "RunAnything", "DebugClass"}
DEBUGGER = {"StepOver", "StepInto", "StepOut", "Resume", "ToggleLineBreakpoint",
            "RunToCursor", "ViewBreakpoints", "AddConditionalBreakpoint"}
EDIT_ACTIONS = {"EditorPaste", "EditorBackSpace", "EditorDeleteToWordStart",
                "EditorCut", "EditorEnter", "SaveAll", "CommentByLineComment",
                "EditorChooseLookupItem", "EditorChooseLookupItemReplace"}
NAV = {"GotoImplementation", "GotoDeclaration", "GotoTypeDeclaration", "Find",
       "FindInPath", "SearchEverywhere", "ViewSource", "Back", "Forward",
       "GotoLine"}
UNDO = {"$Undo", "$Redo"}

COUNT_KEYS = ["n_test_run", "n_debugger", "n_source_edit", "n_test_edit",
              "n_navigation", "n_undo", "n_apply_patch"]


def parse_logs(xml_paths: list[Path]) -> dict:
    """Stream actions + typing elements across all parts; return per-task counts,
    first-occurrence timestamps, and the IDE-session duration.

    Uses iterparse to keep memory flat over the 9-14 MB logs.
    """
    counts = {k: 0 for k in COUNT_KEYS}
    timestamps: list[int] = []
    run_ts: list[int] = []
    source_edit_ts: list[int] = []

    for xml_path in xml_paths:
        for _event, elem in ET.iterparse(xml_path, events=("end",)):
            tag = elem.tag
            if tag == "action":
                # P*_0 participants use id="..."; everyone else event="...".
                ev = elem.get("event")
                if ev is None:
                    ev = elem.get("id", "")
                ts = elem.get("timestamp")
                path = elem.get("path", "") or ""
                if ts is not None:
                    ts = int(ts)
                    timestamps.append(ts)
                    if ev == "ChangesView.ApplyPatch":
                        counts["n_apply_patch"] += 1
                        counts["n_source_edit"] += 1
                        source_edit_ts.append(ts)
                    elif ev in TEST_RUN:
                        counts["n_test_run"] += 1
                        run_ts.append(ts)
                    elif ev in DEBUGGER:
                        counts["n_debugger"] += 1
                    elif ev in NAV:
                        counts["n_navigation"] += 1
                    elif ev in UNDO:
                        counts["n_undo"] += 1
                    elif ev in EDIT_ACTIONS:
                        if is_source(path):
                            counts["n_source_edit"] += 1
                            source_edit_ts.append(ts)
                        elif is_test(path):
                            counts["n_test_edit"] += 1
                elem.clear()
            elif tag == "typing":
                ts = elem.get("timestamp")
                path = elem.get("path", "") or ""
                if ts is not None:
                    ts = int(ts)
                    timestamps.append(ts)
                    if is_source(path):
                        counts["n_source_edit"] += 1
                        source_edit_ts.append(ts)
                    elif is_test(path):
                        counts["n_test_edit"] += 1
                elem.clear()
            else:
                elem.clear()

    if not timestamps:
        return {**counts, "t0": None, "duration_ide_min": None,
                "t_first_run": None, "t_first_source_edit": None,
                "t_last_source_edit": None, "t_first_run_after_edit": None}

    t0 = min(timestamps)
    t_first_run = min(run_ts) if run_ts else None
    t_first_source_edit = min(source_edit_ts) if source_edit_ts else None
    t_last_source_edit = max(source_edit_ts) if source_edit_ts else None
    t_first_run_after_edit = None
    if t_first_source_edit is not None:
        after = [t for t in run_ts if t > t_first_source_edit]
        t_first_run_after_edit = min(after) if after else None

    return {
        **counts,
        "t0": t0,
        "duration_ide_min": (max(timestamps) - t0) / 1000 / 60,
        "t_first_run": t_first_run,
        "t_first_source_edit": t_first_source_edit,
        "t_last_source_edit": t_last_source_edit,
        "t_first_run_after_edit": t_first_run_after_edit,
    }


def order_flags(row: dict) -> dict:
    """Derive ordering outcomes. 'never edited / never ran' are their own
    categories, not silently treated as ordering failures."""
    run = row["t_first_run"]
    edit = row["t_first_source_edit"]
    run_after = row["t_first_run_after_edit"]
    return {
        "ran": run is not None,
        "edited_source": edit is not None,
        "reproduce_first": (run is not None and edit is not None and run < edit),
        "validated_after_edit": run_after is not None,
        "full_order_ok": (run is not None and edit is not None
                          and run < edit and run_after is not None),
    }


def main() -> None:
    tim = pd.read_csv(TIMING_CSV)

    rows = []
    skipped_no_log = []
    skipped_unparseable = []
    for _, r in tim.iterrows():
        pid, tno = r["PID"], int(r["task_no"])
        logs = resolve_logs(pid, tno)
        if not logs:
            skipped_no_log.append((pid, tno))
            continue
        try:
            feat = parse_logs(logs)
        except ET.ParseError:
            skipped_unparseable.append((pid, tno))
            continue
        feat.update(order_flags(feat))
        rows.append({
            "PID": pid, "task_no": tno, "condition": r["condition"],
            "bug": r["bug"], "correct": r["correct"],
            "has_gaze": pd.notna(r["Source Code_fixation_count"]),
            **feat,
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"wrote {OUT}  ({len(out)} tasks)")
    if skipped_no_log:
        print(f"  skipped (no IDE log): {skipped_no_log}")
    if skipped_unparseable:
        print(f"  skipped (unparseable): {skipped_unparseable}")
    print()
    print("any debugger use by condition:")
    used = (out["n_debugger"] > 0).astype(int)
    print(used.groupby(out["condition"]).mean().round(3).to_string())


if __name__ == "__main__":
    main()
