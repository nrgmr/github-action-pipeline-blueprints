import json
from pathlib import Path

import export_env_vars
import pytest


@pytest.fixture
def env_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(path))
    monkeypatch.delenv("ENV_VARS_JSON", raising=False)
    monkeypatch.delenv("SECRET_ENV_VARS_JSON", raising=False)
    return path


def read_exported(path: Path, keep_names: bool = False) -> dict[str, str]:
    """Parse the file the way the runner does: name<<delimiter, value lines, delimiter."""
    result, lines = {}, path.read_text().splitlines()
    i = 0
    while i < len(lines):
        name, delimiter = lines[i].split("<<")
        end = lines.index(delimiter, i + 1)
        result[name] = "\n".join(lines[i + 1 : end])
        i = end + 1
    if not keep_names:
        result.pop(export_env_vars.NAMES_VAR, None)
    return result


class TestParseObject:
    @pytest.mark.parametrize("raw", ["", "   ", "\n"])
    def test_blank_is_empty(self, raw):
        assert export_env_vars.parse_object(raw, "env-vars") == {}

    def test_object_of_strings(self):
        assert export_env_vars.parse_object('{"A": "1"}', "env-vars") == {"A": "1"}

    def test_invalid_json_errors_without_echoing_input(self):
        with pytest.raises(export_env_vars.ExportError) as err:
            export_env_vars.parse_object('{"TOKEN": "hunter2"', "secret-env-vars")
        assert "hunter2" not in str(err.value)

    def test_non_object_errors(self):
        with pytest.raises(export_env_vars.ExportError, match="JSON object"):
            export_env_vars.parse_object('["a"]', "env-vars")

    def test_non_string_value_errors_without_echoing_it(self):
        with pytest.raises(export_env_vars.ExportError, match="must be a string") as err:
            export_env_vars.parse_object('{"PORT": 8080}', "env-vars")
        assert "8080" not in str(err.value)


class TestCheckName:
    @pytest.mark.parametrize("name", ["NODE_AUTH_TOKEN", "_x", "a1"])
    def test_accepts_identifiers(self, name):
        export_env_vars.check_name(name, "env-vars")

    @pytest.mark.parametrize("name", ["", "1A", "A-B", "A B", "A=B", "A\nB"])
    def test_rejects_non_identifiers(self, name):
        with pytest.raises(export_env_vars.ExportError, match="not a valid"):
            export_env_vars.check_name(name, "env-vars")

    @pytest.mark.parametrize(
        "name",
        [
            "PATH",
            "HOME",
            "CI",
            "BASH_ENV",
            "LD_PRELOAD",
            "GITHUB_ENV",
            "RUNNER_TEMP",
            "ACTIONS_X",
            "RP_EXPORTED_ENV_NAMES",
        ],
    )
    def test_rejects_reserved(self, name):
        with pytest.raises(export_env_vars.ExportError, match="reserved"):
            export_env_vars.check_name(name, "env-vars")

    @pytest.mark.parametrize("name", ["NODE_OPTIONS", "node_options"])
    def test_rejects_the_name_the_runner_blocks(self, name):
        with pytest.raises(export_env_vars.ExportError, match="GITHUB_ENV"):
            export_env_vars.check_name(name, "env-vars")

    def test_allows_other_runtime_tuning_names(self):
        export_env_vars.check_name("JAVA_TOOL_OPTIONS", "env-vars")


class TestMask:
    def test_masks_each_nonblank_line(self, capsys):
        export_env_vars.mask("one\n\ntwo\r\n  \nthree")
        assert capsys.readouterr().out.splitlines() == [
            "::add-mask::one",
            "::add-mask::two",
            "::add-mask::three",
        ]

    def test_escapes_percent_so_the_runner_masks_the_original_value(self, capsys):
        export_env_vars.mask("p%25w%0Ad")
        assert capsys.readouterr().out == "::add-mask::p%2525w%250Ad\n"


