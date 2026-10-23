"""Export caller-supplied environment variables to the later steps of a job.

Reads two JSON objects of string values from the environment:
    ENV_VARS_JSON         plain values, written as they are
    SECRET_ENV_VARS_JSON  secret values, masked in logs before they are written

and appends each pair to the file named by GITHUB_ENV. A name in both objects takes
the secret value. An empty or unset object is skipped.

Names must be valid shell identifiers and must not start with GITHUB_, RUNNER_ or
ACTIONS_, nor be NAMES_VAR or one of PROTECTED_NAMES, so a caller cannot change how the
runner or the shared steps behave. NODE_OPTIONS is also rejected, because the runner does not
allow it in GITHUB_ENV. Values are written with a random delimiter, so a newline in a
value cannot add variables.

The exported names are also recorded in NAMES_VAR, added to any names recorded by an
earlier export in the same job, so one clear step covers every export. With --clear,
each recorded name is set to an empty value, so the steps after the build and test
steps, including the coverage gate and any third-party action, no longer see the values.

Exit codes:
    0  - variables exported or cleared, or nothing to do
    1  - error (malformed JSON, non-string value, invalid or protected name)

Usage:
    ENV_VARS_JSON='{"A":"1"}' SECRET_ENV_VARS_JSON='{"TOKEN":"x"}' GITHUB_ENV=env.txt \\
        python3 export_env_vars.py
    RP_EXPORTED_ENV_NAMES=A,TOKEN GITHUB_ENV=env.txt python3 export_env_vars.py --clear
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PROTECTED_PREFIXES = ("GITHUB_", "RUNNER_", "ACTIONS_")
PROTECTED_NAMES = frozenset(
    {"PATH", "HOME", "SHELL", "CI", "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH"}
)
RUNNER_BLOCKED_NAME = "NODE_OPTIONS"
NAMES_VAR = "RP_EXPORTED_ENV_NAMES"


class ExportError(Exception):
    """Invalid input; maps to exit code 1."""


def parse_object(raw: str, source: str) -> dict[str, str]:
    """Parse a JSON object of string values. Messages never include the values."""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        message = f"{source} is not valid JSON ({exc.msg} at position {exc.pos})."
        raise ExportError(message) from None
    if not isinstance(data, dict):
        raise ExportError(f"{source} must be a JSON object of name to string value.")
    for name, value in data.items():
        if not isinstance(value, str):
            raise ExportError(
                f"{source}: the value for {name} must be a string. Quote numbers and booleans."
            )
    return data


def check_name(name: str, source: str) -> None:
    if not NAME_PATTERN.fullmatch(name):
        raise ExportError(f"{source}: {name!r} is not a valid variable name.")
    if name == NAMES_VAR or name in PROTECTED_NAMES or name.startswith(PROTECTED_PREFIXES):
        raise ExportError(f"{source}: {name} is reserved and cannot be set.")
    # The runner refuses this name in GITHUB_ENV, case-insensitively. Failing here gives a
    # clear message instead of a runner error after the step has started.
    if name.upper() == RUNNER_BLOCKED_NAME:
        raise ExportError(
            f"{source}: {name} cannot be set through GITHUB_ENV. Set it in a step env."
        )


def mask(value: str) -> None:
    """Mask each line separately, because the runner masks a multi-line value only line by line."""
    for line in value.splitlines():
        if line.strip():
            # The runner decodes %25, %0A and %0D in command data, so escape the percent sign
            # or a value containing such a sequence would be masked in its decoded form.
            print(f"::add-mask::{line.replace('%', '%25')}")


def export(variables: dict[str, str], env_file: Path) -> None:
    with env_file.open("a", encoding="utf-8") as handle:
        for name, value in variables.items():
            delimiter = f"ghadelimiter_{uuid.uuid4().hex}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def recorded_names() -> list[str]:
    return [name for name in os.environ.get(NAMES_VAR, "").split(",") if name]


def run_clear() -> int:
    try:
        env_file = os.environ.get("GITHUB_ENV")
        if not env_file:
            raise ExportError("GITHUB_ENV is not set; this must run inside a GitHub Actions step.")
        names = recorded_names()
        # The list lives in GITHUB_ENV, which a build step can edit, so each name is checked
        # again. That keeps this step from writing to a protected name.
        for name in names:
            check_name(name, NAMES_VAR)
    except ExportError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if names:
        with Path(env_file).open("a", encoding="utf-8") as handle:
            for name in [*names, NAMES_VAR]:
                handle.write(f"{name}=\n")
        print(f"Cleared {len(names)} variable(s) for the remaining steps.")
    return 0


def main() -> int:
    if "--clear" in sys.argv[1:]:
        return run_clear()
    try:
        env_file = os.environ.get("GITHUB_ENV")
        if not env_file:
            raise ExportError("GITHUB_ENV is not set; this must run inside a GitHub Actions step.")
        plain = parse_object(os.environ.get("ENV_VARS_JSON", ""), "env-vars")
        secret = parse_object(os.environ.get("SECRET_ENV_VARS_JSON", ""), "secret-env-vars")
        for source, variables in (("env-vars", plain), ("secret-env-vars", secret)):
            for name in variables:
                check_name(name, source)
        # The list lives in GITHUB_ENV, which a build step can edit, so names from an earlier
        # export are checked again before they are carried forward.
        earlier = recorded_names()
        for name in earlier:
            check_name(name, NAMES_VAR)
    except ExportError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    # Mask before anything is written, so a failure partway cannot leave a value unmasked.
    for value in secret.values():
        mask(value)
    merged = {**plain, **secret}
    if merged:
        names = list(dict.fromkeys([*earlier, *merged]))
        export({**merged, NAMES_VAR: ",".join(names)}, Path(env_file))
        print(f"Exported {len(merged)} variable(s): {', '.join(sorted(merged))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
