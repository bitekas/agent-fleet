## What this changes

<!-- One or two sentences: the behaviour before, the behaviour after, and why. -->

## Checklist

- [ ] The commit hooks are enabled in the clone these commits were made in:
      `git config core.hooksPath .githooks`, once per clone, with gitleaks at
      the pinned version installed (`CONTRIBUTING.md` section 1). They run the
      leak check on every commit and push and strip AI-attribution lines from
      commit messages.
- [ ] Every commit's author and committer e-mail is a GitHub no-reply address
      (`CONTRIBUTING.md` section 4).
- [ ] No commit message carries an AI-attribution line - a co-author or
      sign-off trailer naming an AI tool, or a generated-with footer. CI's
      commit-hygiene job rejects any commit that does.
- [ ] The tests ran locally and passed:
      `FLEET_CONTEXT_ROOT=tests/fixtures/install FLEET_HOST_CONFIG=tests/fixtures/host.json bash tests/run-all.sh`
      and `bash tests/gates/run.sh`.
- [ ] A new or changed check was seen failing on a deliberately broken input
      before it passed.
- [ ] No private value is in any file, path or commit: no real id, token,
      host name, e-mail address or path under a home directory. Fixtures use
      synthetic values.
- [ ] Prose is ASCII and in the present tense.

Outside pull requests are reviewed and merged by the repository owner alone,
in the GitHub web interface. CI does not run on a pull request from a fork: it
runs once the repository owner has reviewed it and pushed its commits to a
branch of this repository (`CONTRIBUTING.md` section 9).
