# Workflow Reference

Detailed reference for each reusable workflow in this repo. For pinning and versioning guidance, see [README.md](../README.md).

Examples use the sample tag `v1.2.0`; replace it with the released tag the service is adopting. Do not pin service workflows to `@main`.

```yaml
uses: nrgmr/rp-ci-tooling/.github/workflows/<workflow>.yml@v1.2.0
```

## Contents

- [approve-staging.yml](#approve-stagingyml)
- [back-merge.yml](#back-mergeyml)
- [Branch promotion model](#branch-promotion-model)
- [Combined service workflow](#combined-service-workflow)
- [Composite actions](#composite-actions)
- [Coverage gate](#coverage-gate)
- [docker-build-push.yml](#docker-build-pushyml)
- [Environment variables](#environment-variables)
- [image-scan.yml](#image-scanyml)
- [python-lint-test.yml](#python-lint-testyml)
- [python-openapi-generate.yml](#python-openapi-generateyml)
- [release-promotion.yml](#release-promotionyml)
- [secret-scan.yml](#secret-scanyml)

---

## Coverage gate

The `coverage-gate` composite action applies thresholds to the coverage report a test job produces. Four checks apply. The ratchet and the baseline margin are skipped when `baseline-path` is empty, and when the file does not exist. The changed lines check is off until `min-changed-coverage` is set:

- **Overall:** total line coverage must be at least `min-coverage`.
- **Ratchet:** overall coverage must not fall below the value in `baseline-path`, a JSON file such as `{"overall": 83.2}` committed in the service repo. The comparison rounds both the measured coverage and the baseline to two decimals. The overall minimum is compared unrounded, so 79.996% fails an 80% minimum even though it displays as 80.00%. A missing file skips the check and logs a notice, so a team can adopt the ratchet by committing the first baseline. Check the notice if the ratchet never fails, since a mistyped path looks the same. An empty or unrecognised report is an error, not a pass.
- **Baseline margin:** overall coverage must not exceed the baseline by more than `baseline-margin` percentage points, `1` by default. The baseline file is edited by hand, so without this check it falls behind as coverage improves and the ratchet protects less over time. A pull request that adds tests past the margin fails until it also raises `overall` in the baseline file, and the failure message gives the value to write. Set `baseline-margin` to `"0"` to require an exact match, or to an empty string to turn the check off. Like the others, it only warns when `fail-on-threshold` is `false`.
- **Changed lines:** the lines a pull request adds or modifies must reach `min-changed-coverage` combined, so new code is held to a standard even when the overall figure is high enough to absorb it. Only lines the report marks as executable count, so comments, blank lines, and imports do not. The figure is covered lines over total lines across all files, not an average of per-file percentages. Files the report does not cover, such as tests, docs, and workflow files, are ignored, and the check is skipped with a notice when no changed line appears in the report. It runs only on `pull_request` events, comparing the merge commit with the base branch, and is skipped with a notice on other events. It needs a git checkout, so run it after `actions/checkout`. The job summary and pull request comment list each changed file under `working-directory` by its path relative to `working-directory`, lowest coverage first and capped at 20. A changed file the report omits, such as one excluded from coverage, is skipped. When a report path could name several files and one of them changed, the job logs a warning that names the file it used. The usual cause is a `working-directory` that spans several modules.

A reviewer should question any pull request that lowers a baseline file, because it quietly weakens the ratchet. Two open pull requests that both raise the same baseline conflict on that file, so the second resolves it after the first merges. Measure the first baseline on the CI runner, not locally, since results can differ by a few hundredths between platforms.

The report format follows the file extension: `.xml` is JaCoCo or Cobertura, and any other extension is read as LCOV.

Results appear in the job summary whenever the report is readable. The coverage report is uploaded for 7 days as an artifact named `coverage-<working-directory>-<report file>`, such as `coverage-api-coverage.xml`, so calls for different directories do not collide. Nothing is uploaded when the tests fail.

### Coverage gate inputs

These inputs configure the thresholds. [coverage-gate](#coverage-gate-1) lists the remaining inputs.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `min-coverage` | No | `80` | Minimum overall line coverage percentage |
| `baseline-path` | No | `""` | Ratchet baseline file, relative to `working-directory`. Empty disables the ratchet and the baseline margin. |
| `baseline-margin` | No | `1` | Maximum percentage points coverage may exceed the baseline before the job fails, so a change that raises coverage must also raise the baseline file. Applies only when `baseline-path` is set and the file exists. Empty disables it. |
| `min-changed-coverage` | No | `""` | Minimum combined line coverage percentage of the lines a pull request adds or changes. Runs only on `pull_request` events, after the repository is checked out, and counts only lines the report marks as executable. Empty disables it. |
| `fail-on-threshold` | No | `true` | When `false`, a violation is reported as a warning and the job passes. Use it as a temporary on-ramp, not a permanent setting. |
| `comment-on-pr` | No | `false` | Post the result as a pull request comment, updated in place on each run, with one comment per report so calls for different projects do not overwrite each other. The calling workflow must grant `pull-requests: write`. Fork PRs cannot comment, and the comment step never fails the job. |

---

## Environment variables

The [export-env-vars](#export-env-vars) and [clear-env-vars](#clear-env-vars) actions pass environment variables, such as registry credentials, to the build and test steps of a job. Use them for what a private dependency needs, such as `UV_INDEX_*_PASSWORD` for a private Python index. The actions do not know any variable names, so a new need never requires a change here.

Run `export-env-vars` right before the first step that needs the variables, and `clear-env-vars` with `if: always()` right after the last one, so the coverage gate and anything that runs after it never see the values. `export-env-vars` can run more than once before the single clear step.

```yaml
steps:
  - uses: nrgmr/rp-ci-tooling/.github/actions/export-env-vars@v1.2.0
    with:
      env-vars: '{"CI_REGION":"us-west1"}'
      # toJSON quotes and escapes the value, so a quote or newline in it cannot break the JSON.
      secret-env-vars: '{"UV_INDEX_PRIVATE_PASSWORD":${{ toJSON(secrets.PRIVATE_INDEX_PASSWORD) }}}'
  - run: uv sync && uv run pytest
  - name: Clear caller environment variables
    if: always()
    uses: nrgmr/rp-ci-tooling/.github/actions/clear-env-vars@v1.2.0
```

### Limits

- **Strings only.** Every value must be a JSON string, so write `"8080"`, not `8080`. Malformed JSON, a non-string value, or an invalid name fails the job before any step runs.
- **Reserved names.** Names must match `[A-Za-z_][A-Za-z0-9_]*`. `GITHUB_*`, `RUNNER_*`, `ACTIONS_*`, `PATH`, `HOME`, `SHELL`, `CI`, `BASH_ENV`, `ENV`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, and `RP_EXPORTED_ENV_NAMES`, which the actions use to track what to clear, are rejected, so a caller cannot change how the runner or the shared steps behave. `NODE_OPTIONS` is also rejected, because the runner does not allow it in `GITHUB_ENV`. Set it in an `env:` block on the step that needs it instead.
- **Visibility.** A variable is visible only to the steps between the export and the clear step. That includes the scripts, plugins, and dependencies those commands run, which cannot be avoided if they need the credential. Earlier steps never see it, so a variable needed by an earlier step cannot be supplied this way. Later steps see an empty value. Do not add a third-party action between the export and the clear step.
- **Masking is by exact value.** A multi-line value is masked line by line. A derived form of a secret, such as its base64 encoding, is not masked. A very short or common value masks every occurrence of it in the logs.
- **Duplicates.** A name in both `env-vars` and `secret-env-vars` takes the secret value.
- **No fork or Dependabot secrets.** Secrets are not passed to pull requests from forks or to Dependabot, and `GITHUB_TOKEN` is read-only there, so a private install fails on those runs. This is expected.
- **Size.** A GitHub secret is limited to 48 KB, which bounds `secret-env-vars` as a whole.
- **Caller escapes the JSON.** The action cannot fix JSON the caller built badly. Use `toJSON()` for secret values, as in the example above.

---

## python-lint-test.yml

Runs ruff lint and format checks plus pytest against a Python service using uv.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `project-dir` | No | `.` | Directory containing the `pyproject.toml` |

### Usage

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  lint-test:
    uses: nrgmr/rp-ci-tooling/.github/workflows/python-lint-test.yml@v1.2.0
    with:
      project-dir: sidecar
```

---

## python-openapi-generate.yml

Generates an OpenAPI spec from a Python FastAPI service, then runs the shared OpenAPI checks: Spectral lint, oasdiff version enforcement, concurrent-version-limit check, and GCP baseline fetch/publish.

The workflow expects `project-dir` to be a uv project with `main.py` exporting a FastAPI app named `app`. It installs production dependencies with `uv sync --no-dev`, runs the repo-provided generator, and validates that the generated spec is JSON before running the shared checks.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `project-dir` | No | `.` | Directory containing the `pyproject.toml` |
| `gen-spec-env` | No | `{}` | JSON object of env vars needed during spec generation (dummy values are fine) |
| `gar-repository` | Yes | | Artifact Registry repository name |
| `package-name` | Yes | | Package name used to store the prod spec in Artifact Registry |
| `gar-location` | No | `us-central1` | Artifact Registry region |
| `workload-identity-provider` | Yes | | GCP Workload Identity Provider used to authenticate GitHub Actions to GCP |
| `service-account` | Yes | | GCP service account email used by CI |
| `gar-project` | Yes | | GCP project hosting Artifact Registry |
| `override-version-limit` | No | `false` | Allows the version-limit gate to warn instead of fail when route retirement is already in progress |

### Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `TEAMS_API_BREAKING_WEBHOOK_URL` | No | Teams incoming webhook URL for the route major version bump notice. Unset skips the notice with a step-summary note, never fails the job. |

The notice is for API consumers across teams, so this secret is meant to be set once at the organization level, pointing at a shared channel. It is separate from `back-merge.yml`'s `TEAMS_WEBHOOK_URL`, whose stale-approval notice concerns only the repo's owners.

### Usage

```yaml
name: API checks

on:
  push:
    branches: ["**"]
  pull_request:
  workflow_dispatch:
    inputs:
      override-version-limit:
        description: "Allow a temporary third route version when retirement is already in progress"
        type: boolean
        default: false

jobs:
  api-checks:
    uses: nrgmr/rp-ci-tooling/.github/workflows/python-openapi-generate.yml@v1.2.0
    with:
      project-dir: sidecar
      gen-spec-env: '{"UM_BASE_URL": "http://localhost", "PUBLIC_ORIGIN": "http://localhost"}'
      gar-repository: my-service
      package-name: my-service
      workload-identity-provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github
      service-account: nrg-elp-ci-prod-gha@nrg-bootstrap-master.iam.gserviceaccount.com
      gar-project: nrg-platsvc-elp-prod
      override-version-limit: ${{ inputs.override-version-limit || false }}
    secrets: inherit
```

### API check behavior

On every run the workflow checks out the caller repo and this tooling repo, generates `/tmp/openapi.json`, validates it as JSON, then:

1. **Spectral lint** - validates the spec against the shared RP Spectral ruleset, or the service's `.spectral.yaml` if present.
2. **GCP auth and baseline fetch** - runs on pull requests, manual `workflow_dispatch` runs, and pushes to `main`. Non-fork PRs, manual runs, and `main` pushes fail if GCP auth is unavailable. Fork PRs and non-main branch pushes still generate the spec and run local checks, but cannot run baseline diff or publish.
3. **Baseline selection** - downloads the latest immutable `sha-*` Artifact Registry version for the package. If no `sha-*` version exists, it falls back to `prod-baseline`. If no baseline exists, the run is treated as a new service or first deploy.
4. **Version enforcement** - when a baseline exists, compares the generated spec against the baseline using oasdiff. Non-breaking OpenAPI changes pass without a route version change. Breaking changes require a new major version path for each affected route. `info.version` is treated as OpenAPI metadata and is not used as a pass/fail gate.
5. **Concurrent version limit** - blocks the run if the current generated spec contains more than 2 live major versions for any route, or exactly 2 non-consecutive major versions for a route. This check does not need a prod baseline. `override-version-limit` converts this specific violation into a warning.
6. **PR comments** - on PRs, updates bot comments for new services with no baseline, breaking API changes, and version-limit violations or overrides.
7. **Baseline publish** - on a successful push to `main`, uploads the generated spec as `sha-${{ github.sha }}` and refreshes `prod-baseline` as a compatibility alias. Future checks prefer the latest `sha-*` baseline.
8. **Major version bump notice** - when that push ships a route major version bump, posts to `TEAMS_API_BREAKING_WEBHOOK_URL`: the service, the old and new route versions, oasdiff's breaking changes grouped by type (capped at about 20 KB, with a closing "... N more" line pointing at the spec artifact, since Teams rejects payloads over 28 KB), and links to the PR (or commit), the published spec and the deprecation policy.

#### Route versioning rules

Routes are identified by their full path with the version segment normalized to `/v{N}`. Prefixes, suffixes, and the rest of the path all remain significant.

These are the **same route** across versions:

```text
/api/v1/auth/users
/api/v2/auth/users
```

These are **different routes**:

```text
/api/v1/auth/users
/api/v2/auth/roles
/internal/v2/auth/users
```

If `/api/v1/auth/users` has a breaking change, the replacement route must be `/api/v2/auth/users`. Adding only `/api/v2/auth/status` does not satisfy the rule.

At most two major versions of the same normalized route may be live at once, and two coexisting versions in the current spec must be consecutive. If prod has `v1` and `v2`, a PR may retire `v1` and introduce `v3` in the same current spec, leaving only `v2` and `v3`. A current spec containing `v1`, `v2`, and `v3` is blocked. Use `override-version-limit` only when retirement is already tracked and in progress.

For the manual override checkbox to appear, the caller workflow must define the `workflow_dispatch.inputs.override-version-limit` input and pass it through to `python-openapi-generate.yml`, as shown in the examples above.

#### Spectral overrides

A service can add a `.spectral.yaml` at its repo root to extend or adjust the shared ruleset:

```yaml
extends: [".rp-ci-tooling/spectral/rp-base.spectral.js"]
rules:
  operation-description: warn
```

Overrides should be narrow and intentional. They apply only to the repo that declares them.

The shared ruleset enforces OpenAPI validity, contact metadata, operation summaries and descriptions, success responses, response descriptions, defined/described tags, and the rule that every non-probe API path has exactly one version segment like `/v1`. The concurrent route version limit is enforced separately by `scripts/openapi_version_limit_check.py` so the workflow can support `override-version-limit` without weakening the base Spectral ruleset.

---

## docker-build-push.yml

Builds a Docker image on every run. Pushes the commit SHA tag to Artifact Registry only on pushes to `develop`, `staging`, and `main`; `main` also pushes `latest`. Pull requests and other branch pushes build the image but do not push it.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `image-name` | Yes | | Docker image name |
| `gar-repository` | Yes | | Artifact Registry repository name |
| `gar-project` | Yes | | GCP project hosting Artifact Registry |
| `dockerfile` | No | `./Dockerfile` | Path to the Dockerfile |
| `context` | No | `.` | Docker build context |
| `gar-location` | No | `us-central1` | Artifact Registry region |

### Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `WORKLOAD_IDENTITY_PROVIDER` | Yes | Authenticate GitHub Actions to GCP |
| `SERVICE_ACCOUNT` | Yes | GCP service account used by CI |

### Usage

```yaml
name: Docker

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  docker:
    uses: nrgmr/rp-ci-tooling/.github/workflows/docker-build-push.yml@v1.2.0
    with:
      image-name: my-service-sidecar
      dockerfile: ./sidecar/Dockerfile
      context: ./sidecar
      gar-repository: my-service
      gar-project: my-gcp-project
    secrets: inherit
```

---

## secret-scan.yml

Scans for secrets with [gitleaks](https://github.com/gitleaks/gitleaks). Language-agnostic: every service can call this the same way regardless of what `python-lint-test.yml` / `docker-build-push.yml` variant it also uses.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `mode` | No | `full-history` | `full-history` scans the entire commit history. `pr-diff` scans only the commits new to this PR (`origin/<base>..HEAD`); requires a `pull_request` trigger. Either mode fails the job on a finding, on every trigger, including `schedule`. |

`full-history` rescans the entire history on every run, not just the diff. Adopting it on a repo with a real, unbaselined leak fails every run where this check exists. Before enabling it, run `gitleaks detect --source . -v` locally against the adopting repo and add a [`.gitleaksignore`](https://github.com/gitleaks/gitleaks#creating-a-baseline) baselining anything it finds.

`pr-diff` avoids that adoption hazard entirely, at the cost of never seeing a secret already sitting in history. It reads `github.base_ref`, which only a `pull_request` trigger sets, so a `pr-diff` job fails immediately with an explicit error on any other trigger rather than scanning an empty range. A caller wanting `pr-diff` on pull requests and a periodic deep scan should use two jobs: `pr-diff` on `pull_request`, and the `full-history` default on `schedule`.

Whether a failure here blocks a merge is a branch-protection decision on the caller's repo - mark this job a required status check, or don't - not something this workflow encodes. That also means the same workflow works unchanged on a `schedule` trigger, where there is no PR to block and a failure is the only signal.

### Usage

```yaml
name: Secret scan

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  secret-scan:
    uses: nrgmr/rp-ci-tooling/.github/workflows/secret-scan.yml@v1.2.0
```

---

## image-scan.yml

Scans an image already pushed to Artifact Registry with [Trivy](https://github.com/aquasecurity/trivy-action) and prints the findings as a table in the job log. Reads the image back from the registry, so it works whether the caller built with `docker-build-push.yml` or pushed server-side via Cloud Build - only a pullable reference is required. Fails the run (`exit-code: 1`) on any finding at or above `severity`.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `image-ref` | Yes | | Fully qualified image reference to scan, including tag or digest |
| `workload-identity-provider` | Yes | | GCP Workload Identity Provider used to read the image from Artifact Registry |
| `service-account` | Yes | | GCP service account impersonated to read the image |
| `gar-location` | Yes | | Artifact Registry region, used to configure the docker credential helper |
| `severity` | No | `CRITICAL,HIGH` | Comma-separated severities that fail the scan |
| `ignore-unfixed` | No | `true` | Exclude vulnerabilities with no available fix from the scan. Set to `false` to gate on unfixed findings too. |

A reusable workflow's job permissions are capped by the caller's grant, so the caller must declare `id-token: write` (for the GCP OIDC auth step) itself, exactly as shown below - omitting it leaves the job with read-only access and the scan fails at runtime.

### Usage

```yaml
name: Image scan

on:
  workflow_dispatch:

jobs:
  scan:
    permissions:
      contents: read
      id-token: write
    uses: nrgmr/rp-ci-tooling/.github/workflows/image-scan.yml@v1.2.0
    with:
      image-ref: us-west1-docker.pkg.dev/my-gcp-project/my-service/my-image:abc1234
      workload-identity-provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github
      service-account: nrg-elp-ci-prod-gha@nrg-bootstrap-master.iam.gserviceaccount.com
      gar-location: us-west1
```

---

## Branch promotion model

`back-merge.yml`, `approve-staging.yml`, and `release-promotion.yml` together implement one `develop -> staging -> main` promotion model. Each workflow is documented on its own below; this section shows how they fit together.

**Branch topology** — `release/*` branches are dedicated, frozen cuts; nothing merges into `staging` or `main` from a trunk branch directly.

```mermaid
%%{init: {"themeVariables": {"edgeLabelBackground": "transparent"}}}%%
flowchart LR
    DEV[develop]
    STG[staging]
    MAIN[main]
    FIX["fix/* or cherry-pick/*"]
    HOTFIX["hotfix/*"]

    DEV -->|"promote via release-promotion.yml"| STG
    FIX -->|"human merge"| STG
    HOTFIX -->|"human merge"| MAIN
    STG -->|"promote via release-promotion.yml"| MAIN

    STG -.->|"back-merge.yml"| DEV
    MAIN -.->|"back-merge.yml"| STG
    MAIN -.->|"back-merge.yml"| DEV
```

Each promotion arrow above cuts a dedicated `release/*` branch that a human then merges; see [back-merge.yml](#back-mergeyml) and [release-promotion.yml](#release-promotionyml) below for exact mechanics. Every back-merge arrow runs a file-diff check, not a commit-count check.

**The approval lifecycle** — a race, not a fixed sequence: whichever happens first between another merge into `staging` and the next promotion decides whether the approval survives to be used.

```mermaid
sequenceDiagram
    participant Staging as staging branch
    participant Approve as approve-staging.yml
    participant Tag as approved-staging tag
    participant BackMerge as back-merge.yml
    participant Promo as release-promotion.yml

    Approve->>Tag: force-move to staging's tip
    Note over Tag: staging is now "approved"
    alt another fix merges into staging first
        Staging->>BackMerge: triggers on merge
        BackMerge->>Tag: staging != tag -> delete
        BackMerge-->>BackMerge: notify Teams (if configured)
    else promotion runs before anything else lands
        Promo->>Tag: read the approved commit
        Promo->>Promo: cut release/*-main from it
    end
```

---

## back-merge.yml

Opens a pull request carrying a fix back down to the branch(es) below it, whenever a merge into `staging` or `main` leaves the branch below it missing commits. Never merges automatically — merging stays a human decision.

Runs on every merge into `staging` or `main`, including ordinary promotions — it does not infer intent from the head branch's name or prefix. Instead, for each candidate target below the branch that was just merged into, it asks whether the target's files actually differ from what's now on the merged-into branch (`gh api compare/<target>...<base>`, counting `.files`, not `.commits`) — a merge, squash, or rebase always produces at least one commit unique to the target by SHA even when nothing really changed, so a commit-count check would misfire on every ordinary promotion. A promotion PR (`develop -> staging` via a `release/*` branch, `staging -> main` likewise) finds nothing to do, since the source already held everything the target just took. Anything else — a `fix/*` branch merged into `staging`, a `hotfix/*` branch merged into `main` — opens a back-merge into whichever branch(es) below it actually have different files. Branch-policy is a separate, repo-owned concern that governs who is allowed to merge directly into `staging` or `main` in the first place; this workflow only reacts to whatever cleared that gate.

Defaults to the `develop` / `staging` / `main` branch model. If your repo uses different names, pass `develop-branch`, `staging-branch`, and `main-branch` to match.

When the merge is into the staging branch, this workflow also checks whether its approval tag (`approved-<staging-branch>`, see `approve-staging.yml` below) still points at that branch's tip. If the branch moved past it, the tag is deleted — a stale approval tag left in place is a worse trap than no tag at all — and, if `TEAMS_WEBHOOK_URL` is configured, a notification is posted saying it needs re-approval before promoting. Purely informational: this never blocks anything, and a failed notification never fails the job.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `develop-branch` | No | `develop` | Branch that fixes merged into staging or main back-merge into |
| `staging-branch` | No | `staging` | Branch between develop and main in the promotion chain |
| `main-branch` | No | `main` | Production branch |

### Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `RELEASE_BOT_APP_ID` | Yes | App ID of the GitHub App installed on this repo for opening promotion PRs |
| `RELEASE_BOT_PRIVATE_KEY` | Yes | Private key for that GitHub App |
| `TEAMS_WEBHOOK_URL` | No | Teams incoming webhook URL. Unset skips the notification with a step-summary note — never fails the job. |

A pull request opened with `GITHUB_TOKEN` triggers no workflows, so this repo's own required checks would never start on the PRs this workflow opens. The GitHub App identity does not carry that restriction. Each calling repo creates and installs its own release-bot GitHub App, scoped to `Contents: Read and write` / `Pull requests: Read and write` on that repo only; the two secrets above must come from that App, not from `GITHUB_TOKEN`. `Contents: write` is required here, not just `Read`, because invalidating a stale `approved-<staging-branch>` tag deletes a Git ref.

GitHub withholds repository secrets from `pull_request`-triggered runs whenever the pull request's head is a fork, even after that pull request merges. This workflow detects that case and fails with a clear error rather than an opaque credential error from the token-mint step. A repo where every contributor pushes branches directly (no forks) is unaffected.

### Usage

```yaml
name: Back-merge

on:
  pull_request:
    types: [closed]

permissions:
  contents: read
  pull-requests: write

jobs:
  open:
    uses: nrgmr/rp-ci-tooling/.github/workflows/back-merge.yml@v1.2.0
    # Only needed if your branch names differ from the develop / staging / main defaults:
    # with:
    #   develop-branch: dev
    #   staging-branch: stage
    #   main-branch: production
    secrets: inherit
```

---

## approve-staging.yml

Marks the current tip of the staging branch as approved by force-moving a floating tag, `approved-<staging-branch>`, to point at it — the same floating-tag mechanic this repo's own `release-please.yml` uses for its major-version tag. `workflow_dispatch` only: approval is a deliberate human action, not something inferred from CI passing or a schedule.

Pass `require-approval: true` to `release-promotion.yml` (below) so a promotion resolves the exact commit this tag points at instead of the staging branch's live tip — a fix merged into it after approval can't silently ride an already-approved promotion. See `back-merge.yml` above for the other half: it invalidates this tag automatically the moment the staging branch moves past it.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `staging-branch` | No | `staging` | Branch to approve. Must match the `staging-branch` passed to `back-merge.yml`, since the tag name is derived from it. |

### Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `RELEASE_BOT_APP_ID` | Yes | App ID of the GitHub App installed on this repo |
| `RELEASE_BOT_PRIVATE_KEY` | Yes | Private key for that GitHub App |

Moving a tag is a write to repository contents, same as cutting a release branch in `release-promotion.yml` — the release bot App must be scoped `Contents: Read and write`.

### Usage

```yaml
name: Approve staging

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  approve:
    uses: nrgmr/rp-ci-tooling/.github/workflows/approve-staging.yml@v1.2.0
    # Only needed if your staging branch has a different name:
    # with:
    #   staging-branch: stage
    secrets: inherit
```

---

## release-promotion.yml

Cuts a dedicated branch (`release/<label>-<target-branch>`) from `source-branch`'s current tip and opens a pull request into `target-branch`. Never merges automatically. The dedicated branch freezes the source's content at cut time — later commits on `source-branch` do not silently join an already-open promotion, the way they would if the PR's head were `source-branch` itself.

Serves both legs of the `develop -> staging -> main` model from one parameterized workflow:

- **`develop -> staging`** (candidate cuts): caller has a `schedule` trigger and passes `cut-day` / `interval-weeks` / `anchor-date`. Runs (e.g. daily) because a `schedule` trigger cannot read a repository variable directly — the job checks those three inputs and no-ops most days unless a cut is actually due.
- **`staging -> main`** (on-demand promotion): caller has only `workflow_dispatch`, no `schedule`, and leaves the cadence inputs unset — every dispatch cuts.

Also skips cutting a new branch (regardless of cadence) when `source-branch` holds nothing `target-branch` doesn't already have, or when a `release/*` PR into `target-branch` is already open.

With `require-approval: true`, the branch is cut from the exact commit an `approved-<source-branch>` tag points at (see `approve-staging.yml` above), not from `source-branch`'s live tip — closing the gap where a fix merged in after approval would otherwise silently ride the promotion. The run fails clearly if that tag does not exist, rather than falling back to the live tip. This is the recommended setting for the `staging -> main` leg; the `develop -> staging` leg has no equivalent "approved" concept for `develop` and should leave this unset.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `source-branch` | Yes | | Branch to cut the release branch from |
| `target-branch` | Yes | | Branch the pull request targets |
| `cut-day` | No | `""` | Day of week a cut is due (e.g. `Monday`). Empty disables scheduled cuts. |
| `interval-weeks` | No | `""` | Cut cadence in weeks, relative to `anchor-date`. |
| `anchor-date` | No | `""` | Any past date (`YYYY-MM-DD`, UTC) that was a valid cut day. |
| `require-approval` | No | `false` | Cut from the `approved-<source-branch>` tag's commit instead of the live tip; fails if that tag doesn't exist. |

### Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `RELEASE_BOT_APP_ID` | Yes | App ID of the GitHub App installed on this repo for opening promotion PRs |
| `RELEASE_BOT_PRIVATE_KEY` | Yes | Private key for that GitHub App |

Same `GITHUB_TOKEN` limitation as `back-merge.yml` above — this workflow needs its own per-repo release-bot App. It also needs more than `back-merge.yml`: creating the dedicated branch is a write to repository contents, so the App must be scoped `Contents: Read and write`, not `Read` only.

### Usage

```yaml
name: Staging candidate

on:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  propose:
    uses: nrgmr/rp-ci-tooling/.github/workflows/release-promotion.yml@v1.2.0
    with:
      source-branch: develop
      target-branch: staging
      cut-day: ${{ vars.STAGING_CUT_DAY }}
      interval-weeks: ${{ vars.STAGING_CUT_INTERVAL_WEEKS }}
      anchor-date: ${{ vars.STAGING_CUT_ANCHOR_DATE }}
    secrets: inherit
```

```yaml
name: Prod promotion

on:
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  propose:
    uses: nrgmr/rp-ci-tooling/.github/workflows/release-promotion.yml@v1.2.0
    with:
      source-branch: staging
      target-branch: main
      require-approval: true
    secrets: inherit
```

---

## Combined service workflow

```yaml
name: Service CI

on:
  push:
    branches: ["**"]
  pull_request:
  workflow_dispatch:
    inputs:
      override-version-limit:
        description: "Allow a temporary third route version when retirement is already in progress"
        type: boolean
        default: false

jobs:
  lint-test:
    uses: nrgmr/rp-ci-tooling/.github/workflows/python-lint-test.yml@v1.2.0
    with:
      project-dir: sidecar

  api-checks:
    needs: lint-test
    uses: nrgmr/rp-ci-tooling/.github/workflows/python-openapi-generate.yml@v1.2.0
    with:
      project-dir: sidecar
      gen-spec-env: '{"UM_BASE_URL": "http://localhost", "PUBLIC_ORIGIN": "http://localhost"}'
      gar-repository: my-service
      package-name: my-service
      workload-identity-provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github
      service-account: nrg-elp-ci-prod-gha@nrg-bootstrap-master.iam.gserviceaccount.com
      gar-project: nrg-platsvc-elp-prod
      override-version-limit: ${{ inputs.override-version-limit || false }}
    secrets: inherit

  docker:
    needs: [lint-test, api-checks]
    uses: nrgmr/rp-ci-tooling/.github/workflows/docker-build-push.yml@v1.2.0
    with:
      image-name: my-service-sidecar
      dockerfile: ./sidecar/Dockerfile
      context: ./sidecar
      gar-repository: my-service
      gar-project: my-gcp-project
    secrets: inherit
```

---

## Composite actions

Workflows in this repo use these internally. Other repos can also call them directly from a step.

### openapi-checks

The checks behind `python-openapi-generate.yml`, for a spec generated by any language. Inputs mirror the workflow's (`spec-path`, `package-name`, `gar-repository`, `gar-location`, `override-version-limit`, `workload-identity-provider`, `service-account`, `gar-project`), plus:

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `teams-webhook-url` | No | `""` | Teams incoming webhook URL for the route major version bump notice. Empty skips the notice. |

### clear-env-vars

The step that ends the exposure started by [export-env-vars](#export-env-vars). It takes no inputs and sets every exported variable to an empty value for the remaining steps. Run it with `if: always()` after the last step that needs them, so a failed build still clears them. It does nothing when nothing was exported.

```yaml
- name: Clear caller environment variables
  if: always()
  uses: nrgmr/rp-ci-tooling/.github/actions/clear-env-vars@v1.2.0
```

### coverage-gate

Coverage thresholds for a JaCoCo, Cobertura, or LCOV report produced by any language. The inputs `min-coverage`, `baseline-path`, `baseline-margin`, `min-changed-coverage`, `fail-on-threshold`, and `comment-on-pr` behave as described under [Coverage gate](#coverage-gate). The remaining inputs are:

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `report-path` | Yes | | Coverage report, relative to `working-directory` |
| `working-directory` | No | `.` | Directory the report and `baseline-path` are relative to. Only files under it count for the changed lines check. In a repository with several modules, set it to the module folder and call the gate once per module, so a report path can only match files in that module. |
| `github-token` | No | `github.token` | Token used to fetch the base commit for the changed lines check and to post the pull request comment. The comment is updated in place only when a bot posted it, so a personal access token creates a new comment on every run. Keep the default unless the job needs another token. |

```yaml
# Replace v1.2.0 with the released tag your service is adopting.
- uses: actions/checkout@v4
- uses: nrgmr/rp-ci-tooling/.github/actions/coverage-gate@v1.2.0
  with:
    report-path: coverage.xml
    min-coverage: "80"
    baseline-path: coverage-baseline.json
    min-changed-coverage: "80"
```

### export-env-vars

The step behind [Environment variables](#environment-variables). Inputs `env-vars` and `secret-env-vars` each take a JSON object of string values, with an empty value skipping it, and the limits above apply. A later call adds to the names an earlier call recorded, so one `clear-env-vars` step blanks every batch. Secret values are masked before anything is written.

```yaml
- uses: nrgmr/rp-ci-tooling/.github/actions/export-env-vars@v1.2.0
  with:
    secret-env-vars: '{"NODE_AUTH_TOKEN":${{ toJSON(secrets.REGISTRY_TOKEN) }}}'
```

### notify-teams

Best-effort post to a Teams webhook. Plain text is wrapped in an Adaptive Card, because Teams Workflows webhooks accept a plain `{"text": ...}` payload with a 202 and then drop it. A JSON object is sent as-is. A failed post adds a `::warning::` annotation and a step-summary line, and never fails the job.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `webhook-url` | No | `""` | Teams incoming webhook URL. Empty skips the notification with a step-summary note. |
| `message` | Yes | | Plain text, or a complete JSON object payload |

```yaml
- uses: nrgmr/rp-ci-tooling/.github/actions/notify-teams@v1.2.0
  with:
    webhook-url: ${{ secrets.TEAMS_WEBHOOK_URL }}
    message: "Deploy of my-service finished."
```
