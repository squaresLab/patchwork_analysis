"""Shared IO and path helpers for the paper_results build scripts.

The build scripts under ``paper_results`` all need the same things, so those
helpers live here and each build script imports them rather than redefining
them. The helpers fall into these categories.

  - Path / PID / project-Java: the repo root, the gaze-data directory, the
    timing CSV path, the study-PID-to-disk-name mapping, and the project-Java
    path filtering.
  - Source/test path classification: ``is_source`` / ``is_test`` over the
    project source and test roots.
  - IDE-log resolution: ``resolve_logs`` finds the ide_tracking.xml file(s) for
    a (PID, task), merging split parts.
  - Gaze clock recovery: ``recover_ms_clock`` undoes tracker-clock jumps in the
    per-sample millisecond timestamps.
"""

from __future__ import annotations

import os
from pathlib import Path

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
# layout; jfreechart uses /source & /tests. The rare /chart12/{source,tests}
# variants are folded in. Test roots are checked before source roots so that a
# test file is never misclassified as source.
SOURCE_ROOTS = ("/src/main/", "/source/", "/chart12/source/")
TEST_ROOTS = ("/src/test/", "/tests/", "/chart12/tests/")


def is_test(path: str) -> bool:
    if not is_project_java(path):
        return False
    return any(path.startswith(root) for root in TEST_ROOTS)


def is_source(path: str) -> bool:
    if not is_project_java(path):
        return False
    if any(path.startswith(root) for root in TEST_ROOTS):
        return False
    return any(path.startswith(root) for root in SOURCE_ROOTS)


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
    """Same single-jump recovery for per-sample millisecond timestamps.

    GLITCH_GAP_MIN minutes is converted to milliseconds for the threshold.
    """
    out = df.copy()
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
