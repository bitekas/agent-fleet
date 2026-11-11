# Contributing to agent-fleet

This repository must never carry a private value: no person's or organization's identifier, no private path, host or account, no secret, and no AI-attribution line in a commit message. The commit gate below enforces that on your machine, and CI enforces its public half on every push to this repository (section 9).

## 1. Enable the hooks (once per clone)

```bash
git config core.hooksPath .githooks
bash tools/leak-gate/install-gitleaks.sh ~/.local/bin
```

The hooks need `bash` (3.2 or newer), `python3` (3.11 or newer; CI runs 3.14), `grep` and `awk` (GNU or BSD), and gitleaks at the version `tools/leak-gate/gitleaks.version` pins. The installer downloads that release, checks its sha256 and refuses on a mismatch; it supports `linux_x64`, `linux_arm64` and `darwin_arm64`, and on another platform you install the pinned tag from the gitleaks release page yourself. A missing gitleaks, or one at another version, makes the hooks refuse every commit with exit 3 and the install command.

What the hooks do:

| Hook | Runs | Refuses |
|---|---|---|
| `pre-commit` | `tools/leak-gate/leak_gate.py --staged` | a leak in the staged change: file contents (binary files included), file names, symlink targets, a secret gitleaks recognises |
| `commit-msg` | `tools/commit-hygiene/ai-attribution.sh strip`, then `leak_gate.py --message --identity` | a leak in the message or in the author and committer; AI-attribution lines are removed, not refused |
| `pre-push` | `leak_gate.py --ref --range` and `ai-attribution.sh check-range` for every pushed ref | a leak or an AI-attribution line in any commit the push publishes, or a leak in a ref name |

A finding prints one line, `<where> <class>`, and the commit or push is refused. `<class>` is a public pattern's name, `ai-identity` (section 4), `gitleaks:<rule>`, or `deny#<n>`. A line that trips a public pattern by design (a placeholder id in a test fixture) goes in `tools/leak-gate/allow.txt`; `python3 tools/leak-gate/leak_gate.py --allow-entry <path>:<line>` prints its entry. An allowed line that changes is no longer allowed, and there is no inline ignore marker. The `pre-commit` hook reads `allow.txt` from your working tree; a push and CI judge a range by the `allow.txt` its tip commit carries, so commit the entry with the line.

The private half: on a maintainer's host (one installed with `fleet install`), the gate also checks a private deny list that lives in that host's install repository and never in this one. A finding from it prints `deny#<n>`, the entry's line number in that list, and never the matched text. On such a host a deny list that cannot be read refuses the commit (exit 3). On any other machine the hooks print one line saying the deny half did not run, and check everything else.

A host installed with `fleet install` sets `core.hooksPath` on its checkout, and every worktree made from it inherits it. The hooks resolve every path from the work tree's top level, so they run from any worktree.

## 2. Branches

Name a branch `<type>/<slug>` with one of these types, and no person's or agent's name in it:

`fix/<slug>`, `feat/<slug>`, `docs/<slug>`, `chore/<slug>`, `test/<slug>`

## 3. Commit messages

- Subject: `type(scope): subject`, with the types above (`feat`, `fix`, `docs`, `chore`, `test`) and no name prefix.
- No AI-attribution line: no `Co-Authored-By:` or `Signed-off-by:` trailer naming Claude or Anthropic, no `Claude-<word>:` provenance trailer, and no footer saying the change was generated, made, written, created, built or authored with, by or using Claude. Such a line counts at the margin, behind an indent, or behind a `> ` quote, which is how `git merge --squash` and a quoted `git log` write it. The `commit-msg` hook deletes such lines; the `commit-hygiene` CI check fails any pushed commit that still carries one (a commit made with `--no-verify`, or in a clone without the hooks). The list is `tools/commit-hygiene/ai-attribution.ere`; a trailer under another key, or naming another tool, is not on it. Every pattern is anchored at the start of a line, so prose that mentions one mid-sentence is kept. An AI tool as author or committer is refused by the identity check (section 4).
- Because the patterns are anchored at a line start, they reach the subject line too: a subject that starts with `Claude-<word>:`, in any case, is deleted by the hook.
- `.claude/settings.json` turns off the attribution Claude Code adds to commits and pull requests, for every session whose working directory is a clone or worktree of this repository.

## 4. Commit identity

Every commit's author and committer e-mail is a GitHub no-reply address (`<id>+<user>@users.noreply.github.com`). The hooks and CI check every author and committer. An address is a finding unless it is a GitHub no-reply address, `noreply@github.com` (the committer GitHub records for a change made in its web interface), `git@<host>`, or under `example.com`, `example.org` or `example.net`. An AI tool's own identity is the finding `ai-identity`: an address at `anthropic.com`, or the name `Claude` or `Claude Code` alone.

Maintainers' agents commit with their install manifest's `upstream.identity` (`.claude/fleet.json` in the install repository). An agent's service environment may set `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, and those variables outrank repository configuration, so the commit sets all four:

```bash
env GIT_AUTHOR_NAME="<upstream.identity.name>" GIT_AUTHOR_EMAIL="<upstream.identity.email>" \
    GIT_COMMITTER_NAME="<upstream.identity.name>" GIT_COMMITTER_EMAIL="<upstream.identity.email>" \
    git commit -m "type(scope): subject" -- <paths>
```

## 5. Tests

```bash
bash tests/run-all.sh       # every *.test.py, *.test.sh and *.test.mjs under .claude/skills/, bin/, lib/, systemd/, tools/
bash tests/gates/run.sh     # the structural gates, tests/gates/*.test.sh
```

`run-all.sh` prints the census of the tests it discovered and fails if any of them fails or does not run. A new test file named that way is picked up with no registration. Each test carries its own negative control: a check that cannot go red is a defect.

Some tests need dependencies from outside the repository. On CI the runner carries the system packages and each test job installs the rest (section 9). Install them once per clone or worktree, from its root:

```bash
python3 -m pip install -r .claude/skills/google-spreadsheet/installation/requirements.txt
sudo apt-get install -y xvfb x11vnc websockify xinput x11-utils x11-apps imagemagick
npm ci --prefix .claude/skills/agent-revive/signin_driver
cd .claude/skills/agent-revive/signin_driver
PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers" npx playwright install --with-deps chromium
```

The last command is the Chromium build the sign-in driver's tests drive. Without it, `profiles.test.mjs` and `share.test.mjs` exit 3 (NO VERDICT), and `run-all.sh` counts each as a failure. `node_modules/` and `browsers/` are gitignored, so a fresh worktree needs them again. On macOS, `brew install tmux` stands in for the `apt-get` line: the share test, the one that needs X11, runs on Linux only.

**Every fleet shell script runs on both systems the installer supports**: Linux (`linux_x64` and `linux_arm64`, a current bash and GNU userland) and macOS (`darwin_arm64`, `/bin/bash` 3.2 and BSD userland). So no associative arrays, `mapfile`, `readarray`, `${x,,}` or `${x^^}`, `|&` or `&>>`, no apostrophe in the word of a double-quoted `${x:-word}` (bash 3.2 does not parse the file), no `"${a[@]}"` of an array that may be empty while `set -u` is on (bash before 4.4 calls it unbound), and no `grep -P`, `stat -c`, `sed -i`, `date -d`, `find -printf`, or `timeout`, `setsid` or `flock` as a command. The `portable-shell` gate refuses each of those in a shell script or a `bash` block of a Markdown file (`tests/gates/gates.py`); a line that runs only on Linux carries `# linux-only: <reason>`, and `stat -c ... || stat -f ...` is the portable form of a file's mode. The `test-macos` check (`.github/workflows/ci-macos.yml`, section 9) runs the whole suite on the macOS runner under `/bin/bash` 3.2.

**A test that can run on one system only is listed in `tests/platforms.json`** with the system it runs on and a one-line reason naming the construct that ties it there. On the other system `run-all.sh` does not run it and prints it as SKIPPED with that reason, in the census and in the run. An entry that names no discovered test, repeats a path or carries no reason fails the run, and the change that makes such a test pass on both systems deletes its entry.

## 6. Landing a change (maintainers)

Maintainers land on `main` directly, from a branch, after CI has passed on the exact commit that lands:

```bash
git push -u origin fix/<slug>
# wait until test, gates, leak and commit-hygiene all succeed on that commit:
gh api repos/bitekas/agent-fleet/commits/<sha>/check-runs --jq '.check_runs[] | [.name, .conclusion] | @tsv'
git push origin fix/<slug>:main          # a fast-forward of main to that commit
git push origin --delete fix/<slug>
git branch -d fix/<slug>
```

If `main` moved, the fast-forward is refused: bring `origin/main` into the branch, push the branch, and wait for the four checks again.

## 7. Tags

Annotated tags `vMAJOR.MINOR.PATCH`, cut only on a `main` commit whose four checks passed:

- **MAJOR**: a change an install must act on - the manifest schema, a `CONTEXT.md` or `config.json` key a skill now requires, a command-line argument made required, a unit template change that needs a re-render.
- **MINOR**: a backward-compatible capability.
- **PATCH**: a fix.

```bash
git tag -a vX.Y.Z -m "vX.Y.Z" <sha>
git push origin vX.Y.Z
```

## 8. Outside pull requests

Pull requests from outside contributors are welcome. Fork the repository, enable the hooks (section 1), commit with your GitHub no-reply address (section 4), run the tests (section 5), and open the pull request against `main`. CI does not run on a pull request from a fork; it runs once the repository owner has reviewed the pull request and pushed its commits to a branch of this repository (section 9). The repository owner alone reviews and merges outside pull requests, in the GitHub web interface, and never approves a workflow run for a pull request from a fork (section 9 says why).

## 9. CI

