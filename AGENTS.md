# AGENTS.md

## When To Read What

- Any change to `.github/workflows/`: read the full workflow file being changed
  and verify it follows the conventions below before proceeding.
- Any change to `.github/actions/openapi-checks/action.yml`: verify the change
  does not break the `spec-path`, `package-name`, and GCP secret inputs that
  callers depend on.
- Adding a new language workflow: read the existing language workflow
  implementations as reference before writing the new ones.
- Changing `spectral/rp-base.spectral.js`: verify the change does not silently
  break service-level `.spectral.yaml` overrides that extend it.
- Changing `scripts/openapi_version_check.py`: any interface change to args,
  exit codes, or GitHub Actions outputs (`has_breaking`, `is_major_bump`,
  `route_summary`, `breaking_details`) must be reflected in
  `.github/actions/openapi-checks/action.yml`.
- Changing `scripts/openapi_version_limit_check.py`: preserve exit code `2` for
  version-limit violations — the composite action branches on this code to
  implement the `override-version-limit` flow. Exit `1` is reserved for
  unexpected errors; exit `0` is clean.
- Changing `scripts/coverage_gate.py`: preserve exit code `2` for threshold
  violations. The `coverage-gate` composite action implements
  `fail-on-threshold: false` by passing `--warn-only`, which maps `2` to `0`.
  Exit `1` is reserved for errors and always fails the job. Interface changes
  to args must be reflected in `.github/actions/coverage-gate/action.yml`.
- Changing `scripts/export_env_vars.py`: preserve exit code `1` for invalid input
  and never put a secret value in an error message. Interface changes to its
  environment variables must be reflected in
  `.github/actions/export-env-vars/action.yml`. `--clear` backs
  `.github/actions/clear-env-vars/action.yml`. Keep the clear step after the last
  build or test step and before any third-party action, and never add one
  in between. The limits in the
  Environment variables section of `docs/tools.md` must stay accurate.
- Changing `java-test.yml`, `python-test.yml`, or `typescript-test.yml`: the
  shared behavior must stay identical across all three, so make the same change
  in each. Shared behavior is the coverage inputs and their descriptions, the
  `env-vars` input and `SECRET_ENV_VARS` secret with the `export-env-vars` and `clear-env-vars` steps, the tooling
  checkout, and the `coverage-gate` call. Only the toolchain steps
  (setup, build, test command, report path) differ by language. Update the
  shared inputs table in `docs/tools.md` once.
- Changing any `gen-spec/{language}/` script: the script is called from the
  corresponding language workflow and must write a valid OpenAPI JSON spec to
  stdout.

## Workflow Conventions

**Workflow naming:** use `{language}-{intent}.yml` for language-specific
workflows. Omit the language prefix for language-agnostic workflows such as
`docker-build-push.yml`. Intent should describe what the workflow does, not how:
use `openapi-generate`, not `api-checks`.

**Composite action vs reusable workflow:** reusable workflows own the public
caller contract and the orchestration for a specific job, such as lint/test,
OpenAPI generation, or Docker publish. Use `{language}-{intent}.yml` when that
job depends on a language or framework toolchain. Use a composite action when a
set of steps is shared across multiple workflows and should evolve in one place.
For example, once any workflow has produced an OpenAPI spec, shared policy
checks such as Spectral, oasdiff, GCP baseline fetch/publish, and Teams
notifications belong in `.github/actions/openapi-checks/`.

**Script checkout inside workflows:** always use `job.workflow_repository` and
`job.workflow_sha` when checking out `rp-ci-tooling` from within one of its own
reusable workflows. These identify the repository and commit for the workflow
file that defines the current job. Never hardcode a tag or branch because it
would drift from the workflow version the caller pinned.

```yaml
- uses: actions/checkout@v4
  with:
    repository: ${{ job.workflow_repository }}
    ref: ${{ job.workflow_sha }}
    path: .rp-ci-tooling
```

