"""Apply coverage thresholds to a JaCoCo, Cobertura, or LCOV report.

Two independent checks:
    overall  - total line coverage must be >= --min-coverage
    ratchet  - with --baseline, total line coverage must not fall below the value
               recorded there, a JSON file of the form {"overall": 83.2}

A third check keeps the baseline current. With --baseline-margin, total line coverage
must not exceed the baseline by more than that many percentage points, so a change
that raises coverage also raises the file. It applies only when a baseline exists.

A fourth check holds new work to a standard regardless of the overall figure. With
--min-changed-coverage and --changed-files (a file of repo-relative paths, one per line),
the combined line coverage of the changed files that appear in the report must be
>= that minimum. Changed files the report does not cover, such as tests or docs, are
ignored, and the check is skipped when none appear in it.

With --warn-only a violation is reported as a warning and the exit code stays 0,
so teams can adopt the gate without failing their jobs.

Exit codes:
    0  - all checks passed or skipped, or a violation under --warn-only
    2  - at least one threshold was violated
    1  - error (unreadable or empty report, unknown format, malformed baseline)

Usage:
    python3 coverage_gate.py <report> --min-coverage 80 \\
        [--baseline coverage-baseline.json] [--baseline-margin 1] \\
        [--changed-files changed.txt --min-changed-coverage 80] [--summary-file summary.md] \\
        [--warn-only]
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
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
    found = hit = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("LF:"):
            found += int(line[3:])
        elif line.startswith("LH:"):
            hit += int(line[3:])
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


def _files_xml(path: Path) -> dict[str, tuple[int, int]]:
    root = ET.parse(path).getroot()
    if root.tag == "report":
        # JaCoCo names a file by its package directory plus the source file name.
        files = {}
        for package in root.findall("package"):
            for source in package.findall("sourcefile"):
                for counter in source.findall("counter"):
                    if counter.get("type") == "LINE":
                        covered = int(counter.get("covered", 0))
                        total = covered + int(counter.get("missed", 0))
                        name = f"{package.get('name', '')}/{source.get('name')}"
                        files[_normalise(name).lstrip("/")] = (covered, total)
        return files
    if root.tag == "coverage":
        # Inner classes share a file, so merge by line number before counting.
        lines: dict[str, dict[str, bool]] = {}
        for cls in root.iter("class"):
            seen = lines.setdefault(_normalise(cls.get("filename", "")), {})
            for line in cls.iter("line"):
                number = line.get("number", "")
                seen[number] = seen.get(number, False) or int(line.get("hits", 0)) > 0
        return {name: (sum(hit.values()), len(hit)) for name, hit in lines.items()}
    raise GateError(f"{path}: not a recognised JaCoCo or Cobertura report")


def _files_lcov(path: Path) -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    name = ""
    found = hit = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SF:"):
            name, found, hit = _normalise(line[3:]), 0, 0
        elif line.startswith("LF:"):
            found = int(line[3:])
        elif line.startswith("LH:"):
            hit = int(line[3:])
        elif line == "end_of_record" and name:
            covered, total = files.get(name, (0, 0))
            files[name] = (covered + hit, total + found)
    return files


def file_coverage(path: Path) -> dict[str, tuple[int, int]]:
    """Return (covered lines, total lines) for each file in the report, keyed by its path."""
    try:
        files = _files_xml(path) if path.suffix == ".xml" else _files_lcov(path)
    except (ET.ParseError, ValueError) as exc:
        raise GateError(f"{path}: unreadable coverage report ({exc})") from exc
    return files


def _same_file(changed: str, reported: str) -> bool:
    # Reports name files relative to a source root and `changed` is relative to the repo
    # root, so one is normally a path suffix of the other. Absolute LCOV paths reverse it.
    return (
        changed == reported or changed.endswith("/" + reported) or reported.endswith("/" + changed)
    )


def changed_coverage(
    report: Path, changed_files: Path
) -> tuple[float, dict[str, tuple[int, int]]] | None:
    """Return combined coverage of the changed files in the report and each file's counts.

    Returns None when no changed file is in the report.
    """
    if not changed_files.is_file():
        raise GateError(f"changed files list not found: {changed_files}")
    changed = [_normalise(line) for line in changed_files.read_text(encoding="utf-8").splitlines()]
    changed = [name for name in changed if name]
    # A file with no executable lines, such as an interface, says nothing about coverage.
    matched = {
        name: counts
        for name, counts in file_coverage(report).items()
        if counts[1] > 0 and any(_same_file(c, name) for c in changed)
    }
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
    detail = f"{percent:.2f}% across {len(files)} files (min {min_changed:g}%)"
    return ("Changed files", detail, percent >= min_changed)


def render_summary(
    rows: list[tuple[str, str, bool]], files: dict[str, tuple[int, int]] | None = None
) -> str:
    lines = ["### Coverage", "", "| Check | Result | Status |", "| --- | --- | --- |"]
    lines += [f"| {name} | {detail} | {'Pass' if ok else 'Fail'} |" for name, detail, ok in rows]
    # The changed-files figure is a combined one, so name the files pulling it down.
    gaps = sorted(
        (
            (covered * 100 / total, name)
            for name, (covered, total) in (files or {}).items()
            if covered < total
        )
    )[:5]
    if gaps:
        lines += ["", "Least covered changed files:", ""]
        lines += [f"- `{name}`: {percent:.2f}%" for percent, name in gaps]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__.split("\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-coverage", type=float, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-margin", type=float)
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--min-changed-coverage", type=float)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args(argv)
    if args.baseline_margin is not None and args.baseline_margin < 0:
        parser.error("--baseline-margin must not be negative")
    if (args.changed_files is None) != (args.min_changed_coverage is None):
        parser.error("--changed-files and --min-changed-coverage must be used together")

    changed = None
    try:
        overall = overall_coverage(args.report)
        baseline = read_baseline(args.baseline) if args.baseline else None
        if args.changed_files:
            changed = changed_coverage(args.report, args.changed_files)
    except GateError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if args.baseline and baseline is None:
        # A mistyped path would otherwise disable the ratchet without any sign.
        print(f"::notice::No baseline at {args.baseline}; the ratchet check is skipped.")

    rows = evaluate(overall, args.min_coverage, baseline, args.baseline_margin)
    changed_files = None
    if args.changed_files and changed is None:
        print(
            "::notice::No changed file appears in the coverage report; "
            "the changed files check is skipped."
        )
    elif changed is not None:
        changed_files = changed[1]
        rows.append(evaluate_changed(changed[0], changed_files, args.min_changed_coverage))
    summary = render_summary(rows, changed_files)
    print(summary)
    if args.summary_file:
        args.summary_file.write_text(summary)

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
