"""Apply coverage thresholds to a JaCoCo, Cobertura, or LCOV report.

Two independent checks:
    overall  - total line coverage must be >= --min-coverage
    ratchet  - with --baseline, total line coverage must not fall below the value
               recorded there, a JSON file of the form {"overall": 83.2}

A third check keeps the baseline current. With --baseline-margin, total line coverage
must not exceed the baseline by more than that many percentage points, so a change
that raises coverage also raises the file. It applies only when a baseline exists.

A fourth check holds new work to a standard regardless of the overall figure. With
--min-changed-coverage and --diff (the output of `git diff -U0`), the combined line
coverage of the lines the diff adds or modifies must be >= that minimum. Only lines the
report marks as executable count, so comments, tests and docs are ignored, and the check
is skipped when no changed line appears in the report. Report paths are matched to the files
`git ls-files` lists, so run it from a git checkout, in the directory the diff is relative to.

The report format follows the file extension: `.xml` is JaCoCo or Cobertura, anything else
is read as LCOV.

With --warn-only a violation is reported as a warning and the exit code stays 0,
so teams can adopt the gate without failing their jobs.

Exit codes:
    0  - all checks passed or skipped, or a violation under --warn-only
    2  - at least one threshold was violated
    1  - error (unreadable or empty report, unknown format, malformed baseline,
         changed lines check outside a git checkout)

Usage:
    python3 coverage_gate.py <report> --min-coverage 80 \\
        [--baseline coverage-baseline.json] [--baseline-margin 1] \\
        [--diff changes.diff --min-changed-coverage 80] [--summary-file summary.md] \\
        [--warn-only]
"""

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable
from pathlib import Path


class GateError(Exception):
    """Unreadable or unsupported input; maps to exit code 1."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        # argparse exits with 2, which this script reserves for threshold violations.
        self.print_usage(sys.stderr)
        print(f"::error::{message}", file=sys.stderr)
        raise SystemExit(1)


def _percent(covered: int, total: int, path: Path) -> float:
    # A report with no instrumented lines usually means coverage was misconfigured,
    # so it is an error rather than a pass.
    if total == 0:
        raise GateError(f"{path}: report contains no coverage data")
    return covered * 100 / total


def _overall_xml(path: Path) -> float:
    root = ET.parse(path).getroot()
    if root.tag == "report":
        # JaCoCo: report-level LINE counter is the sum across all packages.
        for counter in root.findall("counter"):
            if counter.get("type") == "LINE":
                covered = int(counter.get("covered", 0))
                return _percent(covered, covered + int(counter.get("missed", 0)), path)
        raise GateError(f"{path}: JaCoCo report has no report-level LINE counter")
    if root.tag == "coverage":
        lines_valid = root.get("lines-valid")
        lines_covered = root.get("lines-covered")
        if lines_valid is not None and lines_covered is not None:
            return _percent(int(lines_covered), int(lines_valid), path)
    raise GateError(f"{path}: not a recognised JaCoCo or Cobertura report")


def _overall_lcov(path: Path) -> float:
    # Merge by file and line, as the changed lines check does, so a trace with several
    # records for one file, such as concatenated per-test reports, is not double counted.
    detailed = _lines_lcov(path)
    merged = [hit for lines in detailed.values() for hit in lines.values()]
    found, hit = len(merged), sum(merged)
    # A record without DA lines still carries its LF and LH totals, so count those too. A file
    # that has DA lines anywhere in the trace is already counted line by line, and a file with
    # several totals-only records is counted once, at its largest figures.
    totals: dict[str, tuple[int, int]] = {}
    name, has_da, record_found, record_hit = "", False, 0, 0
    for line in [*path.read_text(encoding="utf-8").splitlines(), "end_of_record"]:
        if line.startswith("SF:"):
            name = _normalise(line[3:])
        elif line.startswith("DA:"):
            has_da = True
        elif line.startswith("LF:"):
            record_found = int(line[3:])
        elif line.startswith("LH:"):
            record_hit = int(line[3:])
        elif line == "end_of_record":
            if name and not has_da and not detailed.get(name):
                old_found, old_hit = totals.get(name, (0, 0))
                totals[name] = (max(old_found, record_found), max(old_hit, record_hit))
            name, has_da, record_found, record_hit = "", False, 0, 0
    found += sum(f for f, _ in totals.values())
    hit += sum(h for _, h in totals.values())
    return _percent(hit, found, path)


def overall_coverage(path: Path) -> float:
    """Return total line coverage as a percentage."""
    if not path.is_file():
        raise GateError(f"coverage report not found: {path}")
    try:
        if path.suffix == ".xml":
            return _overall_xml(path)
        return _overall_lcov(path)
    except (ET.ParseError, ValueError) as exc:
        raise GateError(f"{path}: unreadable coverage report ({exc})") from exc


def _normalise(path: str) -> str:
    path = path.strip().replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def _lines_xml(path: Path) -> dict[str, dict[int, bool]]:
    root = ET.parse(path).getroot()
    files: dict[str, dict[int, bool]] = {}
    if root.tag == "report":
        # JaCoCo names a file by its package directory plus the source file name.
        for package in root.findall("package"):
            for source in package.findall("sourcefile"):
                name = f"{package.get('name', '')}/{source.get('name')}"
                lines = files.setdefault(_normalise(name).lstrip("/"), {})
                for line in source.findall("line"):
                    number = int(line.get("nr", 0))
                    lines[number] = lines.get(number, False) or int(line.get("ci", 0)) > 0
        return files
    if root.tag == "coverage":
        # Inner classes share a file, so merge by line number.
        for cls in root.iter("class"):
            lines = files.setdefault(_normalise(cls.get("filename", "")), {})
            for line in cls.iter("line"):
                number = int(line.get("number", 0))
                lines[number] = lines.get(number, False) or int(line.get("hits", 0)) > 0
        return files
    raise GateError(f"{path}: not a recognised JaCoCo or Cobertura report")


def _lines_lcov(path: Path) -> dict[str, dict[int, bool]]:
    files: dict[str, dict[int, bool]] = {}
    lines: dict[int, bool] | None = None
    for position, row in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if row.startswith("SF:"):
            lines = files.setdefault(_normalise(row[3:]), {})
        elif row.startswith(("DA:", "LF:", "LH:")) and lines is None:
            # Skipping the record would drop its coverage without any sign, so fail instead.
            raise GateError(f"{path}:{position}: coverage record has no SF line")
        elif row.startswith("DA:"):
            number, hits = row[3:].split(",")[:2]
            lines[int(number)] = lines.get(int(number), False) or int(hits) > 0
        elif row == "end_of_record":
            lines = None
    return files


def line_coverage(path: Path) -> dict[str, dict[int, bool]]:
    """Return whether each executable line is covered, keyed by file path then line number."""
    try:
        return _lines_xml(path) if path.suffix == ".xml" else _lines_lcov(path)
    except (ET.ParseError, ValueError) as exc:
        raise GateError(f"{path}: unreadable coverage report ({exc})") from exc


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or re.match(r"[A-Za-z]:/", path) is not None


def _under_root(name: str, root: str) -> str:
    # Absolute report paths start at the checkout, while changed paths are relative to the
    # working directory, so strip the working directory when the report is under it.
    prefix = root + "/"
    return name[len(prefix) :] if name.startswith(prefix) else name


def tracked_files() -> set[str]:
    """Return the files git tracks under the working directory."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GateError(
            "the changed lines check needs a git checkout and must run in the directory "
            "the diff is relative to"
        ) from exc
    return {_normalise(path) for path in result.stdout.split("\0") if path}


