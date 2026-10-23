# Changelog

## [0.5.0](https://github.com/nrgmr/rp-ci-tooling/compare/v0.4.0...v0.5.0) (2026-10-23)


### Features

* **ci:** add a shared coverage gate AB[#33690](https://github.com/nrgmr/rp-ci-tooling/issues/33690) ([fb6923b](https://github.com/nrgmr/rp-ci-tooling/commit/fb6923b8da1d5817993202764fccc8aa216e72cf))
* **ci:** add a shared coverage gate AB[#33690](https://github.com/nrgmr/rp-ci-tooling/issues/33690) ([d2bbcc3](https://github.com/nrgmr/rp-ci-tooling/commit/d2bbcc3a7f0712e3863199ede392b5180edbd564))


### Bug Fixes

* **ci:** count LCOV totals once per file and reject records without a file AB[#33690](https://github.com/nrgmr/rp-ci-tooling/issues/33690) ([96a4c2e](https://github.com/nrgmr/rp-ci-tooling/commit/96a4c2ebeb6de439ac998ace5f816b54324a1c8a))
* **ci:** harden coverage gate file matching and input handling AB[#33690](https://github.com/nrgmr/rp-ci-tooling/issues/33690) ([81d4bd6](https://github.com/nrgmr/rp-ci-tooling/commit/81d4bd62affed11f7dfb38182b1a736d0d27fbbe))
* **ci:** suffix matrix artifact names and count LCOV totals per record AB[#33690](https://github.com/nrgmr/rp-ci-tooling/issues/33690) ([8f69e00](https://github.com/nrgmr/rp-ci-tooling/commit/8f69e00f2df9c70def2adfc7b38c46f997060de6))

## [0.4.0](https://github.com/nrgmr/rp-ci-tooling/compare/v0.3.0...v0.4.0) (2026-09-30)


### Features

* **ci:** add notify-teams action and route major version bump notice AB[#33551](https://github.com/nrgmr/rp-ci-tooling/issues/33551) ([7ceaf3a](https://github.com/nrgmr/rp-ci-tooling/commit/7ceaf3ac92ac1631d21142fb51e2c3329a6cbb07))
* **ci:** add notify-teams action and route major version bump notice AB[#33551](https://github.com/nrgmr/rp-ci-tooling/issues/33551) ([92f17d5](https://github.com/nrgmr/rp-ci-tooling/commit/92f17d56ecbceb1392687cc8f63ee2cc9557f202))


### Bug Fixes

* **ci:** cap the breaking-change list under the Teams payload limit ([2a1d223](https://github.com/nrgmr/rp-ci-tooling/commit/2a1d2230ab1cbb43b81c956ec52c170c2ece6ce3))
* **ci:** list only ERR-level changes and name the notice after the merge ([8b5c44c](https://github.com/nrgmr/rp-ci-tooling/commit/8b5c44c19f73bd8fe88e83df6d400a5a8ba41c52))
* **ci:** send notify-teams messages as an Adaptive Card ([7cbf26a](https://github.com/nrgmr/rp-ci-tooling/commit/7cbf26a312f0be1d6580a19b218e3bb1cf77fca6))
* **ci:** surface failed Teams posts and split the breaking-change secret ([a22c23e](https://github.com/nrgmr/rp-ci-tooling/commit/a22c23e562c4097e4759069f122d650db5460361))

## [0.3.0](https://github.com/nrgmr/rp-ci-tooling/compare/v0.2.1...v0.3.0) (2026-09-22)


### Features

* add gitleaks and trivy-image workflows AB[#33419](https://github.com/nrgmr/rp-ci-tooling/issues/33419) ([14798bb](https://github.com/nrgmr/rp-ci-tooling/commit/14798bb8f4d6f6bd05006619ad4d019636f65968))
* **ci:** add ignore-unfixed input to image-scan.yml ([ab1f7cf](https://github.com/nrgmr/rp-ci-tooling/commit/ab1f7cf241b42d7911d04f155b9e8ec96e1ee63c))


### Bug Fixes

* **ci:** bump actions/checkout and google-github-actions/auth off node20 ([24eec32](https://github.com/nrgmr/rp-ci-tooling/commit/24eec320f74bd2136880922ae8773814290d3871))
* **ci:** bump actions/checkout and google-github-actions/auth off node20 AB[#33462](https://github.com/nrgmr/rp-ci-tooling/issues/33462) ([6353691](https://github.com/nrgmr/rp-ci-tooling/commit/6353691539b97205eb88d361fa973ede162c1b8e))
* **ci:** make SARIF upload best-effort in image-scan.yml ([bcd6518](https://github.com/nrgmr/rp-ci-tooling/commit/bcd65184b71aed9d14d37ca086052870bbd84f91))
* **ci:** pin setup-uv to a resolvable tag ([be045ee](https://github.com/nrgmr/rp-ci-tooling/commit/be045eec7999c8c60ae4644d4ac17c607f503600))
* **ci:** pin trivy-action/upload-sarif to valid refs, parameterize gitleaks scope ([0f35001](https://github.com/nrgmr/rp-ci-tooling/commit/0f35001dda69310170c4e37bb1e5a511a5b350a4))
* **ci:** switch image-scan.yml to table output, drop SARIF upload ([db67400](https://github.com/nrgmr/rp-ci-tooling/commit/db6740072c6f17e9a9d8a56112f62ce300f819b3))
* **workflows:** checkout before GCP auth and gate SARIF upload on file presence ([7a1c1b8](https://github.com/nrgmr/rp-ci-tooling/commit/7a1c1b8715d3b3c192c368464e45713f2148738f))

## [0.2.1](https://github.com/nrgmr/rp-ci-tooling/compare/v0.2.0...v0.2.1) (2026-09-18)


### Bug Fixes

* baseline-fetch existence check tolerant of gcloud error wording AB[#33425](https://github.com/nrgmr/rp-ci-tooling/issues/33425) ([9058e6a](https://github.com/nrgmr/rp-ci-tooling/commit/9058e6a6c08c09d72cbff0966b3d34eeb83b326a))
* **openapi-checks:** decide baseline existence from versions list, not download errors ([73939cb](https://github.com/nrgmr/rp-ci-tooling/commit/73939cbbb863923649d516aa87e9b52182605db1))

## [0.2.0](https://github.com/nrgmr/rp-ci-tooling/compare/v0.1.0...v0.2.0) (2026-09-16)


### Features

* add release-bot-token branch promotion workflows ([6fc0bea](https://github.com/nrgmr/rp-ci-tooling/commit/6fc0beaeed4b354faa678ed015254a5274ca7b83))
* add release-bot-token branch promotion workflows AB[#33175](https://github.com/nrgmr/rp-ci-tooling/issues/33175) ([e884150](https://github.com/nrgmr/rp-ci-tooling/commit/e88415042ca778e100210b7eabc485ae12d78309))
* fail loudly on fork-head merges in back-merge.yml ([42d80f6](https://github.com/nrgmr/rp-ci-tooling/commit/42d80f645d9e30555997a3d2a93052da8762804f))


### Bug Fixes

* address PR review findings on release-bot-token workflows ([2f73755](https://github.com/nrgmr/rp-ci-tooling/commit/2f7375509ef8abe779b9a3963479ea6a5eff503d))
* **release:** correct jsonpath filter for uv.lock version updater ([bf789b2](https://github.com/nrgmr/rp-ci-tooling/commit/bf789b23738f71e83468cc08fe7e7484073dd208))
* **release:** correct jsonpath filter for uv.lock version updater ([e420870](https://github.com/nrgmr/rp-ci-tooling/commit/e420870cbe82842c7333d50311a65f6ac06a68ef))
* **release:** keep uv.lock version in sync with release-please bumps ([e59b4c0](https://github.com/nrgmr/rp-ci-tooling/commit/e59b4c0a7d2b9f080c97938a106d6f8da022bf26))
* **release:** keep uv.lock version in sync with release-please bumps ([bd5b03b](https://github.com/nrgmr/rp-ci-tooling/commit/bd5b03b94a0d0b52b103f8860beee90040acf2d6))

## 0.1.0 (2026-06-08)


### Features

* add 80% coverage enforcement and fix duplicate CI runs ([753be82](https://github.com/nrgmr/rp-ci-tooling/commit/753be82e58512f2efa4b60db57b993d1f5946239))
* initial reusable CI/CD workflows and tooling ([2b587e7](https://github.com/nrgmr/rp-ci-tooling/commit/2b587e73255c7f4ef352f011b123b2f09583f515))
* initial reusable CI/CD workflows and tooling AB[#28657](https://github.com/nrgmr/rp-ci-tooling/issues/28657) ([e5cee82](https://github.com/nrgmr/rp-ci-tooling/commit/e5cee82ce607ec8cac9e4355023ebdcd1267d67f))
* promote service-account and gar-project from secrets to inputs ([d3ab4d0](https://github.com/nrgmr/rp-ci-tooling/commit/d3ab4d0c4f0121f82e066ebf6ac889044898259e))
* promote workload-identity-provider from secret to workflow input ([ec2c16a](https://github.com/nrgmr/rp-ci-tooling/commit/ec2c16a05e9bc5ac0ce9c442e05a0e9fe09a3668))


### Bug Fixes

* correct oasdiff download filename for v1.15.3 ([6c24136](https://github.com/nrgmr/rp-ci-tooling/commit/6c24136b98a5323e9de1c85b144268c13b720443))
* move working-directory from defaults to each run step ([ef0e4bf](https://github.com/nrgmr/rp-ci-tooling/commit/ef0e4bf4196e5878637e01bc86dd2466955446f4))
* queue concurrent release-please runs instead of racing ([8a23ec1](https://github.com/nrgmr/rp-ci-tooling/commit/8a23ec1a86de21edf912047c891066dc13f7597e))
* **workflow:** accept ci-tooling-token secret for self-checkout ([d55823c](https://github.com/nrgmr/rp-ci-tooling/commit/d55823c8dd12b8a4b2a9c8aff2e42c7f18f7cf49))
* **workflow:** quote verify-spec run step to fix YAML parse error ([ae0f18b](https://github.com/nrgmr/rp-ci-tooling/commit/ae0f18be85140f36da32483bfa3cebda7da4db7e))
* **workflow:** remove empty secrets key from workflow_call inputs ([c6c4ac5](https://github.com/nrgmr/rp-ci-tooling/commit/c6c4ac5e7141fede545631bcfd5d1b47f1dbed3d))
* **workflow:** use pull_request_target so fork PRs can report title check status ([eddb532](https://github.com/nrgmr/rp-ci-tooling/commit/eddb532aed8724ffce141f39a3ce5672b8f08768))
