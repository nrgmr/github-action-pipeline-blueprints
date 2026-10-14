import json
import re
import shutil
import subprocess
from pathlib import Path

import coverage_gate
import pytest

JACOCO = """<?xml version="1.0"?>
<report name="x"><package name="p"><counter type="LINE" missed="1" covered="1"/></package>
<counter type="INSTRUCTION" missed="75" covered="25"/>
<counter type="LINE" missed="20" covered="80"/><counter type="BRANCH" missed="5" covered="5"/>
</report>"""

COBERTURA = '<coverage lines-valid="50" lines-covered="40" line-rate="0.8"></coverage>'
LCOV = "SF:a.ts\nLF:10\nLH:9\nend_of_record\nSF:b.ts\nLF:10\nLH:5\nend_of_record\n"


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


class TestOverallCoverage:
    def test_jacoco_uses_report_level_line_counter(self, tmp_path):
        assert coverage_gate.overall_coverage(write(tmp_path, "j.xml", JACOCO)) == 80.0

    def test_jacoco_without_line_counter_errors(self, tmp_path):
        body = '<report name="x"><counter type="BRANCH" missed="1" covered="1"/></report>'
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "j.xml", body))

    def test_jacoco_instruction_metric_uses_instruction_counter(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        assert coverage_gate.overall_coverage(report, "instruction") == 25.0

    def test_jacoco_without_instruction_counter_errors(self, tmp_path):
        body = '<report name="x"><counter type="LINE" missed="1" covered="1"/></report>'
        with pytest.raises(coverage_gate.GateError, match="INSTRUCTION"):
            coverage_gate.overall_coverage(write(tmp_path, "j.xml", body), "instruction")

    def test_instruction_metric_rejects_cobertura(self, tmp_path):
        with pytest.raises(coverage_gate.GateError, match="only for JaCoCo"):
            coverage_gate.overall_coverage(write(tmp_path, "c.xml", COBERTURA), "instruction")

    def test_instruction_metric_rejects_lcov(self, tmp_path):
        with pytest.raises(coverage_gate.GateError, match="only for JaCoCo"):
            coverage_gate.overall_coverage(write(tmp_path, "lcov.info", LCOV), "instruction")

    def test_cobertura_lines_counts(self, tmp_path):
        assert coverage_gate.overall_coverage(write(tmp_path, "c.xml", COBERTURA)) == 80.0

    def test_lcov_sums_across_files(self, tmp_path):
        assert coverage_gate.overall_coverage(write(tmp_path, "lcov.info", LCOV)) == 70.0

    def test_lcov_merges_repeated_records_for_one_file(self, tmp_path):
        # Two traces of one file cover line 1 once between them, so one line of two is
        # covered. Summing the records would report 25%.
        body = (
            "SF:a.ts\nDA:1,1\nDA:2,0\nLF:2\nLH:1\nend_of_record\n"
            "SF:a.ts\nDA:1,0\nDA:2,0\nLF:2\nLH:0\nend_of_record\n"
        )
        assert coverage_gate.overall_coverage(write(tmp_path, "lcov.info", body)) == 50.0

    def test_empty_lcov_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "lcov.info", ""))

    def test_non_lcov_file_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "report.json", "{}"))

    def test_jacoco_with_zero_lines_errors(self, tmp_path):
        body = '<report name="x"><counter type="LINE" missed="0" covered="0"/></report>'
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "j.xml", body))

    def test_threshold_is_not_rounded_up(self, tmp_path):
        body = '<coverage lines-valid="100000" lines-covered="79996"></coverage>'
        assert coverage_gate.overall_coverage(write(tmp_path, "c.xml", body)) < 80

    def test_unknown_xml_root_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "x.xml", "<other/>"))

    def test_malformed_xml_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(write(tmp_path, "x.xml", "<report"))

    def test_missing_file_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.overall_coverage(tmp_path / "nope.xml")


def _jacoco_lines(*covered: bool) -> str:
    return "".join(
        f'<line nr="{number}" mi="{0 if hit else 1}" ci="{1 if hit else 0}"/>'
        for number, hit in enumerate(covered, 1)
    )


# A.java: lines 1-9 covered and 10 missed. B.java: lines 1-5 covered and 6-10 missed.
JACOCO_FILES = f"""<?xml version="1.0"?>
<report name="x">
<package name="com/acme">
<sourcefile name="A.java">{_jacoco_lines(*[True] * 9, False)}</sourcefile>
<sourcefile name="B.java">{_jacoco_lines(*[True] * 5, *[False] * 5)}</sourcefile>
<sourcefile name="I.java"><counter type="BRANCH" missed="0" covered="0"/></sourcefile></package>
<counter type="LINE" missed="6" covered="14"/></report>"""

COBERTURA_FILES = """<coverage lines-valid="4" lines-covered="3">
<packages><package><classes>
<class filename="app/a.py"><lines>
<line number="1" hits="1"/><line number="2" hits="0"/></lines></class>
<class filename="app/a.py"><lines>
<line number="2" hits="3"/><line number="3" hits="1"/></lines></class>
<class filename="app/b.py"><lines><line number="1" hits="0"/></lines></class>
</classes></package></packages></coverage>"""

LCOV_LINES = (
    "SF:a.ts\nDA:1,3\nDA:2,0,checksum\nend_of_record\nSF:a.ts\nDA:2,1\nDA:3,0\nend_of_record\n"
)


def diff_for(tmp_path: Path, changes: dict[str, list[str]]) -> Path:
    """Write a `git diff -U0` that changes each file at the given hunks, such as "1,10" or "4"."""
    rows = []
    for name, hunks in changes.items():
        rows += [f"diff --git a/{name} b/{name}", f"--- a/{name}", f"+++ b/{name}"]
        rows += [f"@@ -0,0 +{hunk} @@" for hunk in hunks]
    return write(tmp_path, "changes.diff", "\n".join(rows) + "\n")