def _prefix(path: str, entry: str) -> str:
    return path[: len(path) - len(entry)]


def _fits(
    entries: Iterable[str], tracked: Iterable[str], exact: Collection[str] = ()
) -> dict[str, list[str]]:
    """Map each report entry to the tracked files it could name, leaving out entries with none.

    An `exact` entry is already a full path from the working directory, so it names only itself.
    """
    tracked = set(tracked)
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in tracked:
        by_name[path.rsplit("/", 1)[-1]].append(path)
    fits = {}
    for entry in entries:
        named = by_name.get(entry.rsplit("/", 1)[-1], [])
        if entry in exact:
            found = [entry] if entry in tracked else []
        elif _is_absolute(entry):
            found = [path for path in named if entry.endswith("/" + path)]
        else:
            found = [path for path in named if path == entry or path.endswith("/" + entry)]
        if found:
            fits[entry] = sorted(found)
    return fits


def _resolve(fits: dict[str, list[str]]) -> dict[str, str]:
    """Map each report entry to the one tracked file it names.

    A report names files relative to a source root it does not state, so `utils.py` fits
    `app/utils.py` and `app/migrations/utils.py` alike. The source root is the prefix most
    entries share, so the file whose prefix serves the most entries is the one the report
    means. A tie goes to the path nearest the project root. An absolute entry written under
    a checkout root this run cannot see, such as a container path, names the longest tracked
    path it ends with.
    """
    relative = {entry: found for entry, found in fits.items() if not _is_absolute(entry)}
    support = Counter(_prefix(path, entry) for entry, found in relative.items() for path in found)
    resolved = {}
    for entry, found in fits.items():
        if entry in relative:
            resolved[entry] = max(found, key=lambda p, e=entry: (support[_prefix(p, e)], -len(p)))
        else:
            resolved[entry] = max(found, key=len)
    return resolved


