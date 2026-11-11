#!/usr/bin/env bash
# install-gitleaks.sh <dest-dir> - install the gitleaks that gitleaks.version
# pins into <dest-dir>/gitleaks, from the official release tarball, verified
# against the sha256 that gitleaks.version records. CI's leak and test jobs
# call it; a contributor runs it once (bash tools/leak-gate/install-gitleaks.sh
# ~/.local/bin).
#
# gitleaks.version is ONE line: `<tag> <platform> <sha256> [<platform> <sha256>]...`,
# one pair per platform the fleet supports (linux_x64, linux_arm64, darwin_arm64),
# each sha256 copied from the release's checksums file. It stays one line because
# its other readers (leak_gate.py, bin/fleet, the commit-hygiene test) take the
# tag as the file's first word. The tarball is refused on any mismatch, and nothing is
# installed. The hash is sha256sum's where there is one, else shasum's (macOS).
#
# Exit codes: 0 installed, or the pinned version already at <dest-dir>;
# 2 usage; 3 wrong platform, download failure, checksum mismatch, or a binary
# that does not report the pinned version here (nothing is installed).
set -euo pipefail

die() { local code="$1"; shift; echo "install-gitleaks: $*" >&2; exit "$code"; }
[ $# -eq 1 ] || die 2 "usage: install-gitleaks.sh <dest-dir>"
dest="$1"
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
read -r tag pins < "$here/gitleaks.version" || die 3 "gitleaks.version cannot be read"
[ -n "${pins:-}" ] || die 3 "gitleaks.version wants: <tag> <platform> <sha256> [<platform> <sha256>]..."
version="${tag#v}"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) have=linux_x64 ;;
  Linux-aarch64) have=linux_arm64 ;;
  Darwin-arm64) have=darwin_arm64 ;;
  *) have="$(uname -s)-$(uname -m)" ;;
esac
platform="" sha="" pinned=""
set -- $pins
while [ $# -ge 2 ]; do
  pinned="$pinned $1"
  if [ "$1" = "$have" ]; then platform="$1" sha="$2"; fi
  shift 2
done
[ $# -eq 0 ] || die 3 "gitleaks.version wants: <tag> <platform> <sha256> [<platform> <sha256>]..."
[ -n "$sha" ] || die 3 "gitleaks.version pins${pinned}; this machine is $have - install gitleaks $tag from https://github.com/gitleaks/gitleaks/releases yourself"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 \
  || die 3 "neither sha256sum nor shasum is here to check the download with"

mkdir -p "$dest"
if [ -x "$dest/gitleaks" ] && [ "$("$dest/gitleaks" version 2>/dev/null || true)" = "$version" ]; then
  echo "install-gitleaks: gitleaks $tag already at $dest/gitleaks"
  exit 0
fi

name="gitleaks_${version}_${platform}.tar.gz"
url="https://github.com/gitleaks/gitleaks/releases/download/${tag}/${name}"
work="$(mktemp -d "${dest%/}/.gitleaks-install.XXXXXX")"
trap 'rm -rf -- "${work:?}"' EXIT
curl -fsSL --retry 3 -o "$work/$name" "$url" || die 3 "download failed: $url"
[ "$(sha256_of "$work/$name")" = "$sha" ] || die 3 "checksum mismatch for $name: refusing to install"
tar -xzf "$work/$name" -C "$work" gitleaks || die 3 "the tarball holds no gitleaks binary"
# The version check runs on the extracted binary, before anything reaches
# <dest-dir>: a binary that reports another version, or cannot run on this
# machine at all, is refused and nothing is installed.
got="$("$work/gitleaks" version 2>/dev/null || true)"
[ "$got" = "$version" ] || die 3 "the tarball's binary reports '${got:-nothing it can run}', not $version: refusing to install"
install -m 0755 "$work/gitleaks" "$dest/gitleaks"
echo "install-gitleaks: installed gitleaks $tag at $dest/gitleaks (sha256 of $name verified)"
