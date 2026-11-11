# Security

## Reporting a vulnerability

Report it privately through GitHub private vulnerability reporting: the repository's **Security** tab, then **Report a vulnerability**. Do not open a public issue or pull request for it. The repository owner reads every report.

## The commit gate's threat model

The commit gate catches **accidental** publication by an authorized writer: an identifier quoted from an agent's context, a commit message describing a private incident, a test fixture captured from a real terminal, a branch named after a private name, a private e-mail address as a commit author, a secret pasted into a file, an AI-attribution line in a commit message. It checks file contents (binary files included), file names, symlink targets, commit messages, author and committer identities and ref names, against public patterns, gitleaks and, on the maintainers' own hosts, a private deny list that never leaves those hosts. The hooks run it before each commit and push; CI runs the public half on every push to this repository with a read-only token and no secrets, and never on a pull request from a fork (CONTRIBUTING.md section 9). A writer who means to publish something can always do so, by skipping the hooks on a clone of their own; that is outside what the gate defends against, and CI's checks are what catch a commit that skipped them.
