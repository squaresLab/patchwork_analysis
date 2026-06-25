"""Shared IO and path helpers for the paper_results build scripts.

The build scripts under ``paper_results`` all need the same things, so those
helpers live here and each build script imports them rather than redefining
them. The helpers fall into these categories.

  - Path / PID / project-Java: the repo root, the gaze-data directory, the
    timing CSV path, the study-PID-to-disk-name mapping, and the project-Java
    path filtering.
  - Source/test path classification: ``is_source`` / ``is_test`` over the
    project source and test roots, matched as contiguous path segments.
    ``is_unbucketed_project_java`` names the project Java files that match no
    source or test root.
  - IDE-log resolution: ``resolve_logs`` finds the ide_tracking.xml file(s) for
    a (PID, task), merging split parts.
  - IDE event reading: ``iter_ide_events`` streams the action/typing/archive
    elements of one ide_tracking.xml, resolving each action's ``event=``/``id=``
    key. The action-key taxonomy sets (``NAV``, ``TEST_RUN``, ``DEBUGGER``,
    ``EDIT_ACTIONS``, ``UNDO``, ``APPLY_ACTION``) live here too.
  - Gaze clock recovery: ``recover_ms_clock`` undoes tracker-clock jumps in the
    per-sample millisecond timestamps.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd


def find_root() -> Path:
    """Repo root. PATCHWORK_ROOT env var if set, else the parent of the nearest
    ancestor directory named 'patchwork_analysis'."""
    env = os.environ.get("PATCHWORK_ROOT")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if parent.name == "patchwork_analysis":
            return parent.parent
    raise RuntimeError(
        "Could not locate a 'patchwork_analysis' directory above "
        f"{__file__}; set PATCHWORK_ROOT to the repo root."
    )


ROOT = find_root()
DATA = Path(os.environ.get("PATCHWORK_DATA", ROOT / "patchwork_data"))
TIMING_CSV = ROOT / "patchwork_analysis" / "timing_correctness_data.csv"


def disk_pid(pid: str) -> str:
    """Study PID (P3_0) to on-disk directory name (P3-0)."""
    return pid.replace("_", "-")


def _is_library_path(path: str) -> bool:
    """True for JDK / library / archive paths that are not project files.

    Excludes absolute drive-letter paths (e.g. C:/Users/.../temurin.../
    lib/src.zip!/...), archive members (`src.zip!`, `.jar!`), and compiled
    `.class` files. These are JDK internals or dependencies a participant
    navigated into, never edits of the project under repair.
    """
    if not path:
        return True
    if len(path) >= 2 and path[1] == ":":  # drive-letter absolute (C:/...)
        return True
    if "src.zip!" in path or ".jar!" in path:
        return True
    if path.endswith(".class"):
        return True
    return False


def is_project_java(path: str) -> bool:
    """A real, editable project Java file (not a JDK/library path, not .backup)."""
    return path.endswith(".java") and not _is_library_path(path)


# ---------------------------------------------------------------------------
# Source/test path classification
# ---------------------------------------------------------------------------
# Project source/test roots, derived from the actual logs. Layouts differ by
# project: commons-math / commons-lang use the Maven /src/main & /src/test
# layout; jfreechart uses /source & /tests. The /chart12/{source,tests}
# variants are folded in.
#
# A root matches a path when its segments appear as a contiguous run of the
# path's slash-delimited segments, so "src/main" matches /lang10/src/main/java/X
# (the run src, main appears in order) but not a path where "main" is part of a
# larger token. A root like /tests/ that is one segment matches that segment
# anywhere in the path. Test roots are checked before source roots so a test
# file under a shared parent is never bucketed as source.
SOURCE_ROOTS = ("/src/main/", "/source/", "/chart12/source/")
TEST_ROOTS = ("/src/test/", "/tests/", "/chart12/tests/")


def _segments(path: str) -> list[str]:
    """The non-empty slash-delimited segments of ``path``."""
    return [seg for seg in path.split("/") if seg]


_SOURCE_RUNS = tuple(_segments(root) for root in SOURCE_ROOTS)
_TEST_RUNS = tuple(_segments(root) for root in TEST_ROOTS)


def _has_segment_run(segments: list[str], run: list[str]) -> bool:
    """True when ``run`` appears as a contiguous subsequence of ``segments``."""
    n = len(run)
    if n == 0:
        return False
    return any(segments[i : i + n] == run for i in range(len(segments) - n + 1))


def is_test(path: str) -> bool:
    """True for a project Java test file. The path is a project Java file
    (``is_project_java``) whose segments contain a TEST_ROOTS run."""
    if not is_project_java(path):
        return False
    segments = _segments(path)
    return any(_has_segment_run(segments, run) for run in _TEST_RUNS)


def is_source(path: str) -> bool:
    """True for a project Java source file. The path is a project Java file
    (``is_project_java``) whose segments contain a SOURCE_ROOTS run and no
    TEST_ROOTS run. Test roots take precedence so a test file is never
    classified as source."""
    if not is_project_java(path):
        return False
    segments = _segments(path)
    if any(_has_segment_run(segments, run) for run in _TEST_RUNS):
        return False
    return any(_has_segment_run(segments, run) for run in _SOURCE_RUNS)


def is_unbucketed_project_java(path: str) -> bool:
    """True for a project Java file (``is_project_java``) that is neither
    ``is_source`` nor ``is_test``.

    A project Java file outside every SOURCE_ROOTS and TEST_ROOTS run falls
    here. ``is_source`` and ``is_test`` both return False for it, so the IDE
    builders do not count it as a source or test edit. This predicate names
    that fallthrough so a caller can detect a project file that matched no
    source or test root, which otherwise leaves no trace."""
    if not is_project_java(path):
        return False
    return not is_source(path) and not is_test(path)


# ---------------------------------------------------------------------------
# IDE-log resolution
# ---------------------------------------------------------------------------
def resolve_logs(pid: str, task_no: int) -> list[Path]:
    """All ide_tracking.xml files for a (PID, task), merging split parts.
    Returns the direct t<n>/ide_tracking.xml if present; otherwise any
    t<n>_part*/ide_tracking.xml parts. Empty if none exist."""
    base = DATA / disk_pid(pid)
    direct = base / f"t{task_no}" / "ide_tracking.xml"
    if direct.exists():
        return [direct]
    parts = sorted(base.glob(f"t{task_no}_part*/ide_tracking.xml"))
    return list(parts)


# ---------------------------------------------------------------------------
# IDE event stream reading
# ---------------------------------------------------------------------------
# The IntelliJ tracking log (ide_tracking.xml) records each IDE event as one
# element. Three element kinds matter for the build scripts:
#
#   - <action ... timestamp="..."/> is a named IDE command. Its key is in an
#     ``event="..."`` attribute for most participants. The six P*_0 participants
#     instead write the key in an ``id="..."`` attribute. ``iter_ide_events`` is
#     the single place that resolves this: it reads ``event`` and, when that
#     attribute is absent, reads ``id``. No action element carries both, so the
#     resolved key is unambiguous.
#   - <typing ... timestamp="..." path="..." character="..." line="..."
#     column="..."/> is a single character-level keystroke.
#   - <archive ... remark="..." path="..."/> records file-tree events such as a
#     file being opened (``remark="fileOpened"``).


def iter_ide_events(xml_path: Path | str) -> Iterator[tuple[str, dict]]:
    """Yield ``(kind, attrs)`` for each ``<action>``/``<typing>``/``<archive>``
    element in an ide_tracking.xml, in document order.

    ``kind`` is ``"action"``, ``"typing"``, or ``"archive"``. ``attrs`` is a
    dict of the fields callers need.

      - For actions, ``attrs["key"]`` is the event identifier resolved from
        ``event=`` or, when that attribute is absent (the six P*_0
        participants), from ``id=``. ``attrs`` also carries ``timestamp`` (int
        or None) and ``path`` (str, "" if absent).
      - For typing, ``attrs`` carries ``timestamp`` (int or None), ``path``
        (str), ``character`` (str), ``line`` (int, -1 if absent), and ``column``
        (int, -1 if absent).
      - For archive, ``attrs`` carries ``remark`` (str) and ``path`` (str).

    Uses ``iterparse`` with ``elem.clear()`` on every element to keep memory
    flat over the 9-14 MB logs.
    """
    for _event, elem in ET.iterparse(xml_path, events=("end",)):
        tag = elem.tag
        if tag == "action":
            key = elem.get("event")
            if key is None:
                key = elem.get("id", "")
            ts = elem.get("timestamp")
            yield (
                "action",
                {
                    "key": key,
                    "timestamp": int(ts) if ts is not None else None,
                    "path": elem.get("path", "") or "",
                },
            )
        elif tag == "typing":
            ts = elem.get("timestamp")
            yield (
                "typing",
                {
                    "timestamp": int(ts) if ts is not None else None,
                    "path": elem.get("path", "") or "",
                    "character": elem.get("character", ""),
                    "line": int(elem.get("line", -1)),
                    "column": int(elem.get("column", -1)),
                },
            )
        elif tag == "archive":
            yield (
                "archive",
                {
                    "remark": elem.get("remark", "") or "",
                    "path": elem.get("path", "") or "",
                },
            )
        elem.clear()


# ---------------------------------------------------------------------------
# IDE event taxonomy
# ---------------------------------------------------------------------------
# Which action keys fall into each category. One copy, shared by every build
# script that classifies IDE actions.

# Code-navigation / search actions. The superset includes FindUsages and
# Switcher.
NAV = {
    "GotoImplementation", "GotoDeclaration", "GotoTypeDeclaration", "Find",
    "FindInPath", "SearchEverywhere", "ViewSource", "Back", "Forward",
    "GotoLine", "FindUsages", "Switcher",
}

# Running the test suite. Launching the debugger (Debug / DebugClass) is debugger
# use, not a plain test run, so those keys live in DEBUGGER instead.
TEST_RUN = {"Run", "Rerun", "RunClass", "RunAnything"}

# Debugger use. Launching the debugger counts, not just active stepping.
DEBUGGER = {
    "StepOver", "StepInto", "StepOut", "Resume", "ToggleLineBreakpoint",
    "RunToCursor", "ViewBreakpoints", "AddConditionalBreakpoint",
    "DebugClass", "Debug",
}

# Edit actions. Keystroke-level edits arrive as <typing>; these are the
# coarser editor commands that also change a file.
EDIT_ACTIONS = {
    "EditorPaste", "EditorBackSpace", "EditorDeleteToWordStart", "EditorCut",
    "EditorEnter", "SaveAll", "CommentByLineComment", "EditorChooseLookupItem",
    "EditorChooseLookupItemReplace",
}

# Undo / redo.
UNDO = {"$Undo", "$Redo"}

# Applying the suggested patch through the IntelliJ Apply-Patch dialog.
APPLY_ACTION = "ChangesView.ApplyPatch"


# ---------------------------------------------------------------------------
# Fixation-group AOI reduction
# ---------------------------------------------------------------------------
# AOI label normalization, matching aggregate_gaze.py: both "Execution
# Inspection" and "Test and Run Output" map to "Test and Runtime Feedback".
def normalize_aoi(aoi_series: pd.Series) -> pd.Series:
    """Normalized AOI labels, matching the project's AOI aggregation
    (aggregate_gaze.py). "Execution Inspection" and "Test and Run Output" both
    become "Test and Runtime Feedback"."""
    return aoi_series.replace("Execution Inspection", "Test and Run Output").replace(
        "Test and Run Output", "Test and Runtime Feedback"
    )


def _mode_aoi(s: pd.Series) -> str:
    """Majority AOI over a fixation group's samples (most frequent value).

    ``pandas.Series.mode`` breaks ties alphabetically (it returns the sorted set
    of most-frequent values), so the assignment is deterministic regardless of
    sample order, matching aggregate_gaze.py's ``mode()[0]``."""
    return s.mode().iloc[0]


