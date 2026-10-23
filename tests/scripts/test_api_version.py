"""Tests for openapi_version_check.py.

Integration tests call the script via subprocess and require oasdiff on PATH.
Unit tests for pure-Python helpers run without any external tools.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from openapi_version_check import (
    _set_gha_output,
    breaking_change_details,
    breaking_change_routes,
    main,
    route_versions,
)

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "openapi_version_check.py"
FIXTURES = Path(__file__).parent / "fixtures"

needs_oasdiff = pytest.mark.skipif(
    shutil.which("oasdiff") is None,
    reason="oasdiff not on PATH",
)


def run(baseline: Path, current: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(baseline), str(current)],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return result.returncode, result.stdout


def read_gha_output(path: Path) -> dict[str, str]:
    """Parse a GITHUB_OUTPUT file of heredoc blocks the way the Actions runner does."""
    pattern = r"^(\w+)<<(\S+)\n(.*?)\n\2$"
    return {name: body for name, _, body in re.findall(pattern, path.read_text(), re.M | re.S)}


class TestRouteVersions:
    def test_extracts_route_and_version(self):
        spec = {"paths": {"/v1/auth/verify": {"get": {"responses": {}}}}}
        assert route_versions(spec) == {"/v{N}/auth/verify": {1}}

    def test_multiple_versions_same_route(self):
        spec = {
            "paths": {
                "/v1/auth/verify": {"get": {"responses": {}}},
                "/v2/auth/verify": {"get": {"responses": {}}},
            }
        }
        assert route_versions(spec) == {"/v{N}/auth/verify": {1, 2}}

    def test_keeps_path_prefix_before_version(self):
        spec = {
            "paths": {
                "/api/v1/auth/verify": {"get": {"responses": {}}},
                "/api/v2/auth/verify": {"get": {"responses": {}}},
            }
        }
        assert route_versions(spec) == {"/api/v{N}/auth/verify": {1, 2}}

    def test_different_suffixes_are_different_routes(self):
        spec = {
            "paths": {
                "/v1/auth/verify": {"get": {"responses": {}}},
                "/v2/auth/whoami": {"get": {"responses": {}}},
            }
        }
        assert route_versions(spec) == {
            "/v{N}/auth/verify": {1},
            "/v{N}/auth/whoami": {2},
        }

    def test_probe_excluded(self):
        spec = {
            "paths": {
                "/v1/auth/verify": {"get": {"responses": {}}},
                "/v1/auth/probe": {"get": {"tags": ["probe"], "responses": {}}},
            }
        }
        assert route_versions(spec) == {"/v{N}/auth/verify": {1}}

    def test_unversioned_path_ignored(self):
        spec = {"paths": {"/auth/verify": {"get": {"responses": {}}}}}
        assert route_versions(spec) == {}


class TestBreakingChangeRoutes:
    def test_extracts_route_from_path(self):
        payload = '[{"path": "/v1/auth/verify", "id": "api-path-removed"}]'
        assert breaking_change_routes(payload) == {"/v{N}/auth/verify"}

    def test_keeps_prefix_before_version(self):
        payload = '[{"path": "/api/v1/auth/verify", "id": "api-path-removed"}]'
        assert breaking_change_routes(payload) == {"/api/v{N}/auth/verify"}

    def test_multiple_routes(self):
        payload = '[{"path": "/v1/auth/verify"}, {"path": "/v1/reports/list"}]'
        assert breaking_change_routes(payload) == {
            "/v{N}/auth/verify",
            "/v{N}/reports/list",
        }

    def test_deduplicates_same_route(self):
        payload = '[{"path": "/v1/auth/verify"}, {"path": "/v2/auth/verify"}]'
        assert breaking_change_routes(payload) == {"/v{N}/auth/verify"}

    def test_does_not_deduplicate_different_routes_in_same_group(self):
        payload = '[{"path": "/v1/auth/verify"}, {"path": "/v1/auth/whoami"}]'
        assert breaking_change_routes(payload) == {
            "/v{N}/auth/verify",
            "/v{N}/auth/whoami",
        }

    def test_empty_list(self):
        assert breaking_change_routes("[]") == set()

    def test_invalid_json_returns_empty(self):
        assert breaking_change_routes("not json") == set()

    def test_change_without_path_ignored(self):
        payload = '[{"id": "schema-change", "path": ""}]'
        assert breaking_change_routes(payload) == set()


class TestBreakingChangeDetails:
    def test_groups_changes_by_category(self):
        fields = ("id", "operation", "path", "text")
        changes = [
            ("response-property-type-changed", "GET", "/v1/a", "type changed"),
            ("api-path-removed-without-deprecation", "GET", "/v1/b", "path removed"),
            ("new-required-request-property", "POST", "/v1/a", "new required property"),
            ("response-required-property-removed", "GET", "/v1/a", "property removed"),
        ]
        payload = json.dumps([dict(zip(fields, change)) for change in changes])
        assert breaking_change_details(payload) == (
            "Removed endpoints:\n\n"
            "- GET /v1/b: path removed\n\n"
            "Removed fields (a rename shows up as a removal):\n\n"
            "- GET /v1/a: property removed\n\n"
            "Changed request shapes:\n\n"
            "- POST /v1/a: new required property\n\n"
            "Other breaking changes:\n\n"
            "- GET /v1/a: type changed"
        )

    def test_drops_warn_level_changes(self):
        payload = json.dumps(
            [
                {"id": "response-optional-property-removed", "level": 2, "path": "/v1/a"},
                {
                    "id": "api-removed-before-sunset",
                    "level": 3,
                    "operation": "GET",
                    "path": "/v1/b",
                    "text": "removed",
                },
            ]
        )
        assert breaking_change_details(payload) == "Removed endpoints:\n\n- GET /v1/b: removed"

    def test_omits_empty_categories(self):
        payload = (
            '[{"id": "api-removed-before-sunset", "operation": "GET", "path": "/v1/b", '
            '"text": "removed"}]'
        )
        assert breaking_change_details(payload) == "Removed endpoints:\n\n- GET /v1/b: removed"

    def test_invalid_json_returns_empty(self):
        assert breaking_change_details("not json") == ""

    def test_caps_size_and_counts_the_rest(self):
        payload = json.dumps(
            [
                {
                    "id": "api-removed-before-sunset",
                    "operation": "GET",
                    "path": f"/v1/r{i}",
                    "text": "removed",
                }
                for i in range(5)
            ]
        )
        assert breaking_change_details(payload, max_bytes=80) == (
            "Removed endpoints:\n\n"
            "- GET /v1/r0: removed\n"
            "- GET /v1/r1: removed\n\n"
            "... 3 more, see the spec artifact."
        )

    def test_real_output_stays_under_the_teams_limit(self):
        payload = json.dumps(
            [
                {
                    "id": "response-required-property-removed",
                    "operation": "GET",
                    "path": f"/v1/resource/{i}",
                    "text": "removed the required property 'data/items/field' " * 3,
                }
                for i in range(2000)
            ]
        )
        details = breaking_change_details(payload)
        assert len(details.encode()) < 20_500
        assert details.endswith("more, see the spec artifact.")


class TestSetGhaOutput:
    def test_multiline_value_survives_runner_parsing(self, tmp_path, monkeypatch):
        output = tmp_path / "output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        value = "first\nEOF\nghadelimiter_not-the-real-one\nkey=value\n\nlast"
        _set_gha_output(single="one line", multi=value)
        assert read_gha_output(output) == {"single": "one line", "multi": value}


class TestOasdiffExitCodeHandling:
    """oasdiff diff exits 0 on some versions even when differences exist.

    The script must detect changes from stdout content, not just exit code.
    """

    def _mock_run(self, diff_returncode, diff_stdout, breaking_returncode, breaking_stdout):
        def side_effect(cmd, **kwargs):
            result = MagicMock()
            if cmd[1] == "diff":
                result.returncode = diff_returncode
                result.stdout = diff_stdout
                result.stderr = ""
            else:
                result.returncode = breaking_returncode
                result.stdout = breaking_stdout
                result.stderr = ""
            return result

        return side_effect

    def test_exit0_with_stdout_treated_as_changed(self, tmp_path):
        baseline = tmp_path / "baseline.json"
        baseline.write_text('{"openapi":"3.0.0","info":{"title":"T","version":"1.0.0"},"paths":{}}')
        current = tmp_path / "current.json"
        current.write_text('{"openapi":"3.0.0","info":{"title":"T","version":"1.0.0"},"paths":{}}')
        side_effect = self._mock_run(
            diff_returncode=0,
            diff_stdout="some diff output\n",
            breaking_returncode=0,
            breaking_stdout="[]",
        )
        with patch("openapi_version_check.subprocess.run", side_effect=side_effect):
            rc = main(str(baseline), str(current))
        assert rc == 0

    def test_exit0_with_empty_stdout_treated_as_no_changes(self, tmp_path):
        spec = tmp_path / "spec.json"
        spec.write_text('{"openapi":"3.0.0","info":{"title":"T","version":"1.0.0"},"paths":{}}')
        side_effect = self._mock_run(
            diff_returncode=0,
            diff_stdout="",
            breaking_returncode=0,
            breaking_stdout="[]",
        )
        with patch("openapi_version_check.subprocess.run", side_effect=side_effect):
            rc = main(str(spec), str(spec))
        assert rc == 0

    def test_breaking_without_identified_route_fails(self, tmp_path):
        spec = tmp_path / "spec.json"
        spec.write_text('{"openapi":"3.0.0","info":{"title":"T","version":"1.0.0"},"paths":{}}')
        side_effect = self._mock_run(
            diff_returncode=1,
            diff_stdout="some diff output\n",
            breaking_returncode=1,
            breaking_stdout='[{"id": "schema-removed"}]',
        )
        with patch("openapi_version_check.subprocess.run", side_effect=side_effect):
            rc = main(str(spec), str(spec))
        assert rc == 1


@pytest.mark.integration
@needs_oasdiff
class TestApiVersionScript:
    def test_no_changes_passes(self):
        rc, _ = run(FIXTURES / "auth_v1.json", FIXTURES / "auth_v1.json")
        assert rc == 0

    def test_nonbreaking_change_with_info_version_bump_passes(self):
        rc, _ = run(FIXTURES / "auth_v1.json", FIXTURES / "api_nonbreaking_v1_1.json")
        assert rc == 0

    def test_nonbreaking_change_without_info_version_bump_passes(self):
        rc, _ = run(FIXTURES / "auth_v1.json", FIXTURES / "api_nonbreaking_no_bump.json")
        assert rc == 0

    def test_breaking_with_new_paths_passes(self):
        rc, _ = run(FIXTURES / "auth_v1.json", FIXTURES / "api_breaking_v2.json")
        assert rc == 0

    def test_breaking_with_new_paths_and_no_info_version_bump_passes(self):
        rc, _ = run(FIXTURES / "auth_v1.json", FIXTURES / "api_breaking_v2_no_bump.json")
        assert rc == 0

    def test_breaking_without_new_version_paths_fails(self):
        rc, out = run(FIXTURES / "auth_v1.json", FIXTURES / "api_breaking_no_paths_v2.json")
        assert rc == 1
        assert "/v2/auth/verify" in out

    def test_breaking_without_new_version_paths_fails_even_when_info_version_changes(self):
        rc, out = run(FIXTURES / "auth_v1.json", FIXTURES / "api_breaking_minor.json")
        assert rc == 1
        assert "/v2/auth/verify" in out

    def test_breaking_with_new_version_on_different_route_fails(self):
        rc, out = run(
            FIXTURES / "auth_v1.json",
            FIXTURES / "api_breaking_different_route_v2.json",
        )
        assert rc == 1
        assert "/v2/auth/verify" in out

    def test_breaking_in_one_group_other_group_unaffected_passes(self):
        rc, _ = run(
            FIXTURES / "api_multi_group_base.json",
            FIXTURES / "api_multi_group_breaking_auth.json",
        )
        assert rc == 0

    def test_outputs_affected_route_on_success(self):
        rc, out = run(FIXTURES / "auth_v1.json", FIXTURES / "api_breaking_v2.json")
        assert rc == 0
        assert "/v1/auth/verify -> /v2/auth/verify" in out


@pytest.mark.integration
@needs_oasdiff
class TestApiVersionOutputs:
    def outputs(self, tmp_path: Path, baseline: str, current: str) -> tuple[int, dict[str, str]]:
        output = tmp_path / "output"
        output.touch()
        rc, _ = run(FIXTURES / baseline, FIXTURES / current, {"GITHUB_OUTPUT": str(output)})
        return rc, read_gha_output(output)

    @pytest.mark.parametrize("current", ["auth_v1.json", "api_nonbreaking_v1_1.json"])
    def test_nonbreaking_writes_only_flags(self, tmp_path, current):
        rc, outputs = self.outputs(tmp_path, "auth_v1.json", current)
        assert rc == 0
        assert outputs == {"has_breaking": "false", "is_major_bump": "false"}

    def test_major_bump_writes_route_summary_and_categorized_details(self, tmp_path):
        rc, outputs = self.outputs(tmp_path, "users_v1.json", "users_breaking_v2.json")
        assert rc == 0
        assert outputs["has_breaking"] == "true"
        assert outputs["is_major_bump"] == "true"
        assert outputs["route_summary"] == (
            "/v1/auth/verify -> /v2/auth/verify, /v1/users -> /v2/users"
        )
        details = outputs["breaking_details"]
        assert (
            "Removed endpoints:\n\n- GET /v1/auth/verify: api path removed without deprecation"
            in details
        )
        assert (
            "Removed fields (a rename shows up as a removal):\n\n"
            "- GET /v1/users: removed the required property `name` from the response" in details
        )
        assert (
            "Changed request shapes:\n\n"
            "- POST /v1/users: added the new required request property `email`" in details
        )
        assert "Other breaking changes:\n\n- GET /v1/users: the `id` response's property" in details

    def test_breaking_without_bump_writes_details_but_no_route_summary(self, tmp_path):
        rc, outputs = self.outputs(tmp_path, "auth_v1.json", "api_breaking_no_paths_v2.json")
        assert rc == 1
        assert outputs["is_major_bump"] == "false"
        assert "route_summary" not in outputs
        assert outputs["breaking_details"].startswith("Removed endpoints:")