def lcov_for(tmp_path: Path, files: dict[str, bool]) -> Path:
    """Write an LCOV report that has one executable line, line 1, per file."""
    body = "".join(f"SF:{name}\nDA:1,{int(hit)}\nend_of_record\n" for name, hit in files.items())
    return write(tmp_path, "lcov.info", body)


class TestLineCoverage:
    def test_jacoco_reads_each_line_of_a_source_file(self, tmp_path):
        lines = coverage_gate.line_coverage(write(tmp_path, "j.xml", JACOCO_FILES))
        assert lines["com/acme/A.java"] == {**{n: True for n in range(1, 10)}, 10: False}
        assert lines["com/acme/B.java"] == {n: n <= 5 for n in range(1, 11)}
        assert lines["com/acme/I.java"] == {}

    def test_jacoco_merges_repeated_source_files(self, tmp_path):
        body = (
            '<report name="x"><package name="p">'
            f'<sourcefile name="A.java">{_jacoco_lines(True, False)}</sourcefile>'
            f'<sourcefile name="A.java">{_jacoco_lines(False, False)}</sourcefile>'
            "</package></report>"
        )
        lines = coverage_gate.line_coverage(write(tmp_path, "j.xml", body))
        assert lines == {"p/A.java": {1: True, 2: False}}

    def test_cobertura_merges_classes_sharing_a_file(self, tmp_path):
        lines = coverage_gate.line_coverage(write(tmp_path, "c.xml", COBERTURA_FILES))
        assert lines == {"app/a.py": {1: True, 2: True, 3: True}, "app/b.py": {1: False}}

    def test_lcov_merges_records_for_one_file(self, tmp_path):
        lines = coverage_gate.line_coverage(write(tmp_path, "lcov.info", LCOV_LINES))
        assert lines == {"a.ts": {1: True, 2: True, 3: False}}

    def test_unknown_xml_root_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.line_coverage(write(tmp_path, "x.xml", "<other/>"))


class TestChangedLines:
    def test_reads_added_ranges_and_ignores_deletions(self, tmp_path):
        diff = write(
            tmp_path,
            "d.diff",
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
            "@@ -3 +3 @@\n-old\n+new\n"
            "@@ -10,2 +12,3 @@\n"
            "@@ -20,2 +25,0 @@\n-gone\n-gone\n",
        )
        assert coverage_gate.changed_lines(diff) == {"x.py": {3, 12, 13, 14}}

    def test_deleted_files_are_skipped(self, tmp_path):
        diff = write(
            tmp_path,
            "d.diff",
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n",
        )
        assert coverage_gate.changed_lines(diff) == {}

    def test_a_changed_file_that_is_not_utf8_does_not_fail_the_read(self, tmp_path):
        # Java .properties files are ISO-8859-1, so a diff can carry bytes UTF-8 rejects.
        diff = tmp_path / "d.diff"
        diff.write_bytes(
            b"diff --git a/x.properties b/x.properties\n--- a/x.properties\n"
            b"+++ b/x.properties\n@@ -1 +1 @@\n+caf\xe9=1\n"
        )
        assert coverage_gate.changed_lines(diff) == {"x.properties": {1}}

    def test_a_form_feed_in_a_changed_line_does_not_start_a_new_row(self, tmp_path):
        diff = write(
            tmp_path,
            "d.diff",
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+a\x0c@@ -9 +9 @@\n",
        )
        assert coverage_gate.changed_lines(diff) == {"x.py": {1}}

    def test_strips_the_tab_git_adds_after_a_path_with_spaces(self, tmp_path):
        diff = write(
            tmp_path,
            "d.diff",
            "diff --git a/my file.py b/my file.py\n--- a/my file.py\t\n+++ b/my file.py\t\n"
            "@@ -1 +1 @@\n",
        )
        assert coverage_gate.changed_lines(diff) == {"my file.py": {1}}

    def test_a_line_that_looks_like_a_header_is_content(self, tmp_path):
        diff = write(
            tmp_path,
            "d.diff",
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
            "@@ -1 +1,2 @@\n+++ b/other.py\n+text\n",
        )
        assert coverage_gate.changed_lines(diff) == {"x.py": {1, 2}}

    def test_missing_diff_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.changed_lines(tmp_path / "nope.diff")


# The error must name both conditions, since a wrong directory fails as quietly as no checkout.
ERROR_HINT = "git checkout and must run in the directory the diff is relative to"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def init_repo(path: Path, tracked: list[str], untracked: list[str] = ()) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    for name in [*tracked, *untracked]:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text("x\n")
    subprocess.run(["git", "add", "--", *tracked], cwd=path, check=True)


def enter_checkout(tmp_path: Path, monkeypatch, tracked: list[str]) -> None:
    init_repo(tmp_path, tracked)
    monkeypatch.chdir(tmp_path)


def leave_checkout(tmp_path: Path, monkeypatch) -> None:
    # Stop git from searching parent directories, so the directory is not in a checkout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)