def _ambiguities(
    fits: dict[str, list[str]], resolved: dict[str, str], changed: dict[str, set[int]]
) -> list[str]:
    """Describe each entry that fits several files when a changed file is one of them.

    The pick rests on a guess about the source root, so a changed file among the candidates
    either went unscored or was scored with another file's entry. A candidate that another
    entry resolves to is scored through that entry, so it is not a candidate here. An
    absolute entry names the longest path it ends with, which is not a guess.
    """
    notes = []
    for entry, found in sorted(fits.items()):
        if _is_absolute(entry):
            continue
        taken = {path for other, path in resolved.items() if other != entry}
        candidates = [p for p in found if p == resolved[entry] or p not in taken]
        if len(candidates) > 1 and any(changed.get(p) for p in candidates):
            notes.append(
                f"{entry} in the report fits {', '.join(candidates)}; "
                f"it is used for {resolved[entry]}. "
                "Set working-directory to the module folder to avoid this."
            )
    return notes


_HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def changed_lines(diff: Path) -> dict[str, set[int]]:
    """Return the added or modified line numbers of each file in a `git diff -U0`."""
    if not diff.is_file():
        raise GateError(f"diff not found: {diff}")
    changed: dict[str, set[int]] = {}
    lines: set[int] | None = None
    # A removed or added line can start with "--- " or "+++ ", so a file path counts only
    # in the header between "diff --git" and the first hunk.
    in_header = False
    # Split on newlines only: splitlines() also breaks at characters such as form feed, which
    # source files can contain. Changed files need not be UTF-8, and only the headers matter.
    for row in diff.read_text(encoding="utf-8", errors="replace").split("\n"):
        if row.startswith("diff --git "):
            in_header, lines = True, None
        elif in_header and row.startswith("+++ "):
            target = row[4:].split("\t")[0]
            if target != "/dev/null":
                lines = changed.setdefault(_normalise(target.removeprefix("b/")), set())
        elif row.startswith("@@"):
            in_header = False
            hunk = _HUNK.match(row)
            if lines is not None and hunk:
                start, count = int(hunk[1]), int(hunk[2] or 1)
                lines.update(range(start, start + count))
    return changed


def changed_coverage(
    report: Path,
    diff: Path,
    tracked: Iterable[str],
    ambiguities: list[str] | None = None,
) -> tuple[float, dict[str, tuple[int, int]]] | None:
    """Return combined coverage of the changed lines in the report and each file's counts.

    Only changed lines the report marks as executable count, so comments, blank lines and
    imports do not. Returns None when no such line exists. `tracked` lists the repository
    files under the working directory. A report entry belongs to the one tracked file it
    names, so a changed file the report omits, such as one excluded from coverage, is
    skipped rather than scored against a same-named file. Counts are keyed by the file's
    path relative to the working directory. Entries that fit several files, one of them
    changed, are described in `ambiguities` when it is given.
    """
    changed = changed_lines(diff)
    coverage = line_coverage(report)
    root = Path.cwd().as_posix()
    entries = {_under_root(name, root): name for name in coverage}
    # An absolute entry under the working directory names exactly one file once it is stripped.
    exact = {entry for entry, name in entries.items() if entry != name}
    fits = _fits(entries, tracked, exact)
    resolved = _resolve(fits)
    if ambiguities is not None:
        ambiguities += _ambiguities(fits, resolved, changed)
    # Two entries naming one file are merged by line number, as the overall check merges
    # duplicate records, so the file's lines are neither counted twice nor split.
    owners: dict[str, list[str]] = defaultdict(list)
    for entry in sorted(resolved):
        owners[resolved[entry]].append(entry)
    matched = {}
    for path, names in owners.items():
        hits: dict[int, bool] = {}
        for entry in names:
            for number, hit in coverage[entries[entry]].items():
                hits[number] = hits.get(number, False) or hit
        counted = [hits[number] for number in changed.get(path, ()) if number in hits]
        if counted:
            matched[path] = (sum(counted), len(counted))
    if not matched:
        return None
    covered = sum(c for c, _ in matched.values())
    total = sum(t for _, t in matched.values())
    return _percent(covered, total, report), matched


def read_baseline(path: Path) -> float | None:
    """Return the recorded overall coverage, or None when no baseline exists yet."""
    if not path.is_file():
        return None
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["overall"])
    except (ValueError, KeyError, TypeError) as exc:
        raise GateError(f'{path}: baseline must be JSON like {{"overall": 83.2}}') from exc


