"""Build the patch_usage categorization for the 84 patch tasks (RQ2).

Note that you probably don't need to run this! The csv it produces is already in
this directory.

For each (participant, task) in conditions ``correct`` and ``overfitting``, this
determines HOW the developer used the suggested patch and writes one of five
``patch_usage`` categories to ``patch_usage.csv``, next to the R model that
consumes it.

The category comes from two things about each task.

End-state, from the final diff vs the canonical patch. giving MATCHES-SUGGESTION, EDIT-AT-SITE, EDIT-ELSEWHERE, or NOTHING.

Mechanism, from the IDE event stream. The IDE tracking log gives four
non-exclusive flags for how the patch text entered the code: ``applied_dialog``
(apply-patch dialog), ``pasted_patch`` (paste of copied patch text),
``transcribed`` (hand typing), ``deleted_at_source`` (removal-based edit).
``patch_entered`` is applied_dialog OR pasted_patch OR transcribed.

The end-state and ``patch_entered`` map to the final ``patch_usage`` category.
Two hand-reviewed cells override the rule (P5 t2, P7 t2); both are encoded
explicitly with their reasons below.

The script reads:
- participant final diffs ``patchwork_data/<disk_pid>/<bug>_diff.txt``
- IDE logs ``patchwork_data/<disk_pid>/t<task>[ _part1/_part2]/ide_tracking.xml``
- the task list and anchors from ``patchwork_analysis/timing_correctness_data.csv``
The canonical patches are embedded in this file (``CANONICAL_PATCHES``). Which
yes is gross but they're short, sue me. 

It writes ``patch_usage.csv`` in this directory. See PATCH_USAGE_METHOD.md for
the full method writeup.

Run:
  python3 patchwork_analysis/paper_results/02_patch_editing/build_patch_usage.py
"""

from __future__ import annotations

import csv
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from patchwork_io import (
    APPLY_ACTION,
    DATA,
    TIMING_CSV,
    disk_pid,
    is_source,
    is_test,
    iter_ide_events,
    resolve_logs,
)

OUT = Path(__file__).resolve().parent / "patch_usage.csv"

