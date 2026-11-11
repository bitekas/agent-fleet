"""Tests for fleetlib.services: unit names, both backends against fake managers,
the captured `launchctl print` layouts, rendering, and the process readers.

Nothing here reaches a real service manager: systemctl is a fake written per
test (FLEET_SYSTEMCTL), launchctl is tests/fixtures/launchd/fake-launchctl
(FLEET_LAUNCHCTL), the procfs is a fake tree (FLEET_PROC), and HOME is a temp
directory. The launchd parser is pinned to tests/fixtures/launchd/print-*.txt,
whose layout was captured on macOS 27.0.1, and the fake launchctl is checked to
speak that same layout key for key.

Exit 0 every test passed; 1 a test failed; 3 NO VERDICT: nothing failed, but a
negative control below was not built, its plumbing did not pass unmutated, or
its mutant passed, so a green it guards is unproven and no pass is claimed.

NEGATIVE CONTROLS (ControlTest). Each property the module docstring calls
load-bearing has a check here that is run a second time against a MUTANT of
services.py breaking exactly that property; the mutant run must fail, and with
the marker named, so it fails for that reason and not on its own plumbing:

  R  restart() as `kickstart -k`             test_restart_rereads_the_plist
  W  bootstrap with no wait after bootout    test_restart_waits_for_a_lingering_bootout
  P  the host's launchd_prefix ignored       test_launchd_prefix_comes_from_the_host
  E  the macOS process environment as {}     test_darwin_process_environment_is_unknown
  D  status read from any depth of print     test_print_status_ignores_nested_blocks
  X  plist values not XML-escaped            test_plist_values_are_escaped
  T  `running` with no pid read as active    test_running_with_no_pid_is_the_throttle
  C  a systemd command cut at its first `;`  test_definition_reads_whole_commands_and_every_line
  L  one line kept per systemd Exec key      test_definition_reads_whole_commands_and_every_line

Deleting a control turns its check back into one nobody showed can fail.
"""

import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from fleetlib import EnvironmentFault, Refused, services  # noqa: E402
from fleetlib._testkit import FIXTURES, REPO, IsolatedTest, write_json  # noqa: E402

LAUNCHD_FIX = FIXTURES / "launchd"
FAKE_LAUNCHCTL = LAUNCHD_FIX / "fake-launchctl"
SEAMS = ("FLEET_SERVICE_BACKEND", "FLEET_SYSTEMCTL", "AGENT_DAEMONS_SYSTEMCTL", "FLEET_LAUNCHCTL",
         "FLEET_PROC", "AGENT_DAEMONS_PROC", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "FAKE_LAUNCHD_LINGER",
         "FLEET_LAUNCHD_SYSTEM_DIR")
UID = os.getuid()
A = "ada"
G = "grace"   # unit names are built, never literals: `<job>@<agent>.service` is e-mail shaped
PFX = "com.agent-fleet-test"
INCONCLUSIVE = []

FAKE_SYSTEMCTL = r'''#!/usr/bin/env python3
import fnmatch, json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_SYSTEMCTL_CALLS"], "a") as f:
    f.write(json.dumps({"args": args, "xdg": os.environ.get("XDG_RUNTIME_DIR")}) + "\n")
if os.environ.get("FAKE_SYSTEMCTL_FAIL"):
    print("Failed to connect to bus: No medium found", file=sys.stderr)
    sys.exit(1)
state = json.load(open(os.environ["FAKE_SYSTEMCTL_STATE"]))
if args and args[0] == "--user":
    args = args[1:]
if args[:1] == ["show"]:
    u = state.get(args[1], {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead",
                            "Result": "success", "NRestarts": "0", "MainPID": "0"})
    for i, a in enumerate(args):
        if a == "-p":
            # A list is a key systemd prints once per value: one line per command.
            v = u.get(args[i + 1], "")
            for x in (v if isinstance(v, list) else [v]):
                print(f"{args[i + 1]}={x}")
elif args[:1] == ["list-units"]:
    pats = [a for a in args[1:] if not a.startswith("-")]
    for name in state:
        if any(fnmatch.fnmatch(name, p) for p in pats):
            print(f"{name} loaded active running x")
'''


def exec_value(argv, ignore="no"):
    """One Exec* value as `systemctl show` prints it on systemd 259 (captured on
    a host): the argv words joined by spaces, unquoted, between path= and
    ignore_errors=."""
    return (f"{{ path={argv.split()[0]} ; argv[]={argv} ; ignore_errors={ignore} ; start_time=[n/a] ; "
            "stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }")


# The agent unit's boot handshake as the manager prints it: a `bash -c` script
# whose `;` come long before the follower path its boot message names
# (templates/claude-agent.service.example, ExecStartPost).
HANDSHAKE = ('/bin/bash -c T=/run/claude-tmux-ada; S=claude-ada:0; ok=; for i in $(seq 1 60); do sleep 3; done; '
             'TMUX_TMPDIR=$T tmux send-keys -t $S "Arm each: python3 /srv/f/systemd/agent-daemons.py follow ada '
             'sched 2>&1 ; and python3 /srv/f/systemd/agent-daemons.py follow ada slack-watch 2>&1 ."; sleep 1')


def strip_fixture(path):
    with open(path) as f:
        return "".join(line for line in f if not line.startswith("#fixture"))


def plist_bytes(label, argv, env=None, run_at_load=True, log=None, workdir=None):
    d = {"Label": label, "ProgramArguments": argv, "RunAtLoad": run_at_load,
         "KeepAlive": {"SuccessfulExit": False}}
    if workdir:
        d["WorkingDirectory"] = workdir
    if env:
        d["EnvironmentVariables"] = env
    if log:
        d["StandardOutPath"] = d["StandardErrorPath"] = log
    return plistlib.dumps(d)


class ServicesTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        for k in SEAMS:
            os.environ.pop(k, None)

    def host(self, **extra):
        path = write_json(self.tmp / "host.json", {"schema": 1, "agents_root": str(self.tmp / "agents"),
                                                   "fleet_checkout": str(self.tmp / "fleet"),
                                                   "claims_dir": str(self.tmp / "claims"), **extra})
        os.environ["FLEET_HOST_CONFIG"] = str(path)
        return path

    # -- launchd fixture world --------------------------------------------------
    def launchd(self, **host):
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        self.host(launchd_prefix=PFX, **host)
        os.environ["FLEET_LAUNCHCTL"] = str(FAKE_LAUNCHCTL)
        self.lstate = self.tmp / "launchd.json"
        self.lcalls = self.tmp / "launchd-calls.log"
        os.environ["FAKE_LAUNCHD_STATE"] = str(self.lstate)
        os.environ["FAKE_LAUNCHD_CALLS"] = str(self.lcalls)
        self.agents_dir = self.home / "Library" / "LaunchAgents"
        self.agents_dir.mkdir(parents=True)

    def lstate_get(self):
        return json.loads(self.lstate.read_text()) if self.lstate.exists() else {}

    def lstate_put(self, d):
        self.lstate.write_text(json.dumps(d))

    def lcalls_get(self):
        return self.lcalls.read_text().splitlines() if self.lcalls.exists() else []

    def canned(self, call, fixture, exit_code=0):
        """fake-launchctl answers `call` with the fixture file (a path, or a name in
        tests/fixtures/launchd/) and `exit_code`."""
        st = self.lstate_get()
        st.setdefault("canned", {})[call] = {"file": str(LAUNCHD_FIX / fixture), "exit": exit_code}
        self.lstate_put(st)

    def write_plist(self, label, argv, **kw):
        path = self.agents_dir / f"{label}.plist"
        path.write_bytes(plist_bytes(label, argv, **kw))
        return path

    # -- systemd fixture world --------------------------------------------------
    def systemd(self, units=None):
        os.environ["FLEET_SERVICE_BACKEND"] = "systemd"
        fake = self.tmp / "systemctl"
        fake.write_text(FAKE_SYSTEMCTL)
        fake.chmod(0o755)
        os.environ["FLEET_SYSTEMCTL"] = str(fake)
        self.sstate = self.tmp / "units.json"
        self.scalls = self.tmp / "systemctl-calls.log"
        self.sstate.write_text(json.dumps(units or {}))
        os.environ["FAKE_SYSTEMCTL_STATE"] = str(self.sstate)
        os.environ["FAKE_SYSTEMCTL_CALLS"] = str(self.scalls)

    def scalls_get(self):
        return [json.loads(x) for x in self.scalls.read_text().splitlines()] if self.scalls.exists() else []


# ===================================================================== selection

