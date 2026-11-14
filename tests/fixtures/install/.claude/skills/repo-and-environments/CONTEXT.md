# CONTEXT - repo-and-environments (FIXTURE)

A synthetic install's inventory, so a stranger can see what each section of
this file holds. Every value here is fake. The skill's `SKILL.md` states the
mechanism; this file names everything concrete. **Section numbers match
`SKILL.md`'s**; a section present in only one of the two files keeps its number
in both. `sections.test.py` in the skill reads this file's numbered headings.

---

## 0. Which file plays which role

| role in `SKILL.md` | file here |
|---|---|
| the deploy script | `tools/ship.sh` |
| the dev script | `tools/devstack.sh` |
| the ops library | `tools/lib.sh` |
| the env lookup table | `tools/env-table.sh` |
| the client env mirror | `src/env-table.ts` |
| the app config | `app.config.ts` |
| the build config | `eas.json` |
| the version file | `app-version.json` |
| the bump script | `tools/next-version.mjs` |
| the release workflow | `.github/workflows/ship.yml` |
| the backmerge workflow | `.github/workflows/sync-back.yml` |
| the provenance gate | `tools/check-artifact.sh` |
| the git hooks setup script | `tools/enable-hooks.sh` |
| the credential procedure for the environments' secrets | the install's setup guide, section "Secrets" |

## 1. The environments

| role | name here | cloud project | what it is for |
|---|---|---|---|
| dev-machine | `local` | (emulators only) | emulators + seed data |
| shared-dev | `dev` | `acme-example-dev` | everyday feature work |
| live | `prod` | `acme-example-prod` | real users |
| live-copy | `preprod` | `acme-example-preprod` | testing what ships against a copy of live's data |

Identifiers: `com.example.app` (live), `com.example.app.dev`,
`com.example.app.preprod`, each with a `.client` dev-client variant.

## 2. Which branch deploys where

The map is `branches` in `config.json`. All three branches exist on origin.

### 2.1 A lane with ONE identity is not on the branch map

None: this install has no single-identity publishing lane.

## 3. Standing rules: the local values

### 3.1 The rule, verbatim

"no new features, interfaces, or schema changes on the live branch".

### 3.2 Pushing: what exists here

On push: `ship.yml` and `sync-back.yml`. Everything else is the scheduled
`nightly.yml`, daily on `main`.

### 3.3 Worktrees: the local values

`repo.worktrees_dir`. Verify a landing with `git merge-base --is-ancestor`.

### 3.4 Git hooks

`bash tools/enable-hooks.sh`. The commit-msg hook strips AI-attribution
trailers; no CI job scans pushed messages.

### 3.5 Taking a bug report

Nothing install-specific.

## 4. Where a mobile build actually lands

| env | channel | store track | external tester group |
|---|---|---|---|
| dev | tester distribution | none | none |
| preprod | tester distribution | none | none |
| prod | the stores | internal | none |

### 4.1 The identity split: the shared values

One build-service project; one `build` counter in `app-version.json`.

### 4.2 The store track

`env-table.sh` key `store_track`.

### 4.3 The version number

Opt-out markers: `NO BUILD BUMP` and `NO MINOR BUMP`.

### 4.4 The tester-distribution lane

Group `testers` in `dev` and `preprod`.

### 4.5 The store release note

`bug fixes and improvements`

## 5. The backmerge

Branch protection: none on this plan. The no-deploy property: retained.

### 5.1 The path-filter base

`base: ${{ github.ref_name }}`.

### 5.2 The release-candidate mode

Gate-outcome file: none.

## 6. How a build gets its configuration

### 6.1 The env source files

`env/local`, `env/dev`, `env/preprod`, `env/prod`.

### 6.2 The telemetry slots

One crash-reporting project for every environment, separated by the
`environment` tag; `local`'s slot is empty.

### 6.3 The repo is the env source

Every profile pins its `environment:`.

### 6.4 The export allowlist

The framework's public prefix only.

### 6.4b The functions deploy

No per-environment function option.

### 6.5 The fan-out invariant

Native-feeding files: `env/local`, `env/dev`, `env/preprod`, `env/prod`.

### 6.6 The native backend config pairs

`config/<env>/` for `dev`, `preprod` and `prod`; none for `local`.

## 7. The provenance gate

Both platform halves validated against a real build.

## 8. Where the rest lives

The setup guide is `docs/setup.md`.