class TestChangedCoverage:
    def test_counts_only_changed_executable_lines(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(
            tmp_path,
            {"svc/src/main/java/com/acme/B.java": ["1,3", "6"], "README.md": ["1,5"]},
        )
        tracked = ["svc/src/main/java/com/acme/A.java", "svc/src/main/java/com/acme/B.java"]
        percent, files = coverage_gate.changed_coverage(report, diff, [*tracked, "README.md"])
        assert percent == 75.0
        assert files == {"svc/src/main/java/com/acme/B.java": (3, 4)}

    def test_an_untested_edit_in_a_well_covered_file_fails(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"com/acme/A.java": ["10"]})
        percent, _ = coverage_gate.changed_coverage(report, diff, ["com/acme/A.java"])
        assert percent == 0.0

    def test_lines_the_report_does_not_list_are_ignored(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"com/acme/B.java": ["1,5", "40,3"]})
        percent, files = coverage_gate.changed_coverage(report, diff, ["com/acme/B.java"])
        assert (percent, files) == (100.0, {"com/acme/B.java": (5, 5)})

    def test_files_are_reported_by_repository_path(self, tmp_path):
        # JaCoCo names the file com/acme/B.java, which a reviewer cannot open from a comment.
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        tracked = ["svc/src/main/java/com/acme/B.java"]
        diff = diff_for(tmp_path, {tracked[0]: ["1"]})
        _, files = coverage_gate.changed_coverage(report, diff, tracked)
        assert list(files) == tracked

    def test_a_changed_file_matches_only_its_own_report_entry(self, tmp_path):
        # `pytest --cov=app` names files relative to app/, so app/sub/utils.py is reported
        # as sub/utils.py and app/utils.py as utils.py. Both are suffixes of the change.
        report = write(
            tmp_path,
            "c.xml",
            '<coverage><class filename="utils.py"><line number="1" hits="1"/></class>'
            '<class filename="sub/utils.py"><line number="1" hits="0"/></class></coverage>',
        )
        diff = diff_for(tmp_path, {"app/sub/utils.py": ["1"]})
        tracked = ["app/utils.py", "app/sub/utils.py"]
        percent, files = coverage_gate.changed_coverage(report, diff, tracked)
        assert (percent, files) == (0.0, {"app/sub/utils.py": (0, 1)})

    def test_one_report_entry_serves_one_changed_file(self, tmp_path):
        # Both files fit the utils.py entry. It names the one nearest the root, so merging
        # app/sub/utils.py into it would credit one file with another's lines.
        report = write(
            tmp_path,
            "c.xml",
            '<coverage><class filename="utils.py">'
            '<line number="1" hits="1"/><line number="2" hits="0"/></class></coverage>',
        )
        diff = diff_for(tmp_path, {"app/sub/utils.py": ["2"], "app/utils.py": ["1"]})
        tracked = ["app/utils.py", "app/sub/utils.py"]
        percent, files = coverage_gate.changed_coverage(report, diff, tracked)
        assert (percent, files) == (100.0, {"app/utils.py": (1, 1)})

    def test_two_entries_naming_one_file_count_it_once(self, tmp_path):
        report = lcov_for(tmp_path, {"utils.py": False, "app/utils.py": True})
        diff = diff_for(tmp_path, {"app/utils.py": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, ["app/utils.py"])
        assert (percent, files) == (100.0, {"app/utils.py": (1, 1)})

    def test_two_entries_naming_one_file_merge_their_hits(self, tmp_path):
        # The overall check counts a line covered when any record covers it, so this must too.
        report = write(
            tmp_path,
            "lcov.info",
            "SF:src/a.ts\nDA:1,0\nend_of_record\nSF:a.ts\nDA:1,1\nend_of_record\n",
        )
        diff = diff_for(tmp_path, {"src/a.ts": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, ["src/a.ts"])
        assert (percent, files) == (100.0, {"src/a.ts": (1, 1)})

    def test_a_root_file_is_not_matched_to_the_same_name_in_a_subdirectory(
        self, tmp_path, monkeypatch
    ):
        # With --relative the diff is relative to the working directory, so a root index.ts
        # must not take the coverage of src/index.ts.
        project = tmp_path / "ui"
        project.mkdir()
        monkeypatch.chdir(project)
        report = write(
            tmp_path, "lcov.info", f"SF:{project.as_posix()}/src/index.ts\nDA:1,0\nend_of_record\n"
        )
        tracked = ["index.ts", "src/index.ts"]
        assert (
            coverage_gate.changed_coverage(report, diff_for(tmp_path, {"index.ts": ["1"]}), tracked)
            is None
        )
        percent, _ = coverage_gate.changed_coverage(
            report, diff_for(tmp_path, {"src/index.ts": ["1"]}), tracked
        )
        assert percent == 0.0

    def test_sums_lines_across_files_rather_than_averaging(self, tmp_path):
        covered = "".join(f"DA:{n},1\n" for n in range(1, 91))
        missed = "".join(f"DA:{n},0\n" for n in range(1, 11))
        body = f"SF:a.ts\n{covered}end_of_record\nSF:b.ts\n{missed}end_of_record\n"
        report = write(tmp_path, "lcov.info", body)
        diff = diff_for(tmp_path, {"a.ts": ["1,90"], "b.ts": ["1,10"]})
        percent, _ = coverage_gate.changed_coverage(report, diff, ["a.ts", "b.ts"])
        assert percent == 90.0

    def test_no_matching_file_returns_none(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"docs/x.md": ["1,5"]})
        assert coverage_gate.changed_coverage(report, diff, ["docs/x.md"]) is None

    def test_does_not_match_on_a_partial_file_name(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"src/com/acme/XA.java": ["1,5"]})
        assert coverage_gate.changed_coverage(report, diff, ["src/com/acme/XA.java"]) is None

    def test_an_entry_naming_no_tracked_file_is_ignored(self, tmp_path):
        # A generated source is reported but not committed, so no changed file is it.
        report = lcov_for(tmp_path, {"gen/A.java": True})
        diff = diff_for(tmp_path, {"src/A.java": ["1"]})
        assert coverage_gate.changed_coverage(report, diff, ["src/A.java"]) is None

    def test_changes_with_no_executable_line_return_none(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"com/acme/A.java": ["50,5"]})
        assert coverage_gate.changed_coverage(report, diff, ["com/acme/A.java"]) is None

    def test_a_deletion_only_hunk_returns_none(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        diff = diff_for(tmp_path, {"com/acme/A.java": ["3,0"]})
        assert coverage_gate.changed_coverage(report, diff, ["com/acme/A.java"]) is None

    def test_a_report_written_under_another_checkout_root_matches(self, tmp_path):
        # A report produced in a container names /app/ui/src/a.ts, whatever the runner path is.
        report = write(
            tmp_path,
            "lcov.info",
            "SF:/home/runner/work/r/r/ui/src/a.ts\nDA:1,1\nDA:2,0\nend_of_record\n",
        )
        diff = diff_for(tmp_path, {"ui/src/a.ts": ["1,2"]})
        percent, files = coverage_gate.changed_coverage(report, diff, ["ui/src/a.ts"])
        assert (percent, files) == (50.0, {"ui/src/a.ts": (1, 2)})

    def test_absolute_report_paths_under_the_working_directory_match(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        report = lcov_for(tmp_path, {f"{tmp_path.as_posix()}/src/a.ts": False})
        diff = diff_for(tmp_path, {"src/a.ts": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, ["src/a.ts"])
        assert (percent, files) == (0.0, {"src/a.ts": (0, 1)})

    def test_an_absolute_entry_under_the_working_directory_is_not_matched_by_suffix(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        report = lcov_for(tmp_path, {f"{tmp_path.as_posix()}/src/a.ts": True})
        diff = diff_for(tmp_path, {"vendor/src/a.ts": ["1"]})
        notes: list[str] = []
        tracked = ["src/a.ts", "vendor/src/a.ts"]
        assert coverage_gate.changed_coverage(report, diff, tracked, notes) is None
        assert notes == []

    def test_windows_separators_are_normalised(self, tmp_path):
        report = write(tmp_path, "lcov.info", "SF:src\\a.ts\nDA:1,1\nend_of_record\n")
        diff = diff_for(tmp_path, {"ui/src/a.ts": ["1"]})
        assert coverage_gate.changed_coverage(report, diff, ["ui/src/a.ts"])

    def test_missing_diff_errors(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.changed_coverage(report, tmp_path / "nope.diff", [])


class TestSourceRootResolution:
    # `pytest --cov=app` drops the app/ prefix, so app/utils.py is reported as utils.py.
    TRACKED = ["app/utils.py", "app/main.py", "app/migrations/utils.py"]

    def test_a_file_excluded_from_the_report_is_not_credited_with_a_same_named_file(self, tmp_path):
        # app/migrations/ is omitted from coverage, so the utils.py entry is app/utils.py.
        report = lcov_for(tmp_path, {"utils.py": True, "main.py": True})
        diff = diff_for(tmp_path, {"app/migrations/utils.py": ["1"]})
        assert coverage_gate.changed_coverage(report, diff, self.TRACKED) is None

    def test_the_file_the_entry_names_is_still_counted(self, tmp_path):
        report = lcov_for(tmp_path, {"utils.py": False, "main.py": True})
        diff = diff_for(tmp_path, {"app/utils.py": ["1"], "app/migrations/utils.py": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, self.TRACKED)
        assert (percent, files) == (0.0, {"app/utils.py": (0, 1)})

    def test_an_included_file_matches_its_own_longer_entry(self, tmp_path):
        report = lcov_for(
            tmp_path, {"utils.py": True, "migrations/utils.py": False, "main.py": True}
        )
        diff = diff_for(tmp_path, {"app/migrations/utils.py": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, self.TRACKED)
        assert (percent, files) == (0.0, {"app/migrations/utils.py": (0, 1)})

    def test_the_prefix_most_entries_share_names_the_file(self, tmp_path):
        tracked = ["app/utils.py", "app/main.py", "app/routes.py", "other/utils.py"]
        report = lcov_for(tmp_path, {"utils.py": True, "main.py": True, "routes.py": True})
        other = diff_for(tmp_path, {"other/utils.py": ["1"]})
        assert coverage_gate.changed_coverage(report, other, tracked) is None
        app = diff_for(tmp_path, {"app/utils.py": ["1"]})
        percent, _ = coverage_gate.changed_coverage(report, app, tracked)
        assert percent == 100.0

    def test_a_tie_goes_to_the_path_nearest_the_root(self, tmp_path):
        tracked = ["a/utils.py", "a/b/utils.py"]
        report = lcov_for(tmp_path, {"utils.py": True})
        deeper = diff_for(tmp_path, {"a/b/utils.py": ["1"]})
        assert coverage_gate.changed_coverage(report, deeper, tracked) is None
        nearer = diff_for(tmp_path, {"a/utils.py": ["1"]})
        assert coverage_gate.changed_coverage(report, nearer, tracked)

    def test_entries_under_different_source_roots_each_match(self, tmp_path):
        tracked = ["a/src/p/A.java", "b/src/q/B.java"]
        report = lcov_for(tmp_path, {"p/A.java": True, "q/B.java": False})
        diff = diff_for(tmp_path, {"a/src/p/A.java": ["1"], "b/src/q/B.java": ["1"]})
        percent, files = coverage_gate.changed_coverage(report, diff, tracked)
        assert (percent, files) == (50.0, {"a/src/p/A.java": (1, 1), "b/src/q/B.java": (0, 1)})


def resolve(entries, tracked):
    return coverage_gate._resolve(coverage_gate._fits(entries, tracked))


class TestFits:
    def test_lists_every_tracked_file_an_entry_could_name_in_order(self):
        tracked = ["lib/utils.py", "app/utils.py", "app/main.py"]
        assert coverage_gate._fits(["utils.py"], tracked) == {
            "utils.py": ["app/utils.py", "lib/utils.py"]
        }

    def test_omits_entries_that_fit_nothing(self):
        assert coverage_gate._fits(["gone.py"], ["app/utils.py"]) == {}

    def test_an_absolute_entry_fits_the_tracked_paths_it_ends_with(self):
        fits = coverage_gate._fits(["/srv/ui/a.ts"], ["a.ts", "ui/a.ts", "lib/a.ts"])
        assert fits == {"/srv/ui/a.ts": ["a.ts", "ui/a.ts"]}

    def test_an_exact_entry_fits_only_itself(self):
        fits = coverage_gate._fits(["src/a.ts"], ["src/a.ts", "vendor/src/a.ts"], {"src/a.ts"})
        assert fits == {"src/a.ts": ["src/a.ts"]}

    def test_an_exact_entry_that_is_not_tracked_fits_nothing(self):
        assert coverage_gate._fits(["src/a.ts"], ["vendor/src/a.ts"], {"src/a.ts"}) == {}


class TestAmbiguities:
    TRACKED = ["app/utils.py", "app/main.py", "app/migrations/utils.py"]

    def run(self, tmp_path, report_files, changes, tracked=None):
        report = lcov_for(tmp_path, report_files)
        notes: list[str] = []
        coverage_gate.changed_coverage(
            report, diff_for(tmp_path, changes), tracked or self.TRACKED, notes
        )
        return notes

    def test_warns_when_a_changed_file_is_a_candidate_that_lost(self, tmp_path):
        notes = self.run(
            tmp_path, {"utils.py": True, "main.py": True}, {"app/migrations/utils.py": ["1"]}
        )
        assert notes == [
            "utils.py in the report fits app/migrations/utils.py, app/utils.py; "
            "it is used for app/utils.py. "
            "Set working-directory to the module folder to avoid this."
        ]

    def test_warns_when_the_changed_file_is_the_candidate_that_won(self, tmp_path):
        notes = self.run(tmp_path, {"utils.py": True, "main.py": True}, {"app/utils.py": ["1"]})
        assert len(notes) == 1
        assert "it is used for app/utils.py" in notes[0]

    def test_is_quiet_when_no_candidate_changed(self, tmp_path):
        assert self.run(tmp_path, {"utils.py": True, "main.py": True}, {"app/main.py": ["1"]}) == []

    def test_is_quiet_when_the_other_candidate_is_scored_through_its_own_entry(self, tmp_path):
        notes = self.run(
            tmp_path,
            {"utils.py": True, "sub/utils.py": False},
            {"app/sub/utils.py": ["1"]},
            ["app/utils.py", "app/sub/utils.py"],
        )
        assert notes == []

    def test_is_quiet_when_an_entry_fits_one_file(self, tmp_path):
        tracked = ["app/utils.py", "app/main.py"]
        notes = self.run(tmp_path, {"utils.py": True}, {"app/utils.py": ["1"]}, tracked)
        assert notes == []

    def test_a_candidate_with_only_deleted_lines_is_not_changed(self, tmp_path):
        notes = self.run(tmp_path, {"utils.py": True}, {"app/migrations/utils.py": ["3,0"]})
        assert notes == []

    def test_is_quiet_for_an_absolute_entry(self, tmp_path):
        # An absolute entry names the longest tracked path it ends with, which is no guess.
        tracked = ["a.ts", "src/a.ts"]
        notes = self.run(tmp_path, {"/srv/src/a.ts": True}, {"src/a.ts": ["1"]}, tracked)
        assert notes == []

    def test_each_ambiguous_entry_gets_one_note(self, tmp_path):
        tracked = ["a/utils.py", "b/utils.py", "a/models.py", "b/models.py"]
        changes = {"a/utils.py": ["1"], "b/models.py": ["1"]}
        notes = self.run(tmp_path, {"utils.py": True, "models.py": True}, changes, tracked)
        assert [note.split(" ")[0] for note in notes] == ["models.py", "utils.py"]

    def test_notes_are_optional(self, tmp_path):
        report = lcov_for(tmp_path, {"utils.py": True})
        diff = diff_for(tmp_path, {"app/utils.py": ["1"]})
        assert coverage_gate.changed_coverage(report, diff, self.TRACKED)


class TestResolve:
    def test_maps_an_entry_to_the_one_file_that_ends_with_it(self):
        resolved = resolve(["sub/a.py"], ["app/sub/a.py", "app/b.py"])
        assert resolved == {"sub/a.py": "app/sub/a.py"}

    def test_a_file_at_the_root_matches_an_entry_equal_to_its_path(self):
        assert resolve(["a.py"], ["a.py"]) == {"a.py": "a.py"}

    def test_prefers_the_file_whose_prefix_serves_most_entries(self):
        tracked = ["app/utils.py", "app/main.py", "app/migrations/utils.py"]
        resolved = resolve(["utils.py", "main.py"], tracked)
        assert resolved == {"utils.py": "app/utils.py", "main.py": "app/main.py"}

    def test_a_tie_goes_to_the_shorter_path_then_the_earlier_one(self):
        assert resolve(["u.py"], ["a/b/u.py", "a/u.py"]) == {"u.py": "a/u.py"}
        assert resolve(["u.py"], ["b/u.py", "a/u.py"]) == {"u.py": "a/u.py"}

    def test_omits_entries_that_name_no_file(self):
        assert resolve(["A.java", "x.py"], ["src/XA.java", "src/y.py"]) == {}

    def test_an_absolute_entry_names_the_longest_tracked_path_it_ends_with(self):
        resolved = resolve(["/app/src/a.ts"], ["a.ts", "src/a.ts", "lib/a.ts"])
        assert resolved == {"/app/src/a.ts": "src/a.ts"}

    def test_a_windows_absolute_entry_resolves_the_same_way(self):
        resolved = resolve(["C:/work/ui/a.ts"], ["ui/a.ts"])
        assert resolved == {"C:/work/ui/a.ts": "ui/a.ts"}

    def test_an_absolute_entry_ending_in_no_tracked_path_is_omitted(self):
        assert resolve(["/app/src/a.ts"], ["lib/a.ts"]) == {}

    def test_an_absolute_entry_does_not_count_toward_a_prefix(self):
        # Only relative entries say where the source root is.
        # Counted, the other/ prefix would serve two entries and win the tie.
        tracked = ["z/utils.py", "other/utils.py", "other/x.py"]
        resolved = resolve(["utils.py", "/srv/other/x.py"], tracked)
        assert resolved["utils.py"] == "z/utils.py"


@needs_git
class TestTrackedFiles:
    def test_lists_tracked_files_and_not_untracked_ones(self, tmp_path, monkeypatch):
        init_repo(tmp_path, ["app/a.py", "my file.py"], untracked=["scratch.py"])
        monkeypatch.chdir(tmp_path)
        assert coverage_gate.tracked_files() == {"app/a.py", "my file.py"}

    def test_paths_are_relative_to_the_working_directory(self, tmp_path, monkeypatch):
        init_repo(tmp_path, ["app/a.py", "docs/readme.md"])
        monkeypatch.chdir(tmp_path / "app")
        assert coverage_gate.tracked_files() == {"a.py"}

    def test_outside_a_checkout_errors(self, tmp_path, monkeypatch):
        leave_checkout(tmp_path, monkeypatch)
        with pytest.raises(coverage_gate.GateError, match=ERROR_HINT):
            coverage_gate.tracked_files()


def test_tracked_files_without_git_errors(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(coverage_gate.subprocess, "run", missing)
    with pytest.raises(coverage_gate.GateError, match=ERROR_HINT):
        coverage_gate.tracked_files()


@needs_git
class TestMainInACheckout:
    TRACKED = ["app/utils.py", "app/main.py", "app/migrations/utils.py"]

    def args(self, tmp_path, report_files, changed):
        report = lcov_for(tmp_path, report_files)
        diff = diff_for(tmp_path, changed)
        return [str(report), "--min-coverage", "0", "--diff", str(diff)]

    def test_an_excluded_file_is_skipped_not_scored_against_a_same_named_file(
        self, tmp_path, monkeypatch, capsys
    ):
        enter_checkout(tmp_path, monkeypatch, self.TRACKED)
        args = self.args(
            tmp_path, {"utils.py": True, "main.py": True}, {"app/migrations/utils.py": ["1"]}
        )
        assert coverage_gate.main([*args, "--min-changed-coverage", "99"]) == 0
        assert "::notice::No changed line" in capsys.readouterr().out

    def test_the_file_the_report_names_is_still_held_to_the_minimum(
        self, tmp_path, monkeypatch, capsys
    ):
        enter_checkout(tmp_path, monkeypatch, self.TRACKED)
        args = self.args(tmp_path, {"utils.py": False, "main.py": True}, {"app/utils.py": ["1"]})
        assert coverage_gate.main([*args, "--min-changed-coverage", "50"]) == 2
        assert "| `app/utils.py` | 0.00% (0/1) | ❌ |" in capsys.readouterr().out

    def test_an_ambiguous_entry_is_reported_as_a_warning_annotation(
        self, tmp_path, monkeypatch, capsys
    ):
        enter_checkout(tmp_path, monkeypatch, self.TRACKED)
        args = self.args(
            tmp_path, {"utils.py": True, "main.py": True}, {"app/migrations/utils.py": ["1"]}
        )
        coverage_gate.main([*args, "--min-changed-coverage", "99"])
        assert "::warning::utils.py in the report fits" in capsys.readouterr().out

    def test_an_unambiguous_report_prints_no_warning(self, tmp_path, monkeypatch, capsys):
        enter_checkout(tmp_path, monkeypatch, ["app/utils.py", "app/main.py"])
        args = self.args(tmp_path, {"utils.py": True, "main.py": True}, {"app/utils.py": ["1"]})
        assert coverage_gate.main([*args, "--min-changed-coverage", "50"]) == 0
        assert "::warning::" not in capsys.readouterr().out

    def test_outside_a_checkout_it_is_an_error_not_a_guess(self, tmp_path, monkeypatch, capsys):
        leave_checkout(tmp_path, monkeypatch)
        args = self.args(tmp_path, {"utils.py": False}, {"app/migrations/utils.py": ["1"]})
        assert coverage_gate.main([*args, "--min-changed-coverage", "50"]) == 1
        assert re.search(ERROR_HINT, capsys.readouterr().err)

    def test_the_checkout_is_not_needed_without_the_changed_lines_check(
        self, tmp_path, monkeypatch
    ):
        leave_checkout(tmp_path, monkeypatch)
        report = lcov_for(tmp_path, {"utils.py": True})
        assert coverage_gate.main([str(report), "--min-coverage", "50"]) == 0


class TestBaseline:
    def test_missing_baseline_is_none(self, tmp_path):
        assert coverage_gate.read_baseline(tmp_path / "none.json") is None

    def test_reads_overall(self, tmp_path):
        path = write(tmp_path, "b.json", json.dumps({"overall": 83.2}))
        assert coverage_gate.read_baseline(path) == 83.2

    @pytest.mark.parametrize("body", ["{}", "not json", '{"overall": "x"}'])
    def test_malformed_baseline_errors(self, tmp_path, body):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.read_baseline(write(tmp_path, "b.json", body))


class TestEvaluate:
    def test_overall_only(self):
        rows = coverage_gate.evaluate(79.9, 80, None)
        assert rows == [("Overall", "79.90% (min 80%)", False)]

    def test_ratchet_fails_on_drop(self):
        rows = coverage_gate.evaluate(82, 80, 83.2)
        assert rows[-1] == ("Ratchet", "82.00% (baseline 83.20%)", False)

    def test_ratchet_compares_at_display_precision(self):
        rows = coverage_gate.evaluate(83.2004, 80, 83.2)
        assert rows[-1][2] is True

    def test_ratchet_rounds_baseline_too(self):
        rows = coverage_gate.evaluate(83.254, 80, 83.254)
        assert rows[-1][2] is True

    def test_ratchet_passes_when_equal(self):
        rows = coverage_gate.evaluate(83.2, 80, 83.2)
        assert rows[-1][2] is True

    def test_no_margin_adds_no_row(self):
        assert [r[0] for r in coverage_gate.evaluate(90, 80, 83.2)] == ["Overall", "Ratchet"]

    def test_margin_without_baseline_adds_no_row(self):
        assert [r[0] for r in coverage_gate.evaluate(90, 80, None, 1)] == ["Overall"]

    def test_margin_fails_when_baseline_is_stale(self):
        rows = coverage_gate.evaluate(85, 80, 83.2, 1)
        assert rows[-1] == ("Baseline", "+1.80 points from baseline (max +1)", False)

    def test_margin_passes_within_headroom(self):
        assert coverage_gate.evaluate(84, 80, 83.2, 1)[-1][2] is True

    def test_margin_boundary_is_inclusive(self):
        assert coverage_gate.evaluate(84.2, 80, 83.2, 1)[-1][2] is True

    def test_margin_ignores_float_noise(self):
        assert coverage_gate.evaluate(50.69 + 1e-9, 50, 49.69, 1)[-1][2] is True

    def test_zero_margin_requires_an_exact_baseline(self):
        assert coverage_gate.evaluate(83.21, 80, 83.2, 0)[-1][2] is False
        assert coverage_gate.evaluate(83.2, 80, 83.2, 0)[-1][2] is True


class TestEvaluateChanged:
    def test_detail_uses_the_singular_for_one_file(self):
        _, detail, _ = coverage_gate.evaluate_changed(50.0, {"a.py": (1, 2)}, 40)
        assert "in 1 file," in detail

    def test_detail_uses_the_plural_for_several_files(self):
        _, detail, _ = coverage_gate.evaluate_changed(50.0, {"a.py": (1, 2), "b.py": (1, 2)}, 40)
        assert "in 2 files," in detail


class TestRenderSummary:
    ROWS = [("Overall", "80.00% (min 80%)", True)]

    def test_lists_files_lowest_coverage_first_with_status(self):
        files = {"a/Full.java": (10, 10), "b/Low.java": (1, 10)}
        lines = coverage_gate.render_summary(self.ROWS, files, 50).splitlines()
        assert lines[-2:] == [
            "| `b/Low.java` | 10.00% (1/10) | ❌ |",
            "| `a/Full.java` | 100.00% (10/10) | ✅ |",
        ]

    def test_status_is_blank_without_a_changed_threshold(self):
        summary = coverage_gate.render_summary(self.ROWS, {"a/Full.java": (10, 10)})
        assert "| `a/Full.java` | 100.00% (10/10) |  |" in summary

    def test_caps_file_rows_and_reports_the_rest(self):
        files = {f"f{i}.java": (i, 100) for i in range(coverage_gate.MAX_FILE_ROWS + 3)}
        summary = coverage_gate.render_summary(self.ROWS, files, 50)
        assert summary.count("| `f") == coverage_gate.MAX_FILE_ROWS
        assert "3 more changed files are not shown." in summary

    def test_omits_file_table_without_changed_files(self):
        assert "| File |" not in coverage_gate.render_summary(self.ROWS)

    def test_title_names_the_report_in_the_heading(self):
        summary = coverage_gate.render_summary(self.ROWS, title="api/service")
        assert summary.startswith("### Coverage: api/service\n")

    def test_heading_is_plain_without_a_title(self):
        assert coverage_gate.render_summary(self.ROWS).startswith("### Coverage\n")


class TestMain:
    def test_pass_writes_summary(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        summary = tmp_path / "summary.md"
        code = coverage_gate.main(
            [str(report), "--min-coverage", "80", "--summary-file", str(summary)]
        )
        assert code == 0
        assert "| Overall | 80.00% (min 80%) | ✅ |" in summary.read_text(encoding="utf-8")

    def test_title_option_reaches_the_summary(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        summary = tmp_path / "summary.md"
        args = [str(report), "--min-coverage", "20", "--title", "api/web"]
        assert coverage_gate.main([*args, "--summary-file", str(summary)]) == 0
        assert summary.read_text(encoding="utf-8").startswith("### Coverage: api/web\n")

    def test_instruction_metric_is_named_in_summary(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        summary = tmp_path / "summary.md"
        args = [str(report), "--min-coverage", "20", "--metric", "instruction"]
        assert coverage_gate.main([*args, "--summary-file", str(summary)]) == 0
        text = summary.read_text(encoding="utf-8")
        assert "| Overall (instructions) | 25.00% (min 20%) | ✅ |" in text

    def test_instruction_metric_fails_where_line_passes(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        assert coverage_gate.main([str(report), "--min-coverage", "50"]) == 0
        args = [str(report), "--min-coverage", "50", "--metric", "instruction"]
        assert coverage_gate.main(args) == 2

    def test_instruction_metric_on_non_jacoco_exits_one(self, tmp_path):
        report = write(tmp_path, "lcov.info", LCOV)
        args = [str(report), "--min-coverage", "50", "--metric", "instruction"]
        assert coverage_gate.main(args) == 1

    def test_violation_exits_two(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        assert coverage_gate.main([str(report), "--min-coverage", "90"]) == 2

    def test_missing_baseline_emits_notice(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO)
        args = [str(report), "--min-coverage", "50", "--baseline", str(tmp_path / "none.json")]
        assert coverage_gate.main(args) == 0
        assert "::notice::" in capsys.readouterr().out

    def test_violation_emits_error_annotation(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO)
        coverage_gate.main([str(report), "--min-coverage", "90"])
        assert "::error::Coverage check failed: Overall" in capsys.readouterr().err

    def test_ratchet_violation_exits_two(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        baseline = write(tmp_path, "b.json", json.dumps({"overall": 95}))
        args = [str(report), "--min-coverage", "50", "--baseline", str(baseline)]
        assert coverage_gate.main(args) == 2

    def test_stale_baseline_exits_two_with_a_hint(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO)
        baseline = write(tmp_path, "b.json", json.dumps({"overall": 70}))
        args = [str(report), "--min-coverage", "50", "--baseline", str(baseline)]

        assert coverage_gate.main([*args, "--baseline-margin", "1"]) == 2
        err = capsys.readouterr().err
        assert "Baseline" in err
        assert 'Raise "overall" to 80.00' in err

    def test_baseline_within_margin_passes(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        baseline = write(tmp_path, "b.json", json.dumps({"overall": 79.5}))
        args = [str(report), "--min-coverage", "50", "--baseline", str(baseline)]
        assert coverage_gate.main([*args, "--baseline-margin", "1"]) == 0

    def test_margin_is_skipped_without_a_baseline_file(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        missing = tmp_path / "missing.json"
        args = [str(report), "--min-coverage", "50", "--baseline", str(missing)]
        assert coverage_gate.main([*args, "--baseline-margin", "1"]) == 0

    def test_stale_baseline_under_warn_only_exits_zero(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO)
        baseline = write(tmp_path, "b.json", json.dumps({"overall": 70}))
        args = [str(report), "--min-coverage", "50", "--baseline", str(baseline)]

        assert coverage_gate.main([*args, "--baseline-margin", "1", "--warn-only"]) == 0
        assert 'Raise "overall" to 80.00' in capsys.readouterr().out

    def test_negative_margin_is_an_error(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        args = [str(report), "--min-coverage", "50", "--baseline-margin", "-1"]
        with pytest.raises(SystemExit) as exit_info:
            coverage_gate.main(args)
        assert exit_info.value.code == 1

    def test_warn_only_downgrades_violation(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO)
        assert coverage_gate.main([str(report), "--min-coverage", "90", "--warn-only"]) == 0
        assert "::warning::" in capsys.readouterr().out

    def test_warn_only_does_not_hide_errors(self, tmp_path):
        args = [str(tmp_path / "nope.xml"), "--min-coverage", "80", "--warn-only"]
        assert coverage_gate.main(args) == 1

    def test_unreadable_report_exits_one(self, tmp_path):
        assert coverage_gate.main([str(tmp_path / "nope.xml"), "--min-coverage", "80"]) == 1

    @needs_git
    def test_changed_lines_below_minimum_exits_two(self, tmp_path, monkeypatch, capsys):
        enter_checkout(tmp_path, monkeypatch, ["com/acme/A.java", "com/acme/B.java"])
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = diff_for(tmp_path, {"com/acme/B.java": ["1,10"]})
        args = [str(report), "--min-coverage", "50", "--diff", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80"]) == 2
        captured = capsys.readouterr()
        assert "Changed lines" in captured.err
        assert "| `com/acme/B.java` | 50.00% (5/10) | ❌ |" in captured.out

    @needs_git
    def test_changed_lines_meeting_minimum_passes(self, tmp_path, monkeypatch):
        enter_checkout(tmp_path, monkeypatch, ["com/acme/A.java", "com/acme/B.java"])
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = diff_for(tmp_path, {"com/acme/A.java": ["1,10"]})
        args = [str(report), "--min-coverage", "50", "--diff", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80"]) == 0

    @needs_git
    def test_changed_lines_outside_the_report_skip_with_a_notice(
        self, tmp_path, monkeypatch, capsys
    ):
        enter_checkout(tmp_path, monkeypatch, ["com/acme/A.java", "docs/x.md"])
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = diff_for(tmp_path, {"docs/x.md": ["1,5"]})
        args = [str(report), "--min-coverage", "50", "--diff", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "99"]) == 0
        assert "::notice::No changed line" in capsys.readouterr().out

    @needs_git
    def test_changed_lines_violation_under_warn_only_exits_zero(self, tmp_path, monkeypatch):
        enter_checkout(tmp_path, monkeypatch, ["com/acme/A.java", "com/acme/B.java"])
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = diff_for(tmp_path, {"com/acme/B.java": ["1,10"]})
        args = [str(report), "--min-coverage", "50", "--diff", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80", "--warn-only"]) == 0

    def test_missing_diff_exits_one(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        args = [str(report), "--min-coverage", "50", "--min-changed-coverage", "80"]
        with pytest.raises(SystemExit) as exc:
            coverage_gate.main(args)
        assert exc.value.code == 1
        args = [*args, "--diff", str(tmp_path / "nope.diff")]
        assert coverage_gate.main(args) == 1

    def test_bad_argument_exits_one_not_two(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            coverage_gate.main([str(tmp_path / "r.xml"), "--min-coverage", "abc"])
        assert exc.value.code == 1
