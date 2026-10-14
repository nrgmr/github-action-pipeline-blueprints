"""Tests for rp-base.spectral.js.

All tests call the Spectral CLI via subprocess and require it on PATH.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RULESET = Path(__file__).parent.parent.parent / "spectral" / "rp-base.spectral.js"
FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("spectral") is None, reason="spectral not on PATH"),
]


def lint(fixture_name: str) -> tuple[int, str]:
    spectral_cmd = shutil.which("spectral") or "spectral"
    result = subprocess.run(
        [spectral_cmd, "lint", str(FIXTURES / fixture_name), "--ruleset", str(RULESET)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


class TestVersionedPathRule:
    def test_valid_versioned_path_passes(self):
        rc, _ = lint("valid_spec.json")
        assert rc == 0

    def test_two_consecutive_versions_passes(self):
        rc, _ = lint("two_versions.json")
        assert rc == 0

    def test_probe_path_exempt_from_version_rule(self):
        rc, _ = lint("probe_exempt.json")
        assert rc == 0

    def test_path_missing_version_segment_fails(self):
        rc, output = lint("missing_version.json")
        assert rc != 0
        assert "version segment" in output

    def test_path_with_two_version_segments_fails(self):
        rc, output = lint("double_version.json")
        assert rc != 0
        assert "version segments" in output

    def test_malformed_operation_tags_do_not_crash_custom_rule(self):
        rc, output = lint("malformed_operation_tags.json")
        assert rc != 0
        assert "TypeError" not in output
        assert "includes" not in output

    def test_three_concurrent_versions_are_left_to_version_limit_script(self):
        rc, _ = lint("three_versions.json")
        assert rc == 0

    def test_non_consecutive_versions_are_left_to_version_limit_script(self):
        rc, _ = lint("non_consecutive.json")
        assert rc == 0

    def test_independent_route_groups_do_not_conflict(self):
        rc, _ = lint("two_groups_independent.json")
        assert rc == 0

    def test_different_routes_in_same_group_do_not_conflict(self):
        rc, _ = lint("same_group_different_routes.json")
        assert rc == 0

    def test_different_prefixes_do_not_conflict(self):
        rc, _ = lint("same_suffix_different_prefixes.json")
        assert rc == 0