class TestMain:
    def test_exports_plain_and_secret(self, env_file, monkeypatch, capsys):
        monkeypatch.setenv("ENV_VARS_JSON", json.dumps({"REGION": "us-west1"}))
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", json.dumps({"NODE_AUTH_TOKEN": "s3cret"}))

        assert export_env_vars.main() == 0

        assert read_exported(env_file) == {"REGION": "us-west1", "NODE_AUTH_TOKEN": "s3cret"}
        out = capsys.readouterr().out
        assert "::add-mask::s3cret" in out
        assert "::add-mask::us-west1" not in out
        assert "s3cret" not in out.replace("::add-mask::s3cret", "")

    def test_nothing_to_export_writes_nothing(self, env_file):
        assert export_env_vars.main() == 0
        assert not env_file.exists()

    def test_secret_wins_on_duplicate_name(self, env_file, monkeypatch):
        monkeypatch.setenv("ENV_VARS_JSON", '{"TOKEN": "plain"}')
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", '{"TOKEN": "secret"}')

        assert export_env_vars.main() == 0
        assert read_exported(env_file) == {"TOKEN": "secret"}

    def test_multiline_value_cannot_inject_a_variable(self, env_file, monkeypatch):
        injected = "line one\nPATH=/evil"
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", json.dumps({"KEY": injected}))

        assert export_env_vars.main() == 0
        assert read_exported(env_file) == {"KEY": injected}

    def test_appends_to_existing_file(self, env_file, monkeypatch):
        env_file.write_text("EXISTING<<x\n1\nx\n")
        monkeypatch.setenv("ENV_VARS_JSON", '{"NEW": "2"}')

        assert export_env_vars.main() == 0
        assert read_exported(env_file) == {"EXISTING": "1", "NEW": "2"}

    def test_invalid_name_fails_before_writing_or_masking(self, env_file, monkeypatch, capsys):
        monkeypatch.setenv("ENV_VARS_JSON", '{"GOOD": "1"}')
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", '{"PATH": "s3cret"}')

        assert export_env_vars.main() == 1

        assert not env_file.exists()
        captured = capsys.readouterr()
        assert "::error::" in captured.err
        assert "s3cret" not in captured.out + captured.err

    def test_missing_github_env_fails(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_ENV", raising=False)
        assert export_env_vars.main() == 1
        assert "GITHUB_ENV" in capsys.readouterr().err

    def test_records_exported_names_for_clearing(self, env_file, monkeypatch):
        monkeypatch.setenv("ENV_VARS_JSON", '{"REGION": "us-west1"}')
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", '{"TOKEN": "s3cret"}')

        assert export_env_vars.main() == 0

        recorded = read_exported(env_file, keep_names=True)[export_env_vars.NAMES_VAR]
        assert recorded == "REGION,TOKEN"

    def test_repeated_export_keeps_names_from_earlier_exports(self, env_file, monkeypatch):
        monkeypatch.setenv(export_env_vars.NAMES_VAR, "FIRST,SHARED")
        monkeypatch.setenv("ENV_VARS_JSON", '{"SHARED": "2", "SECOND": "3"}')

        assert export_env_vars.main() == 0

        recorded = read_exported(env_file, keep_names=True)[export_env_vars.NAMES_VAR]
        assert recorded == "FIRST,SHARED,SECOND"

    def test_repeated_export_rejects_a_tampered_earlier_list(self, env_file, monkeypatch, capsys):
        monkeypatch.setenv(export_env_vars.NAMES_VAR, "FIRST,PATH")
        monkeypatch.setenv("ENV_VARS_JSON", '{"SECOND": "3"}')

        assert export_env_vars.main() == 1

        assert not env_file.exists()
        assert "::error::" in capsys.readouterr().err

    def test_rejects_the_bookkeeping_name(self, env_file, monkeypatch):
        monkeypatch.setenv("ENV_VARS_JSON", json.dumps({export_env_vars.NAMES_VAR: "x"}))

        assert export_env_vars.main() == 1
        assert not env_file.exists()


class TestClear:
    @pytest.fixture(autouse=True)
    def clear_mode(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["export_env_vars.py", "--clear"])

    def test_blanks_each_recorded_name_and_the_list(self, env_file, monkeypatch, capsys):
        monkeypatch.setenv(export_env_vars.NAMES_VAR, "REGION,TOKEN")

        assert export_env_vars.main() == 0

        assert env_file.read_text().splitlines() == [
            "REGION=",
            "TOKEN=",
            f"{export_env_vars.NAMES_VAR}=",
        ]
        assert "Cleared 2 variable(s)" in capsys.readouterr().out

    def test_nothing_recorded_writes_nothing(self, env_file, monkeypatch):
        monkeypatch.delenv(export_env_vars.NAMES_VAR, raising=False)

        assert export_env_vars.main() == 0
        assert not env_file.exists()

    def test_export_then_clear_leaves_the_runner_with_empty_values(self, env_file, monkeypatch):
        monkeypatch.setenv("SECRET_ENV_VARS_JSON", '{"TOKEN": "s3cret"}')
        monkeypatch.setattr("sys.argv", ["export_env_vars.py"])
        assert export_env_vars.main() == 0
        monkeypatch.setattr("sys.argv", ["export_env_vars.py", "--clear"])
        monkeypatch.setenv(export_env_vars.NAMES_VAR, "TOKEN")

        assert export_env_vars.main() == 0

        # The runner applies the file in order, so the last write for a name wins.
        assert env_file.read_text().splitlines()[-2:] == ["TOKEN=", f"{export_env_vars.NAMES_VAR}="]

    def test_protected_name_in_the_list_is_refused(self, env_file, monkeypatch, capsys):
        monkeypatch.setenv(export_env_vars.NAMES_VAR, "TOKEN,PATH")

        assert export_env_vars.main() == 1

        assert not env_file.exists()
        assert "reserved" in capsys.readouterr().err

    def test_missing_github_env_fails(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_ENV", raising=False)
        assert export_env_vars.main() == 1
        assert "GITHUB_ENV" in capsys.readouterr().err
