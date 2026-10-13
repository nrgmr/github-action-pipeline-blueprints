import json
from pathlib import Path

import coverage_gate
import pytest

JACOCO = """<?xml version="1.0"?>
<report name="x"><package name="p"><counter type="LINE" missed="1" covered="1"/></package>
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

    def test_cobertura_lines_counts(self, tmp_path):
        assert coverage_gate.overall_coverage(write(tmp_path, "c.xml", COBERTURA)) == 80.0

    def test_lcov_sums_across_files(self, tmp_path):
        assert coverage_gate.overall_coverage(write(tmp_path, "lcov.info", LCOV)) == 70.0

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


JACOCO_FILES = """<?xml version="1.0"?>
<report name="x">
<package name="com/acme">
<sourcefile name="A.java"><counter type="LINE" missed="1" covered="9"/></sourcefile>
<sourcefile name="B.java"><counter type="LINE" missed="5" covered="5"/></sourcefile>
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


def changed_list(tmp_path: Path, *names: str) -> Path:
    return write(tmp_path, "changed.txt", "\n".join(names) + "\n")


class TestFileCoverage:
    def test_jacoco_joins_package_and_source_file(self, tmp_path):
        files = coverage_gate.file_coverage(write(tmp_path, "j.xml", JACOCO_FILES))
        assert files == {"com/acme/A.java": (9, 10), "com/acme/B.java": (5, 10)}

    def test_cobertura_merges_classes_sharing_a_file(self, tmp_path):
        files = coverage_gate.file_coverage(write(tmp_path, "c.xml", COBERTURA_FILES))
        assert files == {"app/a.py": (3, 3), "app/b.py": (0, 1)}

    def test_lcov_reads_each_record(self, tmp_path):
        files = coverage_gate.file_coverage(write(tmp_path, "lcov.info", LCOV))
        assert files == {"a.ts": (9, 10), "b.ts": (5, 10)}

    def test_unknown_xml_root_errors(self, tmp_path):
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.file_coverage(write(tmp_path, "x.xml", "<other/>"))


class TestChangedCoverage:
    def test_combines_matching_files_only(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "svc/src/main/java/com/acme/B.java", "README.md")
        percent, files = coverage_gate.changed_coverage(report, changed)
        assert percent == 50.0
        assert list(files) == ["com/acme/B.java"]

    def test_sums_lines_across_files_rather_than_averaging(self, tmp_path):
        report = write(
            tmp_path,
            "lcov.info",
            "SF:a.ts\nLF:90\nLH:90\nend_of_record\nSF:b.ts\nLF:10\nLH:0\nend_of_record\n",
        )
        percent, _ = coverage_gate.changed_coverage(report, changed_list(tmp_path, "a.ts", "b.ts"))
        assert percent == 90.0

    def test_no_match_returns_none(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        assert coverage_gate.changed_coverage(report, changed_list(tmp_path, "docs/x.md")) is None

    def test_does_not_match_on_a_partial_file_name(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "src/com/acme/XA.java")
        assert coverage_gate.changed_coverage(report, changed) is None

    def test_absolute_report_paths_match_relative_changes(self, tmp_path):
        report = write(
            tmp_path,
            "lcov.info",
            "SF:/home/runner/work/r/r/ui/src/a.ts\nLF:4\nLH:2\nend_of_record\n",
        )
        percent, _ = coverage_gate.changed_coverage(report, changed_list(tmp_path, "ui/src/a.ts"))
        assert percent == 50.0

    def test_windows_separators_are_normalised(self, tmp_path):
        report = write(tmp_path, "lcov.info", "SF:src\\a.ts\nLF:4\nLH:2\nend_of_record\n")
        assert coverage_gate.changed_coverage(report, changed_list(tmp_path, "ui/src/a.ts"))

    def test_files_without_executable_lines_are_ignored(self, tmp_path):
        report = write(tmp_path, "lcov.info", "SF:a.ts\nLF:0\nLH:0\nend_of_record\n")
        assert coverage_gate.changed_coverage(report, changed_list(tmp_path, "a.ts")) is None

    def test_missing_list_errors(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        with pytest.raises(coverage_gate.GateError):
            coverage_gate.changed_coverage(report, tmp_path / "nope.txt")


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


class TestRenderSummary:
    ROWS = [("Overall", "80.00% (min 80%)", True)]

    def test_lists_files_lowest_coverage_first_with_status(self):
        files = {"a/Full.java": (10, 10), "b/Low.java": (1, 10)}
        lines = coverage_gate.render_summary(self.ROWS, files, 50).splitlines()
        assert lines[-2:] == [
            "| `b/Low.java` | 10.00% | ❌ |",
            "| `a/Full.java` | 100.00% | ✅ |",
        ]

    def test_status_is_blank_without_a_changed_threshold(self):
        summary = coverage_gate.render_summary(self.ROWS, {"a/Full.java": (10, 10)})
        assert "| `a/Full.java` | 100.00% |  |" in summary

    def test_caps_file_rows_and_reports_the_rest(self):
        files = {f"f{i}.java": (i, 100) for i in range(coverage_gate.MAX_FILE_ROWS + 3)}
        summary = coverage_gate.render_summary(self.ROWS, files, 50)
        assert summary.count("| `f") == coverage_gate.MAX_FILE_ROWS
        assert "3 more changed files are not shown." in summary

    def test_omits_file_table_without_changed_files(self):
        assert "| File |" not in coverage_gate.render_summary(self.ROWS)


class TestMain:
    def test_pass_writes_summary(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO)
        summary = tmp_path / "summary.md"
        code = coverage_gate.main(
            [str(report), "--min-coverage", "80", "--summary-file", str(summary)]
        )
        assert code == 0
        assert "| Overall | 80.00% (min 80%) | ✅ |" in summary.read_text(encoding="utf-8")

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

    def test_changed_files_below_minimum_exits_two(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "com/acme/B.java")
        args = [str(report), "--min-coverage", "50", "--changed-files", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80"]) == 2
        captured = capsys.readouterr()
        assert "Changed files" in captured.err
        assert "| `com/acme/B.java` | 50.00% | ❌ |" in captured.out

    def test_changed_files_meeting_minimum_passes(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "com/acme/A.java")
        args = [str(report), "--min-coverage", "50", "--changed-files", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80"]) == 0

    def test_changed_files_outside_the_report_skip_with_a_notice(self, tmp_path, capsys):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "docs/x.md")
        args = [str(report), "--min-coverage", "50", "--changed-files", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "99"]) == 0
        assert "::notice::No changed file" in capsys.readouterr().out

    def test_changed_files_violation_under_warn_only_exits_zero(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        changed = changed_list(tmp_path, "com/acme/B.java")
        args = [str(report), "--min-coverage", "50", "--changed-files", str(changed)]
        assert coverage_gate.main([*args, "--min-changed-coverage", "80", "--warn-only"]) == 0

    def test_missing_changed_list_exits_one(self, tmp_path):
        report = write(tmp_path, "j.xml", JACOCO_FILES)
        args = [str(report), "--min-coverage", "50", "--min-changed-coverage", "80"]
        with pytest.raises(SystemExit) as exc:
            coverage_gate.main(args)
        assert exc.value.code == 1
        args = [*args, "--changed-files", str(tmp_path / "nope.txt")]
        assert coverage_gate.main(args) == 1

    def test_bad_argument_exits_one_not_two(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            coverage_gate.main([str(tmp_path / "r.xml"), "--min-coverage", "abc"])
        assert exc.value.code == 1