def fixation_groups(
    df: pd.DataFrame,
    extra_aggs: dict | None = None,
) -> pd.DataFrame:
    """Collapse a per-sample fixation_filtered frame to one row per fixation
    group, matching aggregate_gaze.py.

    The group's AOI is the per-group MAJORITY (mode) over the NORMALIZED AOI
    labels; its duration is the group's ``fixation_group_duration`` (constant
    within a group, take first); its timestamp is the mean sample timestamp.

    The input must carry ``fixation_group_id``, ``fixation_group_duration``,
    ``AOI``, and ``timestamp``. Rows without a ``fixation_group_id`` are
    dropped. The result is indexed by ``fixation_group_id`` with columns ``aoi``
    (normalized majority label), ``dur_ms``, and ``ts``, plus any columns named
    in ``extra_aggs`` (a mapping of output column to ``(source_col, agg)``).
    """
    work = df.dropna(subset=["fixation_group_id"]).copy()
    work["AOI"] = normalize_aoi(work["AOI"])
    aggs = {
        "dur_ms": ("fixation_group_duration", "first"),
        "ts": ("timestamp", "mean"),
    }
    if extra_aggs:
        aggs.update(extra_aggs)
    grp = work.groupby("fixation_group_id").agg(**aggs)
    grp["aoi"] = work.groupby("fixation_group_id")["AOI"].agg(_mode_aoi)
    return grp


