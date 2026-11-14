#!/usr/bin/env python3
"""Regression guard for device-emulators/installation/check.

Runs the real check as a subprocess against the fleet's FIXTURE INSTALL
(tests/fixtures/install) and against copies of it in a temporary directory, with
FAKE platform tools on a PATH that holds nothing else, a temporary HOME, and no
network. Nothing outside the temporary directory is written, and no real SDK,
device, simulator or Mac is touched.

WHAT THIS PINS, and what removing each case would let through:

  - config.json and .install-state.json are read FROM THE INSTALL CONTEXT
    through fleetlib, and build.script and android.hypervisor_probe resolve
    against the INSTALL ROOT. Against the fixture install as committed, with
    every Android artifact faked present, the check must report STALE naming
    `fixture-host` (proving it read that state file and got past every artifact
    leg, so it resolved the fixture's scripts); a copy with this machine
    recorded must go green, and a copy whose build script is not executable
    must name the COPY's path - the same check, a different install, a
    different answer.
  - Every exit state: 0 OK; 1 STALE (older, newer, unreadable, absent record,
    another host only) and NO VERDICT (no install context); 2 NOT INSTALLED for
    each artifact leg, each naming its own cause.
  - The hypervisor leg runs BEFORE the AVD leg: with both broken, the line names
    the hypervisor. A probe that is missing, or raises, is NOT INSTALLED, never a
    skipped leg. A probe's "not probed" words reach the OK line.
  - The JDK leg qualifies on javac: a java with no javac is NOT INSTALLED.
  - The build CLI's session: no token and no stored session is NOT INSTALLED;
    either one alone passes that leg.
  - realpath, never abspath: run through a symlinked skill directory, the check
    still finds fleetlib and its own SKILL.md.
  - iOS off macOS: refused with no remote host; with one, the remote leg runs
    through a fake ssh - the hostname is resolved first (an unresolvable name is
    named as such, never as a key problem), a missing workdir is named as
    such, and a green remote leg says the BUILD credential is not covered.
    These cases run only off macOS, where they are the code path; on macOS the
    local Xcode path would run against the real machine, so they are skipped
    and the run says so.

NEGATIVE CONTROLS: each assertion is a pair with its opposite (STALE beside OK,
the hypervisor message beside the AVD message), and the run fails with NO
VERDICT if this machine's hostname is literally `fixture-host`, because the
first case could then not discriminate.

Run: python3 .claude/skills/device-emulators/installation/check.test.py
Exits nonzero on any failure.
"""
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
SKILL = os.path.dirname(HERE)
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
REL = os.path.join(".claude", "skills", "device-emulators")
ME = socket.gethostname()
DARWIN = sys.platform == "darwin"

_failures = []
_tmp = os.path.realpath(tempfile.mkdtemp(prefix="device-emulators-check-test-"))
HOME = os.path.join(_tmp, "home")
os.mkdir(HOME)


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def skip(name, why):
    print(f"[SKIP] {name} - {why}")


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mode is not None:
        os.chmod(path, mode)


def fakebin(name, **tools):
    """A directory of fake tools: {name: shell body}. Each is a #!/bin/sh script
    using builtins only, because PATH holds nothing but this directory."""
    d = os.path.join(_tmp, "bin-" + name)
    os.makedirs(d, exist_ok=True)
    for tool, body in tools.items():
        write(os.path.join(d, tool), "#!/bin/sh\n" + body + "\n", 0o755)
    return d


JAVA17 = 'echo \'openjdk version "17.0.2" 2022-01-18\' >&2'
JAVA11 = 'echo \'openjdk version "11.0.20" 2023-07-18\' >&2'
AVDS = 'if [ "$1" = "-list-avds" ]; then echo Example_Phone_API_35; fi'
ANDROID_OK = dict(adb=":", aapt2=":", emulator=AVDS, javac=":", java=JAVA17)