def evaluate(
    overall: float,
    min_coverage: float,
    baseline: float | None,
    baseline_margin: float | None = None,
) -> list[tuple[str, str, bool]]:
    """Return (check, detail, passed) rows for every check that applies."""
    rows = [("Overall", f"{overall:.2f}% (min {min_coverage:g}%)", overall >= min_coverage)]
    if baseline is not None:
        # Baselines are written from the two-decimal display value, so compare at that precision.
        passed = round(overall, 2) >= round(baseline, 2)
        rows.append(("Ratchet", f"{overall:.2f}% (baseline {baseline:.2f}%)", passed))
        if baseline_margin is not None:
            headroom = round(round(overall, 2) - round(baseline, 2), 2)
            detail = f"{headroom:+.2f} points from baseline (max +{baseline_margin:g})"
            rows.append(("Baseline", detail, headroom <= baseline_margin))
    return rows


def evaluate_changed(
    percent: float, files: dict[str, tuple[int, int]], min_changed: float
) -> tuple[str, str, bool]:
    covered = sum(c for c, _ in files.values())
    total = sum(t for _, t in files.values())
    noun = "file" if len(files) == 1 else "files"
    detail = (
        f"{percent:.2f}% ({covered}/{total} lines in {len(files)} {noun}, min {min_changed:g}%)"
    )
    return ("Changed lines", detail, percent >= min_changed)


PASS_MARK = "✅"
FAIL_MARK = "❌"
# A pull request can touch hundreds of files, and a comment that long goes unread.
MAX_FILE_ROWS = 20


def render_summary(
    rows: list[tuple[str, str, bool]],
    files: dict[str, tuple[int, int]] | None = None,
    min_changed: float | None = None,
) -> str:
    lines = ["### Coverage", "", "| Check | Result | Status |", "| --- | --- | --- |"]
    lines += [
        f"| {name} | {detail} | {PASS_MARK if ok else FAIL_MARK} |" for name, detail, ok in rows
    ]
    if files:
        # The changed-lines figure is a combined one, so list the files with the lowest
        # coverage first to point at where tests are missing.
        ranked = sorted(
            (covered * 100 / total, name, covered, total)
            for name, (covered, total) in files.items()
        )
        lines += ["", "| File | Changed lines covered | Status |", "| --- | --- | --- |"]
        for percent, name, covered, total in ranked[:MAX_FILE_ROWS]:
            status = (
                "" if min_changed is None else PASS_MARK if percent >= min_changed else FAIL_MARK
            )
            lines.append(f"| `{name}` | {percent:.2f}% ({covered}/{total}) | {status} |")
        if len(ranked) > MAX_FILE_ROWS:
            lines += ["", f"{len(ranked) - MAX_FILE_ROWS} more changed files are not shown."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__.split("\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-coverage", type=float, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-margin", type=float)
    parser.add_argument("--diff", type=Path)
    parser.add_argument("--min-changed-coverage", type=float)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args(argv)
    if args.baseline_margin is not None and args.baseline_margin < 0:
        parser.error("--baseline-margin must not be negative")
    if (args.diff is None) != (args.min_changed_coverage is None):
        parser.error("--diff and --min-changed-coverage must be used together")

    changed = None
    ambiguities: list[str] = []
    try:
        overall = overall_coverage(args.report)
        baseline = read_baseline(args.baseline) if args.baseline else None
        if args.diff:
            changed = changed_coverage(args.report, args.diff, tracked_files(), ambiguities)
    except GateError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    for note in ambiguities:
        print(f"::warning::{note}")

    if args.baseline and baseline is None:
        # A mistyped path would otherwise disable the ratchet without any sign.
        print(f"::notice::No baseline at {args.baseline}; the ratchet check is skipped.")

    rows = evaluate(overall, args.min_coverage, baseline, args.baseline_margin)
    changed_files = None
    if args.diff and changed is None:
        print(
            "::notice::No changed line appears in the coverage report; "
            "the changed lines check is skipped."
        )
    elif changed is not None:
        changed_files = changed[1]
        rows.append(evaluate_changed(changed[0], changed_files, args.min_changed_coverage))
    summary = render_summary(rows, changed_files, args.min_changed_coverage)
    # The marks are not encodable in a legacy Windows console codepage.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(summary)
    if args.summary_file:
        args.summary_file.write_text(summary, encoding="utf-8")

    if all(ok for _, _, ok in rows):
        return 0
    failed = [name for name, _, ok in rows if not ok]
    # Without this, a stale baseline reads like a coverage drop.
    hint = ""
    if "Baseline" in failed:
        hint = f' Raise "overall" to {overall:.2f} in {args.baseline}.'
    if args.warn_only:
        print(f"::warning::Coverage is outside the configured thresholds (warn-only).{hint}")
        return 0
    print(f"::error::Coverage check failed: {', '.join(failed)}.{hint}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