# The canonical suggested patches, one per (bug, condition), embedded verbatim so
# this script has no external file dependency. condition `correct` is the correct
# APR patch; `overfitting` is the deceptive (test-passing, non-generalizing) APR
# patch. Each is the exact unified diff from the Eladawy ICSE'24 replication
# package; the parsers below read the `---/+++/@@/+/-` lines, so the surrounding
# text is reproduced as-is (including the original headers and timestamps).
CANONICAL_PATCHES: dict[tuple[str, str], str] = {
    ("chart12", "correct"): (
        "--- standard/MultiplePiePlot.java\t2024-10-25 22:12:39.000000000 -0400\n"
        "+++ correctAPR/MultiplePiePlot.java\t2024-10-25 22:19:20.000000000 -0400\n"
        "@@ -142,6 +142,9 @@\n"
        "      */\n"
        "     public MultiplePiePlot(CategoryDataset dataset) {\n"
        "         super();\n"
        "+        if(dataset!=null){\n"
        "+            dataset.addChangeListner(this);\n"
        "+        }\n"
        "         this.dataset = dataset;\n"
        "         PiePlot piePlot = new PiePlot(null);\n"
        "         this.pieChart = new JFreeChart(piePlot);\n"
    ),
    ("chart12", "overfitting"): (
        "--- standard/AbstractDataset.java\t2024-10-25 22:12:29.000000000 -0400\n"
        "+++ deceptiveAPR/AbstractDataset.java\t2024-10-25 22:39:36.000000000 -0400\n"
        "@@ -158,7 +158,7 @@\n"
        "      */\n"
        "     public boolean hasListener(EventListener listener) {\n"
        "         List list = Arrays.asList(this.listenerList.getListenerList());\n"
        "-        return list.contains(listener);\n"
        "+        return list != null || list.contains(listener);\n"
        "     }\n"
        "     \n"
        "     /**\n"
    ),
    ("lang10", "correct"): (
        "--- standard/FastDateParser.java\t2024-10-25 22:13:41.000000000 -0400\n"
        "+++ correctAPR/FastDateParser.java\t2024-10-25 23:02:35.000000000 -0400\n"
        "@@ -304,7 +304,7 @@\n"
        "         boolean wasWhite= false;\n"
        "         for(int i= 0; i<value.length(); ++i) {\n"
        "             char c= value.charAt(i);\n"
        "-            if(Character.isWhitespace(c)) {\n"
        "+            if((Character.isWhitespace(c)) && !(unquote)) {\n"
        "                 if(!wasWhite) {\n"
        "                     wasWhite= true;\n"
        '                     regex.append("\\\\s*+");\n'
    ),
    ("lang10", "overfitting"): (
        "--- standard/FastDateParser.java\t2024-10-25 22:13:41.000000000 -0400\n"
        "+++ decAPR/FastDateParser.java\t2024-10-25 23:12:18.000000000 -0400\n"
        "@@ -304,7 +304,7 @@\n"
        "         boolean wasWhite= false;\n"
        "         for(int i= 0; i<value.length(); ++i) {\n"
        "             char c= value.charAt(i);\n"
        "-            if(Character.isWhitespace(c)) {\n"
        "+            if(Character.isHighSurrogate(c)) {\n"
        "                 if(!wasWhite) {\n"
        "                     wasWhite= true;\n"
        '                     regex.append("\\\\s*+");\n'
    ),
    ("math33", "correct"): (
        "--- standard/SimplexTableau.java\t2024-10-25 22:15:15.000000000 -0400\n"
        "+++ correctAPR/SimplexTableau.java\t2024-10-25 23:56:19.000000000 -0400\n"
        "@@ -335,7 +335,7 @@\n"
        "         // positive cost non-artificial variables\n"
        "         for (int i = getNumObjectiveFunctions(); i < getArtificialVariableOffset(); i++) {\n"
        "             final double entry = tableau.getEntry(0, i);\n"
        "-            if (Precision.compareTo(entry, 0d, maxUlps) > 0) {\n"
        "+            if (Precision.compareTo(entry, 0d, epsilon) > 0) {\n"
        "                 columnsToDrop.add(i);\n"
        "             }\n"
        "         }\n"
    ),
    ("math33", "overfitting"): (
        "--- standard/SimplexTableau.java\t2024-10-25 22:15:15.000000000 -0400\n"
        "+++ decAPR/SimplexTableau.java\t2024-10-25 23:59:02.000000000 -0400\n"
        "@@ -335,7 +335,7 @@\n"
        "         // positive cost non-artificial variables\n"
        "         for (int i = getNumObjectiveFunctions(); i < getArtificialVariableOffset(); i++) {\n"
        "             final double entry = tableau.getEntry(0, i);\n"
        "-            if (Precision.compareTo(entry, 0d, maxUlps) > 0) {\n"
        "+            if (entry > this.epsilon && (Precision.compareTo(entry, 0d, maxUlps) > 0)) {\n"
        "                 columnsToDrop.add(i);\n"
        "             }\n"
        "         }\n"
    ),
    ("math50", "correct"): (
        "--- standard/BaseSecantSolver.java\t2024-10-25 22:15:40.000000000 -0400\n"
        "+++ correctAPR/BaseSecantSolver.java\t2024-10-26 00:05:49.000000000 -0400\n"
        "@@ -184,7 +184,7 @@\n"
        "                     break;\n"
        "                 case REGULA_FALSI:\n"
        "                     // Nothing.\n"
        "-                    if (x == x1) {\n"
        "+                    if (x == x0) {\n"
        "                         x0 = 0.5 * (x0 + x1 - FastMath.max(rtol * FastMath.abs(x1), atol));\n"
        "                         f0 = computeObjectiveValue(x0);\n"
        "                     }\n"
    ),
    ("math50", "overfitting"): (
        "--- standard/BaseSecantSolver.java\t2024-10-25 22:15:40.000000000 -0400\n"
        "+++ decAPR/BaseSecantSolver.java\t2024-10-26 00:08:33.000000000 -0400\n"
        "@@ -186,7 +186,7 @@\n"
        "                     // Nothing.\n"
        "                     if (x == x1) {\n"
        "                         x0 = 0.5 * (x0 + x1 - FastMath.max(rtol * FastMath.abs(x1), atol));\n"
        "-                        f0 = computeObjectiveValue(x0);\n"
        "+                        f0 = computeObjectiveValue(x);\n"
        "                     }\n"
        "                     break;\n"
        "                 default:\n"
    ),
    ("math63", "correct"): (
        "--- standard/MathUtils.java\t2024-10-25 22:16:00.000000000 -0400\n"
        "+++ correctAPR/MathUtils.java\t2024-10-26 00:13:04.000000000 -0400\n"
        "@@ -414,7 +414,7 @@\n"
        "      * @return {@code true} if the values are equal.\n"
        "      */\n"
        "     public static boolean equals(double x, double y) {\n"
        "-        return (Double.isNaN(x) && Double.isNaN(y)) || x == y;\n"
        "+        return equals(x,y,1) || FastMath.abs(y-x) <= SAFE_MIN;\n"
        "     }\n"
        " \n"
        "     /**\n"
    ),
    ("math63", "overfitting"): (
        "--- standard/MathUtils.java\t2024-10-25 22:16:00.000000000 -0400\n"
        "+++ decAPR/MathUtils.java\t2024-10-26 00:16:09.000000000 -0400\n"
        "@@ -414,7 +414,7 @@\n"
        "      * @return {@code true} if the values are equal.\n"
        "      */\n"
        "     public static boolean equals(double x, double y) {\n"
        "-        return (Double.isNaN(x) && Double.isNaN(y)) || x == y;\n"
        "+        return (Double.isNaN(EPSILON) && Double.isNaN(y)) || x == y;\n"
        "     }\n"
        " \n"
        "     /**\n"
    ),
}