def run(install, path_dir, *args, **env_extra):
    env = {
        "PATH": path_dir,
        "HOME": HOME,
        "PYTHONDONTWRITEBYTECODE": "1",
        "FLEET_CONTEXT_ROOT": install,
        "FLEET_HOST_CONFIG": os.path.join(FLEET_ROOT, "tests", "fixtures", "host.json"),
        "EXAMPLE_BUILD_TOKEN": "fixture-token-not-a-secret",
    }
    for k, v in env_extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    p = subprocess.run([sys.executable, CHECK, *args], capture_output=True, text=True,
                       env=env, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()


def entry(version=3):
    return {"version": version, "installed_at": "2026-01-15T12:00:00Z", "by": "INSTRUCTION.md"}


def copy(name, state=None, config=None, mutate=None):
    """A copy of the fixture install. state/config: None keeps the fixture's,
    False deletes the file, a str is written raw, anything else as JSON.
    mutate(cfg) edits the fixture's config in place before it is written."""
    root = os.path.join(_tmp, "install-" + name)
    shutil.copytree(FIXTURE_INSTALL, root, symlinks=True)
    ctx = os.path.join(root, REL)
    if mutate is not None:
        with open(os.path.join(ctx, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        mutate(cfg)
        config = cfg
    for rel, value in (("installation/.install-state.json", state), ("config.json", config)):
        p = os.path.join(ctx, rel)
        if value is False:
            os.remove(p)
        elif value is not None:
            write(p, value if isinstance(value, str) else json.dumps(value))
    return root


def mine(version=3):
    return {"versions": {"fixture-host": entry(), ME: entry(version)}}


def names(path, text):
    return path in text or os.path.realpath(path) in text


def main():
    if not os.path.isfile(os.path.join(FIXTURE_INSTALL, ".claude", "fleet.json")) \
            or not os.path.isfile(os.path.join(FIXTURE_INSTALL, REL, "config.json")):
        check("NO VERDICT: the fixture install (tests/fixtures/install/.claude/fleet.json and "
              + REL + "/config.json) is incomplete, so nothing here can run", False)
        return
    if ME == "fixture-host":
        check("NO VERDICT: this machine is named fixture-host, so the fixture's own record "
              "cannot be told from this machine's", False)
        return

    ok_bin = fakebin("ok", **ANDROID_OK)

    # === 1. The fixture install as committed: its config, scripts and state file are read.
    rc, out = run(FIXTURE_INSTALL, ok_bin)
    check("fixture install: STALE, because only fixture-host is recorded",
          rc == 1 and "no install recorded for this machine" in out and "fixture-host" in out,
          "rc=%d out=%r" % (rc, out))

    # === 2. POSITIVE CONTROL: the same install with this machine recorded.
    both = copy("both", state=mine())
    rc, out = run(both, ok_bin)
    check("this machine recorded beside another: exit 0",
          rc == 0 and out.startswith("OK: installed and current (version 3)"), "rc=%d out=%r" % (rc, out))
    check("...the OK line is the inventory: JDK, accelerator words, AVD",
          "JDK 17" in out and "fixture accelerator usable" in out and "Example_Phone_API_35" in out,
          "out=%r" % out)
    check("...and reports the optional driver's absence without failing",
          "device-e2e: no example-driver (optional" in out, "out=%r" % out)

    # === 3. Versions and the state file.
    for label, state, want in (
            ("an older recorded version", {"versions": {ME: entry(2)}}, "recorded version 2"),
            ("a newer recorded version", {"versions": {ME: entry(99)}}, "NEWER"),
            ("an unreadable state file", "{not json", "unreadable"),
            ("a state file with no versions map", {"host": ME, "version": 3}, "unreadable"),
            ("no state file", False, "records which version"),
            ("another machine's record alone", {"versions": {"other-host": entry()}}, "other-host")):
        rc, out = run(copy(label.replace(" ", "-"), state=state), ok_bin)
        check(f"{label} is STALE (exit 1)", rc == 1 and out.startswith("STALE") and want in out,
              "rc=%d out=%r" % (rc, out))

    # === 4. No install context: nothing was looked at.
    bare = os.path.join(_tmp, "no-install")
    os.makedirs(bare)
    rc, out = run(bare, ok_bin)
    check("no install manifest at FLEET_CONTEXT_ROOT is NO VERDICT (exit 1)",
          rc == 1 and out.startswith("NO VERDICT"), "rc=%d out=%r" % (rc, out))

    # === 5. Config legs.
    rc, out = run(copy("no-config", state=mine(), config=False), ok_bin)
    check("no config.json is NOT INSTALLED, with the install command",
          rc == 2 and "NOT INSTALLED" in out and "install -m 644" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("bad-config", state=mine(), config="{nope"), ok_bin)
    check("an unparseable config.json is NOT INSTALLED",
          rc == 2 and "does not parse" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("no-script-key", state=mine(),
                       mutate=lambda c: c["build"].pop("script")), ok_bin)
    check("a missing required key is NOT INSTALLED naming it",
          rc == 2 and "build.script" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(copy("unknown-platform", state=mine(),
                       mutate=lambda c: c["platforms"].update(enabled=["android", "tvos"])), ok_bin)
    check("an unknown platform is NOT INSTALLED", rc == 2 and "tvos" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, ok_bin, "ios")
    check("asking for a platform not enabled is NOT INSTALLED",
          rc == 2 and "not in config.json platforms.enabled" in out, "rc=%d out=%r" % (rc, out))

    # === 6. The build script resolves against the INSTALL ROOT of the copy.
    noexec = copy("noexec", state=mine())
    script = os.path.join(noexec, REL, "fixture-scripts", "build.sh")
    os.chmod(script, stat.S_IRUSR | stat.S_IWUSR)
    rc, out = run(noexec, ok_bin)
    check("a non-executable build.script is NOT INSTALLED, naming the copy's path",
          rc == 2 and names(script, out), "rc=%d out=%r" % (rc, out))

    # === 7. The build CLI's session.
    rc, out = run(both, ok_bin, EXAMPLE_BUILD_TOKEN=None)
    check("no token and no stored session is NOT INSTALLED naming the variable",
          rc == 2 and "$EXAMPLE_BUILD_TOKEN is unset" in out, "rc=%d out=%r" % (rc, out))
    write(os.path.join(HOME, ".expo", "state.json"), json.dumps({"auth": {"username": "ada"}}))
    rc, out = run(both, ok_bin, EXAMPLE_BUILD_TOKEN=None)
    check("a stored CLI session alone passes that leg", rc == 0, "rc=%d out=%r" % (rc, out))
    os.remove(os.path.join(HOME, ".expo", "state.json"))

    # === 8. The SDK, the hypervisor, the JDK and the AVD legs, in order.
    rc, out = run(both, fakebin("no-adb", **{k: v for k, v in ANDROID_OK.items() if k != "adb"}))
    check("no adb is NOT INSTALLED naming adb", rc == 2 and "adb not found" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, fakebin("no-aapt2", **{k: v for k, v in ANDROID_OK.items() if k != "aapt2"}))
    check("no aapt2 is NOT INSTALLED naming aapt2", rc == 2 and "aapt2 not found" in out,
          "rc=%d out=%r" % (rc, out))
    no_avd = fakebin("no-avd", **dict(ANDROID_OK, emulator=':'))
    rc, out = run(both, no_avd)
    check("a missing AVD is NOT INSTALLED naming android.avd.default",
          rc == 2 and "no AVD named Example_Phone_API_35" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, no_avd, FIXTURE_HYPERVISOR="blocked")
    check("hypervisor BEFORE the AVD list: both broken, the line names the hypervisor",
          rc == 2 and "BLOCKED" in out and "no AVD named" not in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, ok_bin, FIXTURE_HYPERVISOR="raise")
    check("a probe that raises is NOT INSTALLED, never a skipped leg",
          rc == 2 and "UNMEASURED" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, ok_bin, FIXTURE_HYPERVISOR="darwin")
    check("a probe's 'not probed' words reach the OK line",
          rc == 0 and "accel [not probed on darwin]" in out, "rc=%d out=%r" % (rc, out))
    noprobe = copy("no-probe", state=mine())
    os.remove(os.path.join(noprobe, REL, "fixture-scripts", "hypervisor_probe.py"))
    rc, out = run(noprobe, ok_bin)
    check("a missing probe is NOT INSTALLED, never a skipped leg",
          rc == 2 and "not loadable" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, fakebin("jre", **{k: v for k, v in ANDROID_OK.items() if k != "javac"}))
    check("a java with no javac (a JRE) is NOT INSTALLED",
          rc == 2 and "no javac" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(both, fakebin("jdk11", **dict(ANDROID_OK, java=JAVA11)))
    check("a JDK below android.jdk_min_major is NOT INSTALLED",
          rc == 2 and "JDK 11" in out and "older than the required 17" in out, "rc=%d out=%r" % (rc, out))
    driver = fakebin("driver", **dict(ANDROID_OK, **{"example-driver": "echo example-driver 1.2.3"}))
    rc, out = run(both, driver)
    check("an optional driver on PATH is reported with its version",
          rc == 0 and "device-e2e: example-driver example-driver 1.2.3" in out, "rc=%d out=%r" % (rc, out))

    # === 9. realpath: through a symlinked skill directory.
    link = os.path.join(_tmp, "agent-skills", "device-emulators")
    os.makedirs(os.path.dirname(link))
    os.symlink(SKILL, link)
    p = subprocess.run([sys.executable, os.path.join(link, "installation", "check")],
                       capture_output=True, text=True, timeout=120,
                       env={"PATH": ok_bin, "HOME": HOME, "PYTHONDONTWRITEBYTECODE": "1",
                            "FLEET_CONTEXT_ROOT": both,
                            "EXAMPLE_BUILD_TOKEN": "fixture-token-not-a-secret"})
    check("run through a symlinked skill directory, it still resolves fleetlib and SKILL.md",
          p.returncode == 0 and p.stdout.startswith("OK"), "rc=%d out=%r" % (p.returncode, p.stdout + p.stderr))

    # === 10. iOS off macOS.
    if DARWIN:
        skip("iOS cases", "on macOS the check takes the local Xcode path against this machine")
        return
    ios = copy("ios", state=mine(), mutate=lambda c: c["platforms"].update(enabled=["ios"]))
    rc, out = run(ios, ok_bin)
    check("iOS with no remote host off macOS is NOT INSTALLED, saying why",
          rc == 2 and "exists only on macOS" in out, "rc=%d out=%r" % (rc, out))

    devices = json.dumps({"devices": {"rt": [{"name": "Example iPhone", "isAvailable": True}]}})
    ssh_ok = fakebin("ssh-ok", ssh='''for a in "$@"; do last="$a"; done
if [ "$1" = "-G" ]; then echo "hostname $SSH_FAKE_HOSTNAME"; exit 0; fi
case "$last" in *NO_WORKDIR*) [ -n "$SSH_FAKE_NO_WORKDIR" ] && { echo NO_WORKDIR; exit 9; } ;; esac
echo /Applications/Xcode.app/Contents/Developer
echo "Xcode 16.4"
echo 'DEVICES' ''' .replace("DEVICES", devices))
    rc, out = run(ios, ssh_ok, IOS_REMOTE_HOST="localhost", SSH_FAKE_HOSTNAME="localhost")
    check("remote route green: the line says the BUILD credential is not covered",
          rc == 0 and "REMOTE route to ada@localhost" in out and "NOT covered" in out,
          "rc=%d out=%r" % (rc, out))
    check("...and the remote workdir kept its ~ for the REMOTE shell",
          "~/example-ios-builds present" in out, "out=%r" % out)
    rc, out = run(ios, ssh_ok, IOS_REMOTE_HOST="localhost", SSH_FAKE_HOSTNAME="localhost",
                  SSH_FAKE_NO_WORKDIR="1")
    check("a missing remote workdir is named as such, not as unreachable",
          rc == 2 and "does not exist there" in out, "rc=%d out=%r" % (rc, out))
    rc, out = run(ios, ssh_ok, IOS_REMOTE_HOST="localhost",
                  SSH_FAKE_HOSTNAME="no-such-host.invalid")
    check("an unresolvable hostname is named as such, never as a key problem",
          rc == 2 and (("does not resolve" in out and "not a key or a host-key problem" in out)
                       or "did not answer" in out) and "cannot reach the remote Mac" not in out,
          "rc=%d out=%r" % (rc, out))


try:
    main()
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

print("")
if _failures:
    print(f"FAIL - {len(_failures)} case(s): " + "; ".join(_failures))
    sys.exit(1)
print("PASS - every state installation/check reports was produced and named")
