"""Build the test-run-rate input.

This is the IDE companion to the fix-validation finding. The motivating
question is whether developers run the tests proportionally more often in some
conditions, measured as test runs PER MINUTE of task time (a rate).

Per-task it emits the count of test-execution ACTION events (the ``TEST_RUN``
set) read from the IntelliJ event stream (``ide_tracking.xml``), together with
the task duration and the join keys. The test_run_rate model consumes
``n_test_run`` with an ``offset(log(duration_min))`` for the rate, plus
``PID``, ``task_no``, ``condition``, ``bug``, ``correct``.

Duration basis. The rate denominator is ``time_minutes`` from
``timing_correctness_data.csv``, written here as ``duration_min``. This is the
SAME basis ide_navigation uses for its offset, so the test-run rate is directly
comparable to the navigation rate. The debugger builder instead derives an
IDE-event-span duration; that basis is not used here, for comparability with
the navigation rate.

How the IDE log encodes the events this reads:

  - Test execution events are ``<action>`` elements whose ``event``/``id`` key
    is in the ``TEST_RUN`` set (= {"Run","Rerun","RunClass","RunAnything"}).
    Launching the debugger (Debug / DebugClass) is debugger use, not a plain
    test run, and is excluded by that taxonomy.
  - The six P*_0 participants write some actions with ``id="..."`` instead of
    ``event="..."``; both attributes are checked when scanning actions, via
    ``iter_ide_events``.

Task set. Every task in ``patchwork_analysis/timing_correctness_data.csv`` with
a resolvable ``ide_tracking.xml``. Split tasks (``t<n>_part1`` / ``t<n>_part2``)
are merged across parts. ``condition``, ``bug``, and ``correct`` come from the
timing CSV. Tasks with no resolvable log are skipped (and printed); a task whose
log will not parse is skipped on ``ET.ParseError`` (and printed).

Note that you probably don't need to run this! The csv it produces from the raw
IDE events data is already in this directory.

Run (from the repo root, with a Python 3.12+ that has the requirements):
    python3 patchwork_analysis/paper_results/06_test_run_rate/build_test_run_rate.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import TEST_RUN, TIMING_CSV, iter_ide_events, resolve_logs

HERE = Path(__file__).resolve().parent
OUT = HERE / "test_run_rate_input.csv"


def count_test_runs(xml_paths: list[Path]) -> int:
    """Number of TEST_RUN action events across all parts of one task.

    Uses iterparse (via iter_ide_events) to keep memory flat over the 9-14 MB
    logs. Only ``<action>`` elements whose resolved key is in ``TEST_RUN`` are
    counted.
    """
    n = 0
    for xml_path in xml_paths:
        for kind, attrs in iter_ide_events(xml_path):
            if kind == "action" and attrs["key"] in TEST_RUN:
                n += 1
    return n


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
            n_test_run = count_test_runs(logs)
        except ET.ParseError:
            skipped_unparseable.append((pid, tno))
            continue

        duration_min = float(r["time_minutes"])

        rows.append({
            "PID": pid, "task_no": tno, "bug": r["bug"],
            "condition": r["condition"], "correct": r["correct"],
            "has_gaze": pd.notna(r["Source Code_fixation_count"]),
            "duration_min": round(duration_min, 4),
            "n_test_run": n_test_run,
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

    rate = out["n_test_run"] / out["duration_min"]
    print("\nMean test runs per minute by condition:")
    print(rate.groupby(out["condition"]).mean().round(3).to_string())
    print("\nMean n_test_run by condition:")
    print(out.groupby("condition")["n_test_run"].mean().round(2).to_string())
    print("\nMedian n_test_run by condition:")
    print(out.groupby("condition")["n_test_run"].median().round(1).to_string())
    print(f"\nn_test_run range: {out['n_test_run'].min()}"
          f"-{out['n_test_run'].max()}")


if __name__ == "__main__":
    main()