class BackendTest(ServicesTest):
    def test_default_follows_the_platform(self):
        self.assertEqual(services.backend(), "launchd" if sys.platform == "darwin" else "systemd")

    def test_the_variable_forces_either(self):
        for b in ("systemd", "launchd"):
            os.environ["FLEET_SERVICE_BACKEND"] = b
            self.assertEqual(services.backend(), b)

    def test_an_unknown_backend_is_exit_3_naming_the_variable(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "upstart"
        self.assertFleetError(EnvironmentFault, services.backend, exit_code=3,
                              variable="FLEET_SERVICE_BACKEND")


# ===================================================================== names

class NamesTest(ServicesTest):
    def test_systemd_names_are_todays(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "systemd"
        self.assertEqual(services.unit("job", A, "sched"), f"agent-sched@{A}.service")
        self.assertEqual(services.unit("job", None, "slack-watch"), "agent-slack-watch@.service")
        self.assertEqual(services.unit("refresh"), "agent-daemons-refresh.timer")
        self.assertEqual(services.unit("session", A), f"claude-agent-{A}.service")
        self.assertEqual(services.unit("watchdog", A), f"claude-agent-{A}-stall-watchdog.service")
        self.assertEqual(services.unit_file(f"agent-sched@{A}.service"), f"agent-sched@{A}.service")

    def test_launchd_default_prefix_with_no_host_settings(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        os.environ["FLEET_HOST_CONFIG"] = str(self.tmp / "absent.json")
        self.assertEqual(services.unit("job", A, "sched"), f"com.agent-fleet.sched.{A}")
        self.assertEqual(services.unit("refresh"), "com.agent-fleet.daemons-refresh")
        self.assertEqual(services.unit("session", A), f"com.agent-fleet.session.{A}")
        self.assertEqual(services.unit("watchdog", A), f"com.agent-fleet.stall-watchdog.{A}")
        self.assertEqual(services.unit_file("com.agent-fleet.daemons-refresh"),
                         "com.agent-fleet.daemons-refresh.plist")

    def test_launchd_prefix_comes_from_the_host(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        self.host(launchd_prefix=PFX)
        self.assertEqual(services.unit("job", A, "slack-watch"), f"{PFX}.slack-watch.{A}")
        self.assertEqual(services.unit("refresh"), f"{PFX}.daemons-refresh")
        self.assertIsNone(services.parse(f"com.agent-fleet.sched.{A}"),
                          "another prefix's label is not this host's unit")

    def test_launchd_has_no_template_units(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        self.assertFleetError(Refused, services.unit, "job", None, "sched", exit_code=2)

    def test_reserved_and_malformed_names_are_refused(self):
        for b in ("systemd", "launchd"):
            os.environ["FLEET_SERVICE_BACKEND"] = b
            for job in ("session", "stall-watchdog", "Sched", "", None):
                self.assertFleetError(Refused, services.unit, "job", A, job, exit_code=2)
            for agent in ("../x", "a.b", "Ada", "-x"):
                self.assertFleetError(Refused, services.unit, "session", agent, exit_code=2)
            self.assertFleetError(Refused, services.unit, "watchdog", exit_code=2)
            self.assertFleetError(Refused, services.unit, "timer", A, exit_code=2)

    def test_parse_inverts_unit_on_both_backends(self):
        self.host(launchd_prefix=PFX)
        for b in ("systemd", "launchd"):
            os.environ["FLEET_SERVICE_BACKEND"] = b
            cases = [(("job", A, "sched"), ("job", "sched", A)),
                     (("job", "grace_2", "slack-watch"), ("job", "slack-watch", "grace_2")),
                     (("session", A), ("session", None, A)),
                     (("watchdog", A), ("watchdog", None, A)),
                     (("refresh",), ("refresh", None, None))]
            for args, want in cases:
                name = services.unit(*args) if args[0] != "job" else services.unit("job", args[1], args[2])
                self.assertEqual(services.parse(name), want, f"{b}: {name}")
                self.assertEqual(services.parse(services.unit_file(name)), want, f"{b}: {name} file")
            for foreign in ("actions.runner.example.ci-1", "sshd.service", f"{PFX}.a.b.c", "claude-agent-.service"):
                self.assertIsNone(services.parse(foreign), f"{b}: {foreign}")

    def test_unit_dirs(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "systemd"
        self.assertEqual(services.unit_dir(), self.home / ".config" / "systemd" / "user")
        self.assertEqual(services.unit_dir("system"), Path("/etc/systemd/system"))
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        self.assertEqual(services.unit_dir(), self.tmp / "xdg" / "systemd" / "user")
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        self.assertEqual(services.unit_dir(), self.home / "Library" / "LaunchAgents")
        self.assertEqual(services.unit_dir("system"), Path("/Library/LaunchDaemons"))
        os.environ["FLEET_LAUNCHD_SYSTEM_DIR"] = str(self.tmp / "LaunchDaemons")
        self.assertEqual(services.unit_dir("system"), self.tmp / "LaunchDaemons", "the system dir's seam")
        self.assertFleetError(Refused, services.unit_dir, "session", exit_code=2)

    def test_launchd_domain_from_the_host(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "launchd"
        self.host()
        self.assertEqual(services.domain(), f"gui/{UID}")
        self.assertEqual(services.domain("system"), "system")
        self.host(launchd_domain="user")
        self.assertEqual(services.domain(), f"user/{UID}")


# ===================================================================== launchd: captured layouts

class PrintLayoutTest(ServicesTest):
    def setUp(self):
        super().setUp()
        self.launchd()
        self.label = f"{PFX}.sched.{A}"

    def test_running_capture(self):
        self.canned(f"print gui/{UID}/{self.label}", "print-running.txt")
        s = services.status(self.label)
        self.assertEqual(s, {"load": "loaded", "active": "active", "sub": "running", "result": "success",
                             "restarts": 0, "pid": 2132, "error": ""})

    def test_print_status_ignores_nested_blocks(self):
        # The resource coalition block says `state = active`; the job's own line is
        # `state = running`. Only the top level is the job's.
        scalars, blocks = services.parse_print(strip_fixture(LAUNCHD_FIX / "print-running.txt"))
        self.assertEqual(scalars["state"], "running")
        self.assertEqual(scalars["active count"], "1")
        self.assertIn("ID = 2609", blocks["resource coalition"])
        self.assertNotIn("type", {k for k in scalars if scalars[k] == "resource"})
        self.assertEqual(scalars.get("type"), "LaunchAgent")

    def test_definition_from_what_launchd_loaded(self):
        self.canned(f"print gui/{UID}/{self.label}", "print-running.txt")
        d = services.definition(self.label)
        fx = "/tmp/fleet-fixture/agents"
        self.assertEqual(d["source"], "loaded")
        self.assertEqual(d["argv"][:3], ["/opt/homebrew/bin/python3", f"{fx}/fleet/systemd/agent-daemons.py", "exec"])
        self.assertEqual(d["argv"][-1], f"{fx}/fleet/.claude/skills/scheduled-tasks/sched.py")
        # The job's own environment block, never `inherited` or `default environment`.
        self.assertEqual(d["env"]["SCHED_CONFIG"], f"{fx}/{A}/config/scheduler.json")
        self.assertEqual(d["env"]["PATH"], "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertNotIn("SSH_AUTH_SOCK", d["env"])
        self.assertEqual(d["workdir"], f"{fx}/{A}/product")
        self.assertEqual(d["log"], f"{fx}/{A}/state/daemons/sched.log")
        self.assertEqual(services.log_of(self.label), d["log"])
        self.assertTrue(d["path"].endswith(f"/Library/LaunchAgents/{self.label}.plist"))

    def test_exited_job(self):
        self.canned(f"print gui/{UID}/{self.label}", "print-exited.txt")
        self.assertEqual(services.status(self.label),
                         {"load": "loaded", "active": "failed", "sub": "failed", "result": "exit-code",
                          "restarts": 0, "pid": 0, "error": ""})

    def test_last_exit_from_the_captures(self):
        for fixture, want in (("print-exited.txt", {"result": "exit-code", "code": "3"}),
                              ("print-respawned-signal.txt", {"result": "signal", "code": "Killed: 9"}),
                              ("print-running.txt", {"result": "success", "code": ""})):
            self.canned(f"print gui/{UID}/{self.label}", fixture)
            self.assertEqual(services.last_exit(self.label), want, fixture)
        self.canned(f"print gui/{UID}/{self.label}", "print-not-found.txt", exit_code=113)
        self.assertEqual(services.last_exit(self.label), {"result": "success", "code": ""})

    def test_running_with_no_pid_is_the_throttle(self):
        # launchd can print `state = running` with no `pid` line in a KeepAlive job's
        # throttle. Read as active it gives the follower a false DAEMON-OK after its
        # not-active alert, and `agent-daemons.py status` an ok row with pid=0.
        scalars, _ = services.parse_print(strip_fixture(LAUNCHD_FIX / "print-running-no-pid.txt"))
        self.assertEqual((scalars["state"], "pid" in scalars), ("running", False),
                         "control: the fixture is the case this test claims (running, no pid line)")
        self.canned(f"print gui/{UID}/{self.label}", "print-running-no-pid.txt")
        self.assertEqual(services.status(self.label),
                         {"load": "loaded", "active": "activating", "sub": "auto-restart", "result": "exit-code",
                          "restarts": 0, "pid": 0, "error": ""})

    def test_not_found_capture(self):
        self.canned(f"print gui/{UID}/{self.label}", "print-not-found.txt", exit_code=113)
        s = services.status(self.label)
        self.assertEqual((s["load"], s["active"], s["sub"], s["result"]), ("not-found", "inactive", "dead", "success"))
        self.assertIsNone(services.definition(self.label), "no plist on disk either")

    def test_an_unexpected_answer_is_unknown_with_its_text(self):
        (self.tmp / "garbled.txt").write_text("Operation already in progress\n")
        self.canned(f"print gui/{UID}/{self.label}", self.tmp / "garbled.txt", exit_code=37)
        s = services.status(self.label)
        self.assertEqual((s["load"], s["active"]), ("unknown", "unknown"))
        self.assertIn("already in progress", s["error"])

    def test_print_disabled_capture(self):
        self.canned(f"print-disabled gui/{UID}", "print-disabled.txt")
        self.assertEqual(services.disabled(), {"com.example.helper": False,
                                               f"{PFX}.slack-watch.{A}": True,
                                               f"{PFX}.sched.grace": False})

    def test_the_fake_speaks_the_captured_layout(self):
        # Every check below runs against fake-launchctl's own `print`; this pins that
        # output to the capture, so a fake that drifted from macOS cannot keep them green.
        self.write_plist(self.label, ["/opt/homebrew/bin/python3", "-u", "/tmp/x.py"], env={"K": "v"},
                         log="/tmp/x.log", workdir="/tmp")
        services.enable(self.label, now=True)
        fake_s, fake_b = services.parse_print(
            subprocess.run([str(FAKE_LAUNCHCTL), "print", f"gui/{UID}/{self.label}"],
                           capture_output=True, text=True).stdout)
        cap_s, cap_b = services.parse_print(strip_fixture(LAUNCHD_FIX / "print-running.txt"))
        self.assertEqual(sorted(fake_s), sorted(cap_s))
        self.assertEqual(sorted(fake_b), sorted(cap_b))
        self.assertEqual(len(cap_s), 25, "control: the capture's top level was read")


# ===================================================================== launchd: lifecycle

class LaunchdLifecycleTest(ServicesTest):
    def setUp(self):
        super().setUp()
        self.launchd()
        self.label = f"{PFX}.sched.{A}"
        self.log = str(self.tmp / "sched.log")

    def test_enable_now_bootstraps_and_names_the_plist(self):
        path = self.write_plist(self.label, ["/opt/homebrew/bin/python3", "-u", "/tmp/a.py"], log=self.log)
        services.enable(self.label, now=True)
        self.assertEqual(self.lcalls_get(), [f"print-disabled gui/{UID}", f"print gui/{UID}/{self.label}",
                                             f"bootstrap gui/{UID} {path}"])
        s = services.status(self.label)
        self.assertEqual((s["active"], s["restarts"]), ("active", 0))
        self.assertGreater(s["pid"], 0)
        self.assertEqual(services.enabled(path.name), {self.label})
        services.enable(self.label, now=True)
        self.assertEqual(sum(c.startswith("bootstrap") for c in self.lcalls_get()), 1,
                         "a loaded label is not bootstrapped twice")

    def test_launchctl_enable_only_for_a_disabled_label(self):
        self.write_plist(self.label, ["/bin/sleep", "300"])
        self.lstate_put({"disabled": {f"gui/{UID}": {self.label: True}}})
        self.assertEqual(services.enabled(self.label), set(), "a disabled label is not enabled")
        services.enable(self.label, now=True)
        calls = self.lcalls_get()
        self.assertIn(f"enable gui/{UID}/{self.label}", calls)
        self.assertLess(calls.index(f"enable gui/{UID}/{self.label}"),
                        next(i for i, c in enumerate(calls) if c.startswith("bootstrap")))
        self.assertEqual(services.status(self.label)["active"], "active")

    def test_enable_without_a_plist_is_exit_3_and_calls_nothing_that_changes(self):
        self.assertFleetError(EnvironmentFault, services.enable, self.label, now=True, exit_code=3)
        self.assertFalse([c for c in self.lcalls_get() if not c.startswith("print")])

    def test_restart_rereads_the_plist(self):
        self.write_plist(self.label, ["/opt/homebrew/bin/python3", "-u", "/tmp/old.py"], log=self.log)
        services.enable(self.label, now=True)
        self.assertEqual(services.definition(self.label)["argv"][-1], "/tmp/old.py")
        self.write_plist(self.label, ["/opt/homebrew/bin/python3", "-u", "/tmp/new.py"], log=self.log)
        open(self.lcalls, "w").close()
        services.restart(self.label)
        self.assertEqual(services.definition(self.label)["argv"][-1], "/tmp/new.py",
                         "the restarted job runs the plist as it is now")
        self.assertEqual(services.status(self.label)["active"], "active")
        verbs = [c.split()[0] for c in self.lcalls_get() if not c.startswith("print")]
        self.assertEqual(verbs, ["bootout", "bootstrap"])

    def test_restart_waits_for_a_lingering_bootout(self):
        self.write_plist(self.label, ["/bin/sleep", "300"])
        services.enable(self.label, now=True)
        os.environ["FAKE_LAUNCHD_LINGER"] = "3"
        services.restart(self.label)
        self.assertEqual(services.status(self.label)["active"], "active")

    def test_restart_of_an_unloaded_label_bootstraps_it(self):
        self.write_plist(self.label, ["/bin/sleep", "300"])
        services.restart(self.label)
        self.assertEqual([c.split()[0] for c in self.lcalls_get() if not c.startswith("print")], ["bootstrap"])

    def test_disable_boots_out_and_keeps_the_plist(self):
        path = self.write_plist(self.label, ["/bin/sleep", "300"])
        services.enable(self.label, now=True)
        services.disable(self.label)
        self.assertEqual(services.status(self.label)["load"], "not-found")
        self.assertTrue(path.is_file())
        self.assertEqual(services.definition(self.label)["source"], "file")
        services.disable(self.label)
        self.assertEqual(sum(c.startswith("bootout") for c in self.lcalls_get()), 1,
                         "an unloaded label is not booted out again")

    def test_start_is_kickstart_and_reload_calls_nothing(self):
        self.write_plist(self.label, ["/bin/sleep", "300"], run_at_load=False)
        services.enable(self.label, now=True)
        self.assertEqual(services.status(self.label)["active"], "inactive")
        services.start(self.label)
        self.assertIn(f"kickstart gui/{UID}/{self.label}", self.lcalls_get())
        self.assertEqual(services.status(self.label)["active"], "active")
        n = len(self.lcalls_get())
        services.reload()
        self.assertEqual(len(self.lcalls_get()), n)

    def test_a_crash_restart_counts_as_a_restart(self):
        self.write_plist(self.label, ["/bin/sleep", "300"])
        services.enable(self.label, now=True)
        subprocess.run([str(FAKE_LAUNCHCTL), "kickstart", "-k", f"gui/{UID}/{self.label}"], check=True)
        self.assertEqual(services.status(self.label)["restarts"], 1)

    def test_instances_are_this_prefixes_job_plists(self):
        for label in (f"{PFX}.sched.{A}", f"{PFX}.slack-watch.{A}", f"{PFX}.sched.grace",
                      f"{PFX}.session.{A}", f"{PFX}.daemons-refresh", f"{PFX}.other-job.{A}",
                      f"com.agent-fleet.sched.{A}", "actions.runner.example.ci-1"):
            self.write_plist(label, ["/bin/true"])
        got = services.instances(["sched", "slack-watch"])
        self.assertEqual(got, [("sched", A, f"{PFX}.sched.{A}"), ("sched", "grace", f"{PFX}.sched.grace"),
                               ("slack-watch", A, f"{PFX}.slack-watch.{A}")])

    def test_started_at_is_the_process_start(self):
        self.write_plist(self.label, ["/bin/sleep", "300"])
        services.enable(self.label, now=True)
        pid = services.status(self.label)["pid"]
        proc = make_proc(self.tmp / "proc", btime=1_000_000)
        fake_pid(proc, pid, ["/bin/sleep", "300"], [], "/", started=1_000_500)
        os.environ["FLEET_PROC"] = str(proc)
        self.assertAlmostEqual(services.started_at(self.label), 1_000_500, delta=0.02)

    def test_hints_name_the_domain_and_the_log(self):
        self.write_plist(self.label, ["/bin/sleep", "300"], log=self.log)
        self.assertEqual(services.hint("start", self.label), f"launchctl kickstart gui/{UID}/{self.label}")
        self.assertEqual(services.hint("restart", self.label),
                         f"launchctl bootout gui/{UID}/{self.label} && launchctl bootstrap gui/{UID} "
                         f"{self.agents_dir / (self.label + '.plist')}")
        os.environ["FLEET_LAUNCHD_SYSTEM_DIR"] = str(self.tmp / "LaunchDaemons")
        self.assertEqual(services.hint("restart", self.label, "system"),
                         f"sudo launchctl bootout system/{self.label} && sudo launchctl bootstrap system "
                         f"{self.tmp / 'LaunchDaemons' / (self.label + '.plist')}")
        self.assertEqual(services.hint("status", self.label, "system"), f"launchctl print system/{self.label}")
        self.assertEqual(services.hint("log", self.label), f"tail -n 30 {self.log}")
        self.assertFleetError(Refused, services.hint, "frobnicate", self.label, exit_code=2)

    def test_domain_exists_reads_the_domain(self):
        self.assertTrue(services.domain_exists())
        self.lstate_put({"absent_domains": [f"gui/{UID}"]})
        self.assertFalse(services.domain_exists(), "no gui domain: no logged-in user")
        self.assertIn(f"print gui/{UID}", self.lcalls_get())
        os.environ["FLEET_SERVICE_BACKEND"] = "systemd"
        self.assertTrue(services.domain_exists())

    def test_definition_commands_are_the_program_arguments(self):
        self.write_plist(self.label, ["/opt/homebrew/bin/python3", "-u", "/tmp/a b.py"])
        self.assertEqual(services.definition(self.label)["commands"], ["/opt/homebrew/bin/python3 -u /tmp/a b.py"])
        services.enable(self.label, now=True)
        self.assertEqual(services.definition(self.label)["commands"], ["/opt/homebrew/bin/python3 -u /tmp/a b.py"])

    def test_a_user_domain_host_talks_to_that_domain(self):
        self.host(launchd_prefix=PFX, launchd_domain="user")
        self.write_plist(self.label, ["/bin/sleep", "300"])
        services.enable(self.label, now=True)
        self.assertIn(f"bootstrap user/{UID} {self.agents_dir / (self.label + '.plist')}", self.lcalls_get())


# ===================================================================== systemd

class SystemdTest(ServicesTest):
    def test_status_and_the_runtime_dir_default(self):
        unit = f"agent-sched@{A}.service"
        self.systemd({unit: {"LoadState": "loaded", "ActiveState": "active", "SubState": "running",
                             "Result": "success", "NRestarts": "2", "MainPID": "4242"}})
        self.assertEqual(services.status(unit), {"load": "loaded", "active": "active", "sub": "running",
                                                 "result": "success", "restarts": 2, "pid": 4242, "error": ""})
        c = self.scalls_get()[-1]
        self.assertEqual(c["args"][:3], ["--user", "show", unit])
        self.assertEqual(c["xdg"], f"/run/user/{UID}")
        os.environ["XDG_RUNTIME_DIR"] = "/run/elsewhere"
        services.status(unit, "system")
        c = self.scalls_get()[-1]
        self.assertEqual((c["args"][0], c["xdg"]), ("show", "/run/elsewhere"))

    def test_last_exit_is_the_result_and_its_number(self):
        failed, killed = f"agent-sched@{A}.service", f"agent-slack-watch@{A}.service"
        self.systemd({failed: {"LoadState": "loaded", "Result": "exit-code", "ExecMainStatus": "3"},
                      killed: {"LoadState": "loaded", "Result": "signal", "ExecMainStatus": "9"}})
        self.assertEqual(services.last_exit(failed), {"result": "exit-code", "code": "3"})
        self.assertEqual(services.last_exit(killed), {"result": "signal", "code": "9"})
        self.assertEqual(services.last_exit("nope.service"), {"result": "success", "code": ""})
        self.assertEqual(self.scalls_get()[-1]["args"][:3], ["--user", "show", "nope.service"])

    def test_a_manager_that_does_not_answer_is_unknown(self):
        self.systemd()
        os.environ["FAKE_SYSTEMCTL_FAIL"] = "1"
        s = services.status("x.service")
        self.assertEqual((s["load"], s["active"]), ("unknown", "unknown"))
        self.assertIn("bus", s["error"])
        self.assertFleetError(EnvironmentFault, services.restart, "x.service", exit_code=3)

    def test_definition(self):
        unit = f"agent-sched@{A}.service"
        self.systemd({unit: {"LoadState": "loaded",
                             "ExecStart": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -u /srv/f/sched.py ; "
                                          "ignore_errors=no ; start_time=[n/a] ; pid=0 ; code=(null) }",
                             "Environment": 'CLAUDE_CONFIG_DIR=/srv/a/.claude "SCHED_CONFIG=/srv/a b/s.json"',
                             "ExecStartPre": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /srv/f/agent-daemons.py "
                                             "rotate /srv/a/s.log ; ignore_errors=no }",
                             "ExecStartPost": exec_value("/bin/bash -c send python3 /srv/f/agent-daemons.py follow"),
                             "WorkingDirectory": "/srv/a/product", "FragmentPath": "/x/agent-sched@.service"}})
        d = services.definition(unit)
        self.assertEqual(d["commands"], ["/usr/bin/python3 /srv/f/agent-daemons.py rotate /srv/a/s.log",
                                         "/usr/bin/python3 -u /srv/f/sched.py",
                                         "/bin/bash -c send python3 /srv/f/agent-daemons.py follow"])
        self.assertEqual(d["argv"], ["/usr/bin/python3", "-u", "/srv/f/sched.py"])
        self.assertEqual(d["env"], {"CLAUDE_CONFIG_DIR": "/srv/a/.claude", "SCHED_CONFIG": "/srv/a b/s.json"})
        self.assertEqual((d["workdir"], d["source"], d["log"]), ("/srv/a/product", "loaded", None))
        self.assertIsNone(services.definition("nope.service"))

    def test_definition_reads_whole_commands_and_every_line(self):
        # A key given three times prints three lines, and a command's argv runs to
        # its ` ; ignore_errors=`: the handshake keeps every `;` and the follower.
        unit = f"claude-agent-{A}.service"
        self.systemd({unit: {"LoadState": "loaded",
                             "ExecStartPre": [exec_value(f"/usr/bin/chattr -i /{x}", "yes") for x in "abc"],
                             "ExecStart": exec_value("/usr/bin/tmux new-session -d -s claude-ada"),
                             "ExecStartPost": exec_value(HANDSHAKE)}})
        cmds = services.definition(unit, "system")["commands"]
        self.assertEqual(cmds[:3], ["/usr/bin/chattr -i /a", "/usr/bin/chattr -i /b", "/usr/bin/chattr -i /c"],
                         "every ExecStartPre= line is a command")
        self.assertEqual(cmds[3:], ["/usr/bin/tmux new-session -d -s claude-ada", HANDSHAKE],
                         "the handshake runs to its ignore_errors, past its first ;")
        self.assertIn("/srv/f/systemd/agent-daemons.py follow ada sched", cmds[-1])

    def test_changes_are_the_systemctl_verbs(self):
        self.systemd()
        u = f"agent-sched@{A}.service"
        services.enable(u, now=True)
        services.enable("agent-daemons-refresh.timer")
        services.disable(u, now=True)
        services.disable(u, scope="system")
        services.restart(u)
        services.start(u)
        services.reload()
        self.assertEqual([c["args"] for c in self.scalls_get()],
                         [["--user", "enable", "--now", u], ["--user", "enable", "agent-daemons-refresh.timer"],
                          ["--user", "disable", "--now", u], ["disable", u], ["--user", "restart", u],
                          ["--user", "start", u], ["--user", "daemon-reload"]])

    def test_enabled_reads_the_wants_links(self):
        self.systemd()
        udir = services.unit_dir()
        (udir / "default.target.wants").mkdir(parents=True)
        (udir / "timers.target.wants").mkdir()
        for name in (f"agent-sched@{A}.service", f"agent-sched@{G}.service", "agent-sched@.service"):
            (udir / "default.target.wants" / name).symlink_to(udir / "agent-sched@.service")
        (udir / "timers.target.wants" / "agent-daemons-refresh.timer").symlink_to("/dev/null")
        self.assertEqual(services.enabled("agent-sched@.service"),
                         {f"agent-sched@{A}.service", f"agent-sched@{G}.service"})
        self.assertEqual(services.enabled("agent-daemons-refresh.timer"), {"agent-daemons-refresh.timer"})
        self.assertEqual(services.enabled("agent-slack-watch@.service"), set())

    def test_instances_from_list_units(self):
        self.systemd({f"agent-sched@{A}.service": {}, f"agent-slack-watch@{A}.service": {},
                      f"agent-sched@{G}.service": {}, f"agent-other@{A}.service": {}})
        self.assertEqual(sorted(services.instances(["sched", "slack-watch"])),
                         [("sched", A, f"agent-sched@{A}.service"), ("sched", G, f"agent-sched@{G}.service"),
                          ("slack-watch", A, f"agent-slack-watch@{A}.service")])

    def test_hints(self):
        os.environ["FLEET_SERVICE_BACKEND"] = "systemd"
        u = f"agent-sched@{A}.service"
        self.assertEqual(services.hint("start", u), f"systemctl --user start {u}")
        self.assertEqual(services.hint("restart", "w.service", "system"), "sudo systemctl restart w.service")
        self.assertEqual(services.hint("log", "w.service", "system"), "journalctl -u w.service -n 30")
        self.assertIsNone(services.log_of(u))


# ===================================================================== rendering

UNIT_TEMPLATE = "[Service]\nExecStart=@PYTHON@ -u @SCRIPT@\n"
PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>@LABEL@</string>
  <key>ProgramArguments</key><array><string>@PYTHON@</string><string>@SCRIPT@</string></array>
</dict>
</plist>
"""


class RenderTest(ServicesTest):
    def test_a_unit_template_renders_as_it_always_has(self):
        got = services.render("agent-x@.service.in", UNIT_TEMPLATE, {"PYTHON": "/usr/bin/python3",
                                                                      "SCRIPT": "/f/s.py"}, "v1.0.3")
        self.assertEqual(got, b"# Rendered by fleet install from systemd/agent-x@.service.in at v1.0.3. "
                              b"Edit the template, not this file.\n[Service]\nExecStart=/usr/bin/python3 -u /f/s.py\n")

    def test_plist_values_are_escaped(self):
        odd = "/tmp/a&b <c>/s.py"
        got = services.render("agent-x.plist.in", PLIST_TEMPLATE,
                              {"LABEL": "com.example.x", "PYTHON": "/p/python3", "SCRIPT": odd}, "v1.1.0--rc")
        d = plistlib.loads(got)
        self.assertEqual(d["ProgramArguments"], ["/p/python3", odd])
        lines = got.decode().splitlines()
        self.assertTrue(lines[0].startswith("<?xml"))
        self.assertEqual(lines[1], "<!-- Rendered by fleet install from systemd/agent-x.plist.in at v1.1.0- -rc. "
                                   "Edit the template, not this file. -->")

    def test_a_placeholder_without_a_value_is_exit_3_naming_it(self):
        for src, text in (("a.service.in", UNIT_TEMPLATE), ("a.plist.in", PLIST_TEMPLATE)):
            err = self.assertFleetError(EnvironmentFault, services.render, src, text, {"PYTHON": "/p"}, "v1",
                                        exit_code=3)
            self.assertIn("@SCRIPT@", str(err))

    def test_a_plist_that_does_not_parse_is_exit_3(self):
        self.assertFleetError(EnvironmentFault, services.render, "a.plist.in",
                              PLIST_TEMPLATE.replace("</dict>", ""), {"LABEL": "l", "PYTHON": "p", "SCRIPT": "s"},
                              "v1", exit_code=3)
        self.assertFleetError(EnvironmentFault, services.render, "a.plist.in", "<plist/>\n", {}, "v1", exit_code=3)


# ===================================================================== processes

def make_proc(root, btime):
    root.mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text(f"cpu  1 2 3 4\nbtime {btime}\nprocesses 1\n")
    return root


def fake_pid(proc, pid, argv, environ, cwd, started):
    d = proc / str(pid)
    d.mkdir(parents=True)
    btime = float((proc / "stat").read_text().split("btime ")[1].split()[0])
    ticks = int(round((started - btime) * os.sysconf("SC_CLK_TCK")))
    (d / "stat").write_text(f"{pid} (python3 (x)) S " + " ".join(["0"] * 18 + [str(ticks)] + ["0"] * 20) + "\n")
    (d / "cmdline").write_bytes(b"".join(x.encode() + b"\0" for x in argv))
    (d / "environ").write_bytes(b"".join(x.encode() + b"\0" for x in environ))
    os.symlink(cwd, d / "cwd")


class ProcTest(ServicesTest):
    def test_procfs_readers(self):
        proc = make_proc(self.tmp / "proc", btime=1_700_000_000)
        fake_pid(proc, 4242, ["/usr/bin/python3", "-u", "s.py"], ["SCHED_CONFIG=/c.json", "A=b=c"],
                 "/srv/a/product", started=1_700_003_600)
        for var in ("FLEET_PROC", "AGENT_DAEMONS_PROC"):
            os.environ.pop("FLEET_PROC", None)
            os.environ.pop("AGENT_DAEMONS_PROC", None)
            os.environ[var] = str(proc)
            self.assertEqual(services.boot_time(), 1_700_000_000)
            self.assertAlmostEqual(services.proc_start(4242), 1_700_003_600, delta=0.02)
            self.assertEqual(services.proc_argv(4242), ["/usr/bin/python3", "-u", "s.py"])
            self.assertEqual(services.proc_cwd(4242), "/srv/a/product")
            self.assertEqual(services.proc_env(4242), {"SCHED_CONFIG": "/c.json", "A": "b=c"})
            for fn in (services.proc_start, services.proc_argv, services.proc_cwd, services.proc_env):
                self.assertIsNone(fn(999999), f"{fn.__name__} of a pid that is not there")

    def test_the_procfs_seam_wins_on_any_platform(self):
        proc = make_proc(self.tmp / "proc", btime=1_000)
        fake_pid(proc, 7, ["x"], ["K=v"], "/", started=1_010)
        os.environ["FLEET_PROC"] = str(proc)
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(services.proc_env(7), {"K": "v"})
            self.assertEqual(services.boot_time(), 1_000)

    def test_darwin_process_environment_is_unknown(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertIsNone(services.proc_env(os.getpid()))
            self.assertIsNone(services.proc_cwd(os.getpid()))

    def test_procargs2_layout(self):
        # The measured macOS layout: argc, the executable path, NUL padding, argv;
        # some processes carry their environment after argv, which is not argv.
        raw = struct.pack("i", 2) + b"/bin/bash\0\0\0\0" + b"/bin/bash\0/tmp/runsvc.sh\0" + b"HOME=/x\0"
        self.assertEqual(services.parse_procargs2(raw), ["/bin/bash", "/tmp/runsvc.sh"])
        self.assertIsNone(services.parse_procargs2(b""))

    def test_timeval_layout(self):
        raw = struct.pack("qi", 1790640895, 29894) + b"\0" * 636
        self.assertAlmostEqual(services.parse_timeval(raw), 1790640895.029894, places=5)
        self.assertIsNone(services.parse_timeval(b"\0" * 648), "a zeroed buffer is no start time")
        self.assertIsNone(services.parse_timeval(None))

    @unittest.skipUnless(sys.platform == "darwin", "the sysctl readers exist on macOS only")
    def test_darwin_live_readers(self):
        now = time.time()
        start = services.proc_start(os.getpid())
        self.assertIsNotNone(start)
        self.assertLess(now - 600, start)
        self.assertLessEqual(start, now)
        argv = services.proc_argv(os.getpid())
        self.assertTrue(argv and any(a.endswith("services.test.py") for a in argv), argv)
        child = subprocess.Popen(["/bin/sleep", "30"], env={**os.environ, "FLEETPROBE": "yes"})
        try:
            self.assertEqual(services.proc_argv(child.pid), ["/bin/sleep", "30"])
            self.assertIsNone(services.proc_env(child.pid))
        finally:
            child.kill()
            child.wait()
        self.assertLess(services.boot_time(), start)
        self.assertIsNone(services.proc_start(2 ** 30), "a pid that is not there")


# ===================================================================== negative controls

CONTROLS = {
    # name: (old text, new text, test id, marker its mutant run must print)
    "R": ('    for name in names:\n        _plist(name, scope)\n        if status(name, scope)["load"] != "not-found":\n'
          '            _bootout(name, scope)\n        _bootstrap(name, scope)\n',
          '    for name in names:\n        _plist(name, scope)\n'
          '        _launchctl("kickstart", "-k", f"{domain(scope)}/{name}", check=True)\n',
          "LaunchdLifecycleTest.test_restart_rereads_the_plist", "the restarted job runs the plist as it is now"),
    "W": ("    while status(name, scope)[\"load\"] != \"not-found\":\n",
          "    while False:\n",
          "LaunchdLifecycleTest.test_restart_waits_for_a_lingering_bootout", "Bootstrap failed: 5"),
    "P": ('    return paths.host_option("launchd_prefix")\n', '    return "com.agent-fleet"\n',
          "NamesTest.test_launchd_prefix_comes_from_the_host", "com.agent-fleet-test.slack-watch"),
    "E": ('    proc = _procfs()\n    if not proc:\n        return None\n    items = ',
          '    proc = _procfs()\n    if not proc:\n        return {}\n    items = ',
          "ProcTest.test_darwin_process_environment_is_unknown", "{} is not None"),
    "D": ("    return scalars, blocks\n",
          '    return {k: v for k, _, v in (x.strip().partition(" = ") for x in text.splitlines()) if v}, blocks\n',
          "PrintLayoutTest.test_print_status_ignores_nested_blocks", "'active' != 'running'"),
    "X": ('        text = text.replace(f"@{k}@", escape(v) if plist else v)\n',
          '        text = text.replace(f"@{k}@", v)\n',
          "RenderTest.test_plist_values_are_escaped", "does not parse"),
    "T": ('    if state == "running" and pid <= 0:\n', "    if False:\n",
          "PrintLayoutTest.test_running_with_no_pid_is_the_throttle", "'sub': 'running'"),
    "C": ('        head, sep, _ = value.rpartition(" ; ignore_errors=")\n'
          '        _, found, argv = (head if sep else value.rstrip().removesuffix("}")).partition("argv[]=")\n'
          '        if found:\n            out.append(argv.strip())\n',
          '        out += [c.strip() for c in re.findall(r"argv\\[\\]=([^;]*)", value)]\n',
          "SystemdTest.test_definition_reads_whole_commands_and_every_line", "past its first ;"),
    "L": ('    for line in show.splitlines():\n',
          '    for line in [x for x in show.splitlines() if x.startswith(key + "=")][-1:]:\n',
          "SystemdTest.test_definition_reads_whole_commands_and_every_line", "every ExecStartPre= line is a command"),
}


class ControlTest(unittest.TestCase):
    """Each control: build a copy of lib/fleetlib with the mutation, run its one
    test there, and require that run to fail with its marker. The same test is
    first run in an UNMUTATED copy and must pass there, so a mutant failing on
    the copy's own plumbing is not counted as the control working."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fleet-services-controls-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self, name, old=None, new=None):
        """A tree <tmp>/<name>/ with lib/fleetlib copied (services.py mutated) and
        tests/ linked; None when `old` does not occur exactly once."""
        root = self.tmp / name
        lib = root / "lib" / "fleetlib"
        lib.mkdir(parents=True)
        src = Path(services.__file__).parent
        for p in src.glob("*.py"):
            shutil.copy(p, lib / p.name)
        (root / "tests").symlink_to(REPO / "tests")
        if old is not None:
            text = (lib / "services.py").read_text()
            if text.count(old) != 1:
                return None
            (lib / "services.py").write_text(text.replace(old, new))
        return lib / "services.test.py"

    def run_one(self, test_file, test_id):
        env = {k: v for k, v in os.environ.items() if k not in SEAMS}
        return subprocess.run([sys.executable, "-B", str(test_file), test_id], capture_output=True,
                              text=True, env=env, timeout=300)

    def control(self, key):
        old, new, test_id, marker = CONTROLS[key]
        base = self.run_one(self.copy(f"base-{key}"), test_id)
        if base.returncode != 0:
            INCONCLUSIVE.append(f"{key}: {test_id} fails in an unmutated copy (plumbing): {base.stderr[-400:]}")
            return
        if "Ran 1 test" not in base.stderr:
            INCONCLUSIVE.append(f"{key}: the unmutated run did not run {test_id}")
            return
        mutant = self.copy(f"mutant-{key}", old, new)
        if mutant is None:
            INCONCLUSIVE.append(f"{key}: the mutated text no longer occurs exactly once in services.py")
            return
        r = self.run_one(mutant, test_id)
        if r.returncode == 0:
            INCONCLUSIVE.append(f"{key}: {test_id} PASSED against its mutant")
        elif marker not in r.stderr + r.stdout:
            INCONCLUSIVE.append(f"{key}: the mutant failed without {marker!r}: {r.stderr[-400:]}")
        else:
            print(f"\n[PASS] CONTROL {key}: {test_id} fails against its mutant with {marker!r}",
                  file=sys.stderr)

    def test_R_restart_as_kickstart(self):
        self.control("R")

    def test_W_no_wait_after_bootout(self):
        self.control("W")

    def test_P_prefix_ignored(self):
        self.control("P")

    def test_E_darwin_env_as_empty(self):
        self.control("E")

    def test_D_status_from_any_depth(self):
        self.control("D")

    def test_X_values_not_escaped(self):
        self.control("X")

    def test_T_running_with_no_pid_as_active(self):
        self.control("T")

    def test_C_command_cut_at_its_first_semicolon(self):
        self.control("C")

    def test_L_one_line_per_exec_key(self):
        self.control("L")


if __name__ == "__main__":
    prog = unittest.main(exit=False)
    if not prog.result.wasSuccessful():
        sys.exit(1)
    if INCONCLUSIVE:
        print("NO VERDICT: no test failed, but these negative controls do not show their check can fail:",
              file=sys.stderr)
        for line in INCONCLUSIVE:
            print(f"  {line}", file=sys.stderr)
        sys.exit(3)