# (bug, condition) cells whose canonical patch is so SMALL that reproducing it
# is nearly indistinguishable from a participant independently making the same
# edit. For these, an end-state of MATCHES-SUGGESTION / EDIT-AT-SITE is low-
# confidence: matching the canonical change does not strongly imply the patch
# was USED. The distinguishing change for each is a single token (or smaller).
# This is a property of the STIMULUS patch, not of any participant.
SUSPECT_TRIVIAL_CELLS = {
    ("math50", "correct"),
    ("math50", "overfitting"),
    ("lang10", "overfitting"),
    ("math33", "correct"),
    ("math63", "overfitting"),
}

# Manual overrides from hand-review of IDE typing streams. Keyed on
# (PID, task_no); applied AFTER the rule-based assignment.
MANUAL_OVERRIDES: dict[tuple[str, int], tuple[str, str]] = {
    ("P5", 2): (
        "applied_and_modified",
        "Typed the deceptive patch `if(Character.isHighSurrogate(c))` "
        "verbatim; EditorChooseLookupItem autocomplete inserted `Surrogate` "
        "invisibly so the typed-text containment under-scored a real "
        "transcription. Patch DID enter via typing.",
    ),
    ("P7", 2): (
        "own_fix_at_site",
        "Containment 0.5 is shared vocabulary, not transcription. Final diff "
        "shows own diagnostic scaffolding (final int t/e comparison vars, "
        "if(t!=e) probe, DEFAULT_ULPS 10->1, hand-worked math in comments), "
        "not the canonical maxUlps->epsilon swap. Patch did not enter.",
    ),
}

# ---------------------------------------------------------------------------
# End-state helpers: normalization / tokenization
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def strip_comments(line: str) -> str:
    """Drop simple // line comments and /* */ block comments on one line."""
    line = re.sub(r"/\*.*?\*/", " ", line)
    line = re.sub(r"//.*$", "", line)
    return line