Five checks run on every push to this repository (any branch, and `v*` tags), on every pull request from a branch of this repository, and on a manual dispatch:

| Check | Workflow | Runner labels |
|---|---|---|
| `test`, `gates`, `leak`, `commit-hygiene` | `.github/workflows/ci.yml` | `self-hosted`, `Linux`, `ARM64`, `agent-fleet-linux` |
| `test-macos` | `.github/workflows/ci-macos.yml` | `self-hosted`, `macOS`, `ARM64`, `agent-fleet-mac` |

The four `ci.yml` checks are the ones section 6 waits for and `fleet upgrade` requires on a tag (`CI_CHECKS` in `bin/fleet`); `test-macos` is not one of them. Both runners are the repository owner's own machine.

**The runner contract.** A job cannot install anything system-wide, so what the tests need from the system comes with the runner. Each test job's first step checks its runner's half and fails naming every command that is missing.

- **Linux** (`agent-fleet-linux`): Ubuntu 26.04, arm64. 26.04 because its x11vnc, 0.9.17, is the first with more than 5 mouse buttons: `share.test.mjs` proves side buttons 6-8 cannot reach X, and with 0.9.16 its control cannot deliver them at all, so the test issues no verdict. Jobs run as an unprivileged user without sudo. The runner carries these packages, each installed with `--no-install-recommends`:
  - the browser tests' tools: `xvfb`, `x11vnc`, `websockify`, `xinput`, `x11-utils`, `x11-apps`, `imagemagick`;
  - the libraries Playwright's Chromium loads on Ubuntu 26.04, with no font package: `libasound2t64`, `libatk-bridge2.0-0t64`, `libatk1.0-0t64`, `libatspi2.0-0t64`, `libcairo2`, `libcups2t64`, `libdbus-1-3`, `libdrm2`, `libgbm1`, `libglib2.0-0t64`, `libnspr4`, `libnss3`, `libpango-1.0-0`, `libx11-6`, `libxcb1`, `libxcomposite1`, `libxdamage1`, `libxext6`, `libxfixes3`, `libxkbcommon0`, `libxrandr2`, `libfontconfig1`, `libfreetype6`;
  - the base the jobs and tests use: `git`, `curl`, `ca-certificates`, `xz-utils`, `xauth`, `tmux`, `coreutils`, `systemd`.

  Its tool cache is `/opt/hostedtoolcache` (`RUNNER_TOOL_CACHE` and `AGENT_TOOLSDIRECTORY` in the runner's environment): `actions/setup-python`'s Linux builds are compiled for that prefix and, installed anywhere else, load the system's libpython and fail. A workflow never overrides either variable.
- **macOS** (`agent-fleet-mac`): macOS, arm64. `/bin/bash` 3.2 is the only bash, the userland is BSD, and there is no Homebrew. Apple's Command Line Tools provide `git`, `cc` and `make`. The runner user's `~/.local/bin` comes first on the job PATH and holds `python3.14` and `python3` (CPython 3.14 from python-build-standalone, installed under `~/.local/python/3.14`) and `tmux` (built from source). The job does not run `actions/setup-python`, whose macOS build installs a `.pkg` with sudo. `pip3` on PATH is the Command Line Tools' pip for Python 3.9, and the base 3.14 install is writable, so a job installs Python packages only with `python3 -m pip` inside its venv. The runner runs in the logged-in GUI session, so Chromium draws headful through WindowServer.
- **Both**: the runner empties the job's workspace before and after every job (a job hook) and updates itself. A job keeps its Python packages in a venv it creates afresh (`--clear`) under the runner's temporary directory, installs gitleaks into a directory of its own there, and downloads Chromium into its workspace, so no package a job installs reaches the next job, even where the runner cannot empty its temporary directory; what persists is the tool cache `actions/setup-python` and `actions/setup-node` fill, and the npm and pip download caches.

**Outside pull requests.** CI never runs for a pull request from a fork. Every job of both workflows carries the condition

```
if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
```

and the `workflow-safety` gate (`tests/gates/gates.py`) refuses a workflow with a job that lacks it, a trigger other than `push`, `pull_request` and `workflow_dispatch`, a runner outside the two label sets above, a permission beyond `contents: read`, or a secret. **That condition binds only the workflow files on this repository's branches.** A workflow run for a fork's pull request executes the pull request's OWN workflow files, so a fork that edits `.github/workflows/` can drop the condition, change the runner labels or add steps, and an approved run of it is that fork's code running on the repository owner's self-hosted runners. The repository's Actions settings are therefore the lock that holds: they require the repository owner's approval before any workflow run for an outside contributor's pull request starts, and while the repository is private they start none. **The rule: never approve a workflow run for a pull request from a fork.** An outside pull request gets CI only after the repository owner has reviewed it, its workflow files included, and pushed its commits to a branch of this repository, where they run as any other push. The repository owner alone reviews outside pull requests (section 8); agents never look at pull requests.