# ---------------------------------------------------------------------------
# Gaze clock recovery
# ---------------------------------------------------------------------------
# A within-task gap larger than this many minutes cannot be a real pause: the
# task cap is 25 min. Used to detect tracker-clock jumps.
GLITCH_GAP_MIN = 30.0


def recover_ms_clock(
    df: pd.DataFrame,
    ts_col: str = "timestamp",
    end_col: str | None = None,
    max_jumps: int = 5,
) -> pd.DataFrame:
    """Single-jump recovery for per-sample millisecond timestamps.

    Each pass sorts ``ts_col``, finds the largest gap between consecutive
    samples, and when that gap exceeds GLITCH_GAP_MIN minutes shifts every
    sample at or after the gap back by the gap width, undoing one tracker-clock
    jump. Up to ``max_jumps`` passes run; the loop stops once the largest
    remaining gap is within threshold. ``end_col``, when given and present,
    is shifted by the same offset as ``ts_col``.

    GLITCH_GAP_MIN minutes is converted to milliseconds for the threshold.

    ``ts_col`` must contain no NaN. A NaN sample time has no place on the
    millisecond clock, and NaN sorts to the end and makes gap comparisons
    silently False, which would let a glitchy clock pass uncorrected. A NaN in
    ``ts_col`` raises ``ValueError`` so the malformed clock fails loudly.
    """
    out = df.copy()
    if out[ts_col].isna().any():
        n_nan = int(out[ts_col].isna().sum())
        raise ValueError(
            f"recover_ms_clock: {ts_col!r} contains {n_nan} NaN value(s); the "
            "per-sample millisecond clock must have no NaN. Drop or repair the "
            "NaN timestamps before clock recovery."
        )
    thresh_ms = GLITCH_GAP_MIN * 60_000.0
    for _ in range(max_jumps):
        s_sorted = np.sort(out[ts_col].to_numpy())
        if len(s_sorted) < 2:
            break
        gaps = np.diff(s_sorted)
        j = int(np.argmax(gaps))
        if gaps[j] <= thresh_ms:
            break
        offset = float(gaps[j])
        cut = s_sorted[j + 1]
        mask = out[ts_col].to_numpy() >= cut
        out.loc[mask, ts_col] = out.loc[mask, ts_col] - offset
        if end_col is not None and end_col in out.columns:
            out.loc[mask, end_col] = out.loc[mask, end_col] - offset
    return out