def normalize(line: str) -> str:
    """Strip comments, collapse internal whitespace, trim."""
    line = strip_comments(line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def tokenize(line: str) -> list[str]:
    """Tokenize a normalized code line (case-sensitive)."""
    return TOKEN_RE.findall(strip_comments(line))


def is_substantive(line: str) -> bool:
    """True if a normalized source line has real code content."""
    n = normalize(line)
    if not n:
        return False
    return bool(re.search(r"[A-Za-z0-9]", n))


# Debug/instrumentation statements participants add AROUND the fix while working
# (print tracing, logging). These do not constitute a different fix, so they must
# not flip an otherwise-faithful application to EDIT-AT-SITE.
DEBUG_RE = re.compile(
    r"""
    \b(
        System\s*\.\s*(out|err)\s*\.\s*(println|print|printf)
        | (e\s*\.\s*)?printStackTrace
        | (log(ger)?|LOG|LOGGER)\s*\.\s*
          (trace|debug|info|warn|warning|error|fine|finer|finest|severe)
    )\b
    """,
    re.VERBOSE,
)


def is_debug_line(line: str) -> bool:
    """True if a source line is solely a debug/instrumentation statement."""
    n = normalize(line)
    return bool(n) and bool(DEBUG_RE.search(n))


# ---------------------------------------------------------------------------
# Canonical patch parsing
# ---------------------------------------------------------------------------
class CanonicalPatch:
    def __init__(
        self,
        target_file: str,
        added_lines: list[str],
        context_lines: list[str],
        hunk_start: Optional[int],
        hunk_end: Optional[int],
    ) -> None:
        self.target_file = target_file  # basename
        self.added_lines = added_lines  # substantive added source lines
        self.context_lines = context_lines  # substantive unchanged hunk lines
        self.hunk_start = hunk_start
        self.hunk_end = hunk_end


def parse_canonical(text: str) -> CanonicalPatch:
    """Parse a canonical unified-diff patch (given as text).

    Returns the target file basename (from +++ header), substantive added
    source lines, the substantive context lines, and the post-image hunk range.
    """
    target_file = ""
    added: list[str] = []
    context: list[str] = []
    hunk_start: Optional[int] = None
    hunk_end: Optional[int] = None
    in_hunk = False
    for line in text.splitlines():
        if line.startswith("+++"):
            path_part = line[3:].strip().split("\t")[0].strip()
            target_file = Path(path_part).name
        elif line.startswith("---"):
            continue
        elif line.startswith("@@"):
            in_hunk = True
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                hunk_start = start
                hunk_end = start + count - 1
        elif line.startswith("+"):
            content = line[1:]
            if is_substantive(content):
                added.append(content)
        elif line.startswith("-"):
            continue
        elif in_hunk and (line.startswith(" ") or line == ""):
            if is_substantive(line):
                context.append(line[1:] if line.startswith(" ") else line)
    return CanonicalPatch(target_file, added, context, hunk_start, hunk_end)


# ---------------------------------------------------------------------------
# Participant diff parsing
# ---------------------------------------------------------------------------
class FileEdit:
    def __init__(self, target_path: str) -> None:
        self.target_path = target_path  # full path from +++ header
        self.basename = Path(target_path).name
        # Use the shared segment-based classifier so jfreechart's plural /tests/
        # and *Tests.java files are recognized as tests, not source.
        self.is_test = is_test(target_path)
        self.is_java = self.basename.endswith(".java")
        self.added: list[str] = []  # substantive added source lines
        self.hunk_lines: list[tuple[int, int]] = []  # (start,end) post-image


def parse_participant_diff(diff_path: Path) -> list[FileEdit]:
    """Parse a `diff -ru` participant diff into per-file edits.

    Handles multiple file sections. Only retains `.java` files. Records
    substantive added source lines and post-image hunk ranges per file.
    """
    edits: list[FileEdit] = []
    current: Optional[FileEdit] = None
    text = diff_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if (
            line.startswith("diff -ru")
            or line.startswith("Only in")
            or line.startswith("Binary files")
        ):
            current = None
            continue
        if line.startswith("---"):
            continue
        if line.startswith("+++"):
            path_part = line[3:].strip().split("\t")[0].strip()
            current = FileEdit(path_part)
            edits.append(current)
            continue
        if line.startswith("@@"):
            if current is not None:
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if m:
                    start = int(m.group(1))
                    count = int(m.group(2)) if m.group(2) else 1
                    current.hunk_lines.append((start, start + count - 1))
            continue
        if current is None:
            continue
        if line.startswith("+"):
            content = line[1:]
            if is_substantive(content):
                current.added.append(content)
        elif line.startswith("-"):
            continue  # removed line
    return [e for e in edits if e.is_java]


# ---------------------------------------------------------------------------
# End-state classification matching policy
# ---------------------------------------------------------------------------
# A canonical clause is reproduced if its token sequence aligns with a
# participant line allowing only bracket insert/delete slack and TYPO-near
# identifier substitution (char Levenshtein <= TYPO_LEV). A token swapped for a
# different identifier is NOT a typo and the clause is treated as not reproduced.
TYPO_LEV = 2
BRACKETS = {"(", ")"}


def _lev(a: str, b: str) -> int:
    m, n = len(a), len(b)
    d = list(range(n + 1))
    for i in range(1, m + 1):
        prev = d[0]
        d[0] = i
        for j in range(1, n + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
            prev = cur
    return d[n]


def _tok_equiv(a: str, b: str) -> bool:
    """Two tokens are equivalent if identical or a typo-near pair (alnum, with
    char Levenshtein <= TYPO_LEV and within 25% length).

    Fuzzy substitution is forbidden when BOTH tokens are length <= 2. Otherwise a
    single-char difference between two short identifiers (e.g. ``x0`` vs ``x1``,
    the math50/correct distinguishing edit) would be scored as a typo, masking a
    participant who did NOT apply the fix. Long-identifier typos such as
    ``Listner`` vs ``Listener`` are unaffected."""
    if a == b:
        return True
    if not (a.isidentifier() and b.isidentifier()):
        return False
    if len(a) <= 2 and len(b) <= 2:
        return False
    if _lev(a, b) > TYPO_LEV:
        return False
    return abs(len(a) - len(b)) <= max(1, int(0.25 * max(len(a), len(b))))


def _align_with_slack(can: list[str], part: list[str]) -> bool:
    """True if `can` aligns into `part` as a contiguous-ish block allowing
    bracket insert/delete and typo substitutions. Tries each start offset in
    `part` and runs a tolerant two-pointer match."""
    if not can:
        return True
    n = len(part)
    cn = len(can)
    for start in range(0, n):
        i = start  # part index
        j = 0  # can index
        bad = False
        while j < cn and i <= n:
            if i >= n:
                if all(t in BRACKETS for t in can[j:]):
                    j = cn
                break
            if _tok_equiv(can[j], part[i]):
                i += 1
                j += 1
            elif part[i] in BRACKETS:
                i += 1
            elif can[j] in BRACKETS:
                j += 1
            else:
                bad = True
                break
        if not bad and j >= cn:
            return True
    return False


def clause_present(can_line: str, participant_added: list[str]) -> tuple[bool, bool]:
    """Is one canonical added line reproduced by some participant added line?

    Returns (present, fuzzy). `fuzzy` True when matched only via bracket/typo
    slack (not an exact token-sequence match)."""
    can_toks = tokenize(can_line)
    if not can_toks:
        return True, False
    for p in participant_added:
        ptoks = tokenize(p)
        for s in range(0, max(1, len(ptoks) - len(can_toks) + 1)):
            if ptoks[s : s + len(can_toks)] == can_toks:
                return True, False
    for p in participant_added:
        if _align_with_slack(can_toks, tokenize(p)):
            return True, True
    return False, False


def canonical_clauses_present(
    canonical_added: list[str], participant_added: list[str]
) -> tuple[bool, bool]:
    """All canonical clauses present? Returns (all_present, any_fuzzy)."""
    all_present = True
    any_fuzzy = False
    for can in canonical_added:
        present, fuzzy = clause_present(can, participant_added)
        if not present:
            all_present = False
        if fuzzy:
            any_fuzzy = True
    return all_present, any_fuzzy


def at_canonical_site(edit: FileEdit, can: CanonicalPatch) -> bool:
    """Same target file (basename) and overlapping hunk range (with slack)."""
    if edit.basename != can.target_file:
        return False
    if can.hunk_start is None or can.hunk_end is None:
        return True
    # +/-25 source-LINE tolerance around the canonical hunk: a participant's edit
    # counts as "at the canonical site" if its post-image range comes within 25
    # lines of the canonical range, absorbing line drift from unrelated edits
    # above the fix. Unrelated to the 25-minute task cap.
    slack = 25
    for (s, e) in edit.hunk_lines:
        if e >= can.hunk_start - slack and s <= can.hunk_end + slack:
            return True
    return False


def classify_endstate(
    edits: list[FileEdit], can: CanonicalPatch
) -> tuple[str, int, list[str], str]:
    """Return (end_state, n_extra_source_lines, extra_lines, notes)."""
    source_edits = [e for e in edits if not e.is_test]
    all_added_source = [ln for e in source_edits for ln in e.added]

    if not all_added_source:
        return ("NOTHING", 0, [], "no substantive added source lines")

    site_edits = [e for e in source_edits if at_canonical_site(e, can)]
    in_target_file = [e for e in source_edits if e.basename == can.target_file]

    if not in_target_file:
        extra = all_added_source
        files = sorted({e.basename for e in source_edits})
        return (
            "EDIT-ELSEWHERE",
            len(extra),
            extra,
            f"edited {files}, not canonical target {can.target_file}",
        )

    if not site_edits:
        extra = [ln for e in in_target_file for ln in e.added]
        return (
            "EDIT-ELSEWHERE",
            len(extra),
            extra,
            f"edited {can.target_file} but outside canonical hunk site",
        )

    site_added = [ln for e in site_edits for ln in e.added]

    def reproduces_canonical(ln: str) -> bool:
        present, _ = clause_present(ln, can.added_lines)
        if present:
            return True
        ln_toks = tokenize(ln)
        for c in can.added_lines:
            if _align_with_slack(tokenize(c), ln_toks):
                return True
        return False

    def is_canonical_context(ln: str) -> bool:
        ln_toks = tokenize(ln)
        for c in can.context_lines:
            ctoks = tokenize(c)
            if ctoks and _align_with_slack(ctoks, ln_toks):
                return True
        return False

    candidate_extra = [
        ln
        for ln in all_added_source
        if not reproduces_canonical(ln) and not is_canonical_context(ln)
    ]
    extra_lines = [ln for ln in candidate_extra if not is_debug_line(ln)]
    n_debug_skipped = len(candidate_extra) - len(extra_lines)
    n_extra = len(extra_lines)
    debug_note = (
        f" (ignored {n_debug_skipped} debug/print line(s))" if n_debug_skipped else ""
    )

    fully_reproduced, any_fuzzy = canonical_clauses_present(can.added_lines, site_added)
    fuzzy_note = (
        " (fuzzy clause match; stimulus typo/redundant parens)" if any_fuzzy else ""
    )

    if fully_reproduced and n_extra == 0:
        return (
            "MATCHES-SUGGESTION",
            0,
            [],
            "all canonical clauses present at site; no other source change"
            + fuzzy_note
            + debug_note,
        )
    if fully_reproduced and n_extra > 0:
        return (
            "EDIT-AT-SITE",
            n_extra,
            extra_lines,
            "canonical clauses present but additional source changes exist"
            + fuzzy_note
            + debug_note,
        )
    return (
        "EDIT-AT-SITE",
        n_extra,
        extra_lines,
        "edited canonical site but canonical clauses not fully reproduced",
    )


# ---------------------------------------------------------------------------
# IDE event stream mechanism flags
# ---------------------------------------------------------------------------
PASTE_ACTIONS = {"EditorPaste"}
COPY_ACTION = "EditorCopy"
SUGGESTED_PATCH_PATH = "/suggested.patch"
BACKSPACE_ACTIONS = {"EditorBackSpace", "EditorDeleteToWordStart"}
DELETION_ACTIONS = {
    "EditorBackSpace",
    "EditorDeleteToWordStart",
    "EditorDelete",
    "EditorCut",
    "EditorDeleteToWordEnd",
    "EditorDeleteLine",
}
AUTOCOMPLETE = {"EditorChooseLookupItem", "EditorChooseLookupItemReplace"}
CONTROL_CHARS = {"0", "1"}  # control-key codes per CodeGRITS logs

# transcription thresholds (judgment calls, documented in PATCH_USAGE_METHOD.md)
TRANSCRIBE_HI = 0.80  # containment fraction
AUTOCOMPLETE_MAX = 2  # allow a couple autocomplete events before untrusted


def stream_events(xml_path: Path):
    """Yield (kind, ts, path, char, line, col) for typing + actions, file order.

    kind is 'type' for typing, or 'action:<event>' for actions. Elements
    without a timestamp are skipped.
    """
    for kind, attrs in iter_ide_events(xml_path):
        if kind not in ("typing", "action"):
            continue
        ts = attrs["timestamp"]
        if ts is None:
            continue
        if kind == "typing":
            yield (
                "type",
                ts,
                attrs["path"],
                attrs["character"],
                attrs["line"],
                attrs["column"],
            )
        else:
            yield ("action:" + attrs["key"], ts, attrs["path"], "", -1, -1)


def load_events(xml_paths: list[Path]) -> list[tuple]:
    events: list[tuple] = []
    for xml_path in xml_paths:
        events.extend(stream_events(xml_path))
    events.sort(key=lambda e: e[1])
    return events


def reconstruct_typed(events: list[tuple]) -> tuple[str, dict]:
    """Positional reconstruction of typed SOURCE text.

    Buffer is a dict (line, col) -> char. Backspace on source removes the most
    recently written cell. Returns (text, diagnostics).
    """
    buf: dict[tuple[int, int], str] = {}
    order: list[tuple[int, int]] = []
    n_typed = 0
    n_autocomplete = 0
    for kind, _ts, path, ch, line, col in events:
        if kind == "type":
            if not is_source(path):
                continue
            if ch in CONTROL_CHARS or ch == "":
                continue
            if line < 0 or col < 0:
                continue
            key = (line, col)
            if key in buf and key in order:
                order.remove(key)
            buf[key] = ch
            order.append(key)
            n_typed += 1
        elif kind.startswith("action:"):
            ev = kind.split(":", 1)[1]
            if ev in BACKSPACE_ACTIONS and is_source(path):
                if order:
                    last = order.pop()
                    buf.pop(last, None)
            elif ev in AUTOCOMPLETE:
                # Count autocomplete regardless of path. An autocomplete with an
                # empty/non-source path still corrupts the positional
                # reconstruction, so it must feed the AUTOCOMPLETE_MAX guard.
                n_autocomplete += 1
    lines: dict[int, dict[int, str]] = {}
    for (line, col), ch in buf.items():
        lines.setdefault(line, {})[col] = ch
    out_lines = []
    for line in sorted(lines):
        cols = lines[line]
        out_lines.append("".join(cols[c] for c in sorted(cols)))
    text = "\n".join(out_lines)
    diag = {
        "n_typed_chars": n_typed,
        "n_autocomplete": n_autocomplete,
    }
    return text, diag


def mech_tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def similarity(typed: str, added_lines: list[str]) -> dict:
    patch_text = "\n".join(added_lines)
    t_tok = mech_tokens(typed)
    p_tok = mech_tokens(patch_text)
    if not p_tok:
        return {"containment": 0.0, "n_patch_tok": 0, "n_typed_tok": len(t_tok)}
    sm = SequenceMatcher(None, t_tok, p_tok, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    containment = matched / len(p_tok)
    return {
        "containment": round(containment, 3),
        "n_patch_tok": len(p_tok),
        "n_typed_tok": len(t_tok),
    }


def load_canonical_added(bug: str, cond: str) -> list[str]:
    """Map (bug_lower, condition) -> list of added (+) code lines, raw (mechanism).

    Mechanism containment uses ALL +-lines (not the substantive-filtered end-state
    set), so this loader is intentionally separate from parse_canonical.
    """
    return [
        ln[1:]
        for ln in CANONICAL_PATCHES[(bug, cond)].splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]


def compute_apply(events: list[tuple]) -> bool:
    """applied_dialog: any ApplyPatch event occurred."""
    return any(kind == "action:" + APPLY_ACTION for kind, *_ in events)


def compute_pasted_patch(events: list[tuple]) -> bool:
    """pasted_patch: a paste into source preceded by a copy from the patch."""
    seen_patch_copy = False
    pasted_patch = False
    for kind, _ts, path, _ch, _line, _col in events:
        if kind == "action:" + COPY_ACTION and path == SUGGESTED_PATCH_PATH:
            seen_patch_copy = True
        elif kind == "action:" + APPLY_ACTION:
            continue
        elif kind.startswith("action:"):
            ev = kind.split(":", 1)[1]
            if ev in PASTE_ACTIONS and is_source(path):
                if seen_patch_copy:
                    pasted_patch = True
    return pasted_patch


def compute_deletion(events: list[tuple]) -> bool:
    """deleted_at_source: any removal-based edit on a SOURCE file."""
    for kind, _ts, path, _ch, _line, _col in events:
        if kind.startswith("action:"):
            ev = kind.split(":", 1)[1]
            if ev in DELETION_ACTIONS and is_source(path):
                return True
    return False


def compute_mechanisms(pid: str, task_no: int, bug: str, cond: str) -> dict:
    """All four mechanism flags for one task. Empty/missing logs -> all False."""
    logs = resolve_logs(pid, task_no)
    if not logs:
        return {
            "applied_dialog": False,
            "pasted_patch": False,
            "transcribed": False,
            "deleted_at_source": False,
        }
    events = load_events(logs)
    added = load_canonical_added(bug, cond)

    applied_dialog = compute_apply(events)
    pasted_patch = compute_pasted_patch(events)
    typed, diag = reconstruct_typed(events)
    sim = similarity(typed, added)
    containment = sim["containment"]
    transcribed = (
        containment is not None
        and containment >= TRANSCRIBE_HI
        and diag["n_autocomplete"] <= AUTOCOMPLETE_MAX
    )
    deleted_at_source = compute_deletion(events)
    return {
        "applied_dialog": applied_dialog,
        "pasted_patch": pasted_patch,
        "transcribed": transcribed,
        "deleted_at_source": deleted_at_source,
    }


# ---------------------------------------------------------------------------
# The join rule
# ---------------------------------------------------------------------------
def classify_rule(end_state: str, patch_entered: bool) -> str:
    """Rule-based patch_usage before manual overrides."""
    if end_state == "MATCHES-SUGGESTION":
        return "applied_unchanged"
    if end_state == "EDIT-AT-SITE":
        return "applied_and_modified" if patch_entered else "own_fix_at_site"
    if end_state == "EDIT-ELSEWHERE":
        return "own_fix_elsewhere"
    if end_state == "NOTHING":
        return "nothing"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def load_task_list() -> list[dict]:
    """The 84 patch tasks + anchors, derived from the timing CSV.

    Restricts to condition in {correct, overfitting}. Reads PID, task_no, bug,
    condition, correct, plus Kaia's hand-coded anchors fix_site_same and
    evaluated_patch.
    """
    tasks: list[dict] = []
    with TIMING_CSV.open() as f:
        for r in csv.DictReader(f):
            if r["condition"] not in ("correct", "overfitting"):
                continue
            tasks.append(
                {
                    "PID": r["PID"],
                    "task_no": r["task_no"],
                    "bug": r["bug"],
                    "condition": r["condition"],
                    "correct": r["correct"],
                    "fix_site_same": r.get("fix_site_same", "") or "",
                    "evaluated_patch": r.get("evaluated_patch", "") or "",
                }
            )
    return tasks


def build_rows() -> list[dict]:
    canon: dict[tuple[str, str], CanonicalPatch] = {
        key: parse_canonical(text) for key, text in CANONICAL_PATCHES.items()
    }

    tasks = load_task_list()
    if len(tasks) != 84:
        raise SystemExit(
            f"Expected 84 patch tasks from timing CSV, got {len(tasks)}. STOP."
        )

    rows: list[dict] = []
    for t in tasks:
        pid = t["PID"]
        task_no = int(t["task_no"])
        bug = t["bug"]
        cond = t["condition"]
        disk = disk_pid(pid)
        cp = canon[(bug, cond)]

        # End-state from the final diff.
        diff_path = DATA / disk / f"{bug}_diff.txt"
        if not diff_path.exists():
            raise SystemExit(f"Missing participant diff: {diff_path}. STOP.")
        edits = parse_participant_diff(diff_path)
        end_state, _n_extra, _extra, _notes = classify_endstate(edits, cp)

        # suspect_trivial_patch flag: only meaningful where the end-state rests
        # on matching the canonical clause (MATCHES-SUGGESTION/EDIT-AT-SITE).
        suspect = (bug, cond) in SUSPECT_TRIVIAL_CELLS and end_state in (
            "MATCHES-SUGGESTION",
            "EDIT-AT-SITE",
        )

        # Mechanism flags from the IDE event stream.
        mech = compute_mechanisms(pid, task_no, bug, cond)
        patch_entered = (
            mech["applied_dialog"] or mech["pasted_patch"] or mech["transcribed"]
        )

        # The join. rule_patch_usage records the pre-override rule output so a
        # manual override is auditable in the CSV and future rule drift under an
        # override is visible.
        rule_patch_usage = classify_rule(end_state, patch_entered)
        patch_usage = rule_patch_usage
        override_applied = False
        override_reason = ""
        if (pid, task_no) in MANUAL_OVERRIDES:
            patch_usage, override_reason = MANUAL_OVERRIDES[(pid, task_no)]
            override_applied = True

        rows.append(
            {
                "PID": pid,
                "task_no": task_no,
                "bug": bug,
                "condition": cond,
                "correct": t["correct"],
                "end_state": end_state,
                "patch_entered": patch_entered,
                "applied_dialog": mech["applied_dialog"],
                "pasted_patch": mech["pasted_patch"],
                "transcribed": mech["transcribed"],
                "deleted_at_source": mech["deleted_at_source"],
                "patch_usage": patch_usage,
                "rule_patch_usage": rule_patch_usage,
                "override_applied": override_applied,
                "override_reason": override_reason,
                "suspect_trivial_patch": suspect,
                "fix_site_same": t["fix_site_same"],
                "evaluated_patch": t["evaluated_patch"],
            }
        )

    rows.sort(key=lambda r: (r["PID"], r["task_no"]))
    return rows


OUT_COLS = [
    "PID",
    "task_no",
    "bug",
    "condition",
    "correct",
    "end_state",
    "patch_entered",
    "applied_dialog",
    "pasted_patch",
    "transcribed",
    "deleted_at_source",
    "patch_usage",
    "rule_patch_usage",
    "override_applied",
    "override_reason",
    "suspect_trivial_patch",
    "fix_site_same",
    "evaluated_patch",
]

# Booleans are written as Python's True/False to match the existing CSV.
BOOL_COLS = {
    "patch_entered",
    "applied_dialog",
    "pasted_patch",
    "transcribed",
    "deleted_at_source",
    "override_applied",
    "suspect_trivial_patch",
}


def write_csv(rows: list[dict]) -> None:
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OUT_COLS)
        for r in rows:
            out = []
            for c in OUT_COLS:
                v = r[c]
                if c in BOOL_COLS:
                    out.append("True" if v else "False")
                else:
                    out.append(v)
            w.writerow(out)


def main() -> None:
    rows = build_rows()
    write_csv(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["patch_usage"]] = counts.get(r["patch_usage"], 0) + 1
    print(f"Wrote {OUT} ({len(rows)} rows)")
    order = [
        "applied_unchanged",
        "applied_and_modified",
        "own_fix_at_site",
        "own_fix_elsewhere",
        "nothing",
    ]
    print("patch_usage counts:")
    for cat in order:
        print(f"  {cat:22s} {counts.get(cat, 0)}")

    overridden = [r for r in rows if r["override_applied"]]
    print(f"\nmanual overrides applied: {len(overridden)}")
    for r in overridden:
        print(
            f"  {r['PID']} t{r['task_no']} ({r['bug']}/{r['condition']}) "
            f"-> {r['patch_usage']}"
        )
        print(f"      reason: {r['override_reason']}")


if __name__ == "__main__":
    main()
