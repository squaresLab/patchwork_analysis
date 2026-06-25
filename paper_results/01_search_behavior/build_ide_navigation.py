"""Build the IDE-event "search" input.

This code setups the analysis of file navigation/search events. The analysis
normalizes for task time.  

Note that you probably don't need to run this! The csv it produces from the raw
IDE events data is already in this directory.

Two per-task measures are emitted.

  - ``n_navigation``: count of code-navigation / search ACTION events (the
    ``NAV`` set).
  - ``n_files_opened``: count of DISTINCT PROJECT ``.java`` files opened, read
    from ``<archive remark="fileOpened" .../>`` elements. Both source and test
    ``.java`` files are counted, to match the gaze ``num_files_looked_at`` (which
    counts every fixated file, not source-only). Non-project paths are dropped.

How the IDE log encodes the events this reads:

  1. ``fileOpened`` is an ``<archive id="fileArchive" remark="fileOpened"
     path="..." timestamp="..."/>`` element, NOT an ``<action>``.
  2. Some fileOpened paths are tagged non-code in the remark, e.g.
     ``remark="fileOpened | NotCodeFile | Fail"`` for ``/suggested.patch`` and
     library ``.class`` members. For files-explored, NotCodeFile remarks,
     ``/suggested.patch``, ``/Diff``, and library paths are all dropped (via the
     ``is_project_java`` helper from ``patchwork_io``).
  3. Switcher and FindUsages are clean action events.
  4. The six P*_0 participants write some actions with ``id="..."`` instead of
     ``event="..."``; both attributes are checked when scanning actions.

Task set. Every task in ``patchwork_analysis/timing_correctness_data.csv`` with a
resolvable IDE log. Split tasks (``t<n>_part1`` / ``t<n>_part2``) are merged
across parts. Task duration for the model offset is the ``time_minutes`` column
of ``timing_correctness_data.csv``.

Run (from the repo root, with a Python 3.12+ that has the requirements):
    python3 patchwork_analysis/paper_results/01_search_behavior/build_ide_navigation.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import TIMING_CSV, is_project_java, resolve_logs

HERE = Path(__file__).resolve().parent
TIMING = TIMING_CSV
OUT = HERE / "ide_navigation_input.csv"


# Code-navigation / search action events.
NAV = {
    "GotoImplementation", "GotoDeclaration", "GotoTypeDeclaration", "Find",
    "FindInPath", "SearchEverywhere", "ViewSource", "Back", "Forward",
    "GotoLine", "FindUsages", "Switcher",
}

# fileOpened paths that are not project code even when the remark is plain
# "fileOpened" (defensive; the NotCodeFile remark already tags these).
NON_CODE_PATHS = {"/suggested.patch", "/Diff"}


def _is_opened_project_java(path: str, remark: str) -> bool:
    """True if a fileOpened archive element refers to a distinct project file.

    Drops NotCodeFile-tagged remarks, the patch/diff pseudo-files, and any
    library / non-project path (via is_project_java). Counts both source and
    test .java files.
    """
    if "NotCodeFile" in remark:
        return False
    if path in NON_CODE_PATHS:
        return False
    return is_project_java(path)


def parse_logs(xml_paths: list[Path]) -> dict:
    """Stream the action + fileOpened-archive elements across all parts.

    Uses iterparse to keep memory flat over the 9-14 MB logs. Returns the three
    measures plus the sorted distinct opened-file list.
    """
    n_nav = 0
    opened: set[str] = set()

    for xml_path in xml_paths:
        for _event, elem in ET.iterparse(xml_path, events=("end",)):
            tag = elem.tag
            if tag == "action":
                # P*_0 participants use id="..."; everyone else event="...".
                key = elem.get("event")
                if key is None:
                    key = elem.get("id", "")
                if key in NAV:
                    n_nav += 1
                elem.clear()
            elif tag == "archive":
                remark = elem.get("remark", "") or ""
                if remark.startswith("fileOpened"):
                    path = elem.get("path", "") or ""
                    if _is_opened_project_java(path, remark):
                        opened.add(path)
                elem.clear()
            else:
                elem.clear()

    return {
        "n_navigation": n_nav,
        "n_files_opened": len(opened),
        "opened_files": "|".join(sorted(opened)),
    }


def main() -> None:
    # Read the canonical task list directly. bug, condition, correct, and the
    # task duration (time_minutes) all live here. The task set is every row with
    # a resolvable IDE log.
    tim = pd.read_csv(TIMING)

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

        duration_min = float(r["time_minutes"])

        rows.append({
            "PID": pid, "task_no": tno, "bug": r["bug"],
            "condition": r["condition"], "correct": r["correct"],
            "duration_min": round(duration_min, 4),
            "n_navigation": feat["n_navigation"],
            "n_files_opened": feat["n_files_opened"],
            "opened_files": feat["opened_files"],
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"Rows written: {len(out)}   (wrote {OUT})")
    if skipped_no_log:
        print(f"  skipped (no IDE log): {skipped_no_log}")
    if skipped_unparseable:
        print(f"  skipped (unparseable): {skipped_unparseable}")

    print("\nPer-condition N:")
    print(out.groupby("condition").size().to_string())

    print("\nMean by condition:")
    print(
        out.groupby("condition")[["n_navigation", "n_files_opened"]]
        .mean().round(2).to_string()
    )
    print("\nMedian by condition:")
    print(
        out.groupby("condition")[["n_navigation", "n_files_opened"]]
        .median().round(1).to_string()
    )

    print("\nRaw per-condition distinct-files and navigation distributions:")
    for cond, g in out.groupby("condition"):
        print(f"  {cond}:")
        print(f"    n_files_opened: {sorted(g['n_files_opened'].tolist())}")
        print(f"    n_navigation:   {sorted(g['n_navigation'].tolist())}")

    print(f"\nn_files_opened range: {out['n_files_opened'].min()}"
          f"-{out['n_files_opened'].max()}")


if __name__ == "__main__":
    main()