**Deprecating a workflow:** GitHub Actions has no deprecation marker. Keep the
workflow's existing jobs unchanged, add a job that emits a `::warning::`
annotation, mark its `docs/tools.md` section "(deprecated)" with a migration
example, and remove it only in a later major release. Do not turn it into a
wrapper that calls its replacements: GitHub does not document which repository a
relative `uses: ./...` resolves against when a workflow is called from another
repository, and a hardcoded ref would break the pinning convention. Pinned
callers keep the old behavior because tags are immutable.

**Coverage in test workflows:** language test workflows produce a coverage
report and then call `./.rp-ci-tooling/.github/actions/coverage-gate`. Do not
add per-language threshold logic; extend `scripts/coverage_gate.py` instead.
Reusable workflows must not declare `permissions:` that exceed what the caller
grants, so the PR comment option documents the required caller permission.

**Composite action secrets:** composite actions cannot declare `secrets:`. Pass
secret values as regular `inputs`. They are still masked in logs when sourced
from `${{ secrets.* }}`.

**Reusable workflow secrets:** reusable workflows must declare secrets
explicitly under `on.workflow_call.secrets`. Never access `secrets.*` without
declaring the secret contract.

**GHA subdirectories:** GitHub Actions does not support subdirectories under
`.github/workflows/`. Keep all workflow files flat.

## Documentation Maintenance

This repo has three documentation files with distinct audiences:

- `README.md` — orientation and pinning guidance. Update when the pinning conventions change.
- `docs/tools.md` — caller-facing reference for each workflow: inputs, secrets, usage examples, API check behavior, Spectral overrides. Update whenever a public workflow interface changes (new input, changed default, new behavior).
- `docs/release.md` — release process, PR title conventions, semver rules. Update when the release automation or bump rules change.
- `AGENTS.md` — this file. Codebase conventions, script contracts, gotchas. Update when internal conventions or interfaces change.

When a public reusable workflow changes, update `docs/tools.md` for:

- caller YAML examples
- input and secret tables
- behavior descriptions visible to callers

When a new `##` section is added to `docs/tools.md` — a new workflow or a new
conceptual section — add it to the "Contents" list at the top, in alphabetical
order, linked to its heading anchor.

Do not add script inventories, directory structure diagrams, internal call graphs, or implementation notes to `README.md` or `docs/tools.md`.

Use sample tags such as `v1.2.0` in examples and make clear that services should replace them with the released tag they are adopting. Do not show `@main` except as an explicit anti-pattern.

## Comment And Documentation Style

Applies to code comments and to every file under `docs/`, `README.md`, and `AGENTS.md`.

- Earn their place: a comment or doc line should say something the reader cannot already get from the code or heading it sits next to.
- Be clear and easy to follow: prefer plain, direct sentences over dense or clever ones.
- Be succinct: cut qualifiers, hedges, and asides that do not change what the reader does next.
- Be useful to the reader: explain the "why," not just the "what" — the reasoning a future editor would otherwise have to reconstruct.
- Do not mention ticket numbers or other issue-tracker references. A comment or doc should stand on its own without external context.

## Adding A New Language

Follow the naming conventions in the Workflow Conventions section. Two non-obvious requirements:

- After generating the spec, call `./.rp-ci-tooling/.github/actions/openapi-checks` — do not replicate its steps inline in the new workflow.
- Use `job.workflow_sha` when checking out this repo from within the new workflow, not a hardcoded tag or branch.

## Anti-Patterns

- Do not reference `@main` or hardcode a tag inside a workflow; use
  `job.workflow_sha` for internal checkouts.
- Do not add language-specific logic inside a language-agnostic workflow.
- Do not inline version-check scripts or Spectral rulesets into a workflow.
- Do not duplicate Spectral, oasdiff, GCP baseline, or publish steps in a new
  language workflow. Add them to the composite action instead.
- Do not place workflow files in subdirectories under `.github/workflows/`.

## Validation

Before finishing a code change in this repo, run the relevant focused tests and,
when practical, the full local suite:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -v
```

Coverage is measured against `scripts/` and enforced at 80%. pytest-cov runs automatically
via `addopts` in `pyproject.toml` — no extra flags needed. The final pytest output line will
confirm `Required test coverage of 80% reached` or fail the run if it drops below.
