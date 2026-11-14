"""Fixture hypervisor probe for the device-emulators tests.

The interface installation/check imports (SKILL.md, "The two scripts"):
check_hypervisor(<emulator path>) -> (ok, detail), ok True, False or None
(not measured). It measures nothing: the verdict comes from FIXTURE_HYPERVISOR,
so check.test.py can drive each branch.

    unset or "ok"   (True, "fixture accelerator usable")
    "unmeasured"    (None, "not measured on darwin")
    "legacy-words"  (True, "not probed on darwin"): a probe that predates the
                    None answer, read as its verdict says
    "blocked"       (False, "android: fixture hypervisor BLOCKED ...")
    "bad-answer"    ("yes", ...): none of True, False or None
    "raise"         raises RuntimeError
"""
import os


def check_hypervisor(emulator):
    mode = os.environ.get("FIXTURE_HYPERVISOR", "ok")
    if mode == "raise":
        raise RuntimeError("fixture probe told to raise")
    if mode == "blocked":
        return False, ("android: fixture hypervisor BLOCKED: /dev/kvm cannot be opened by "
                       "this user (a machine ADMIN adds the user to its group)")
    if mode == "unmeasured":
        return None, "not measured on darwin"
    if mode == "legacy-words":
        return True, "not probed on darwin"
    if mode == "bad-answer":
        return "yes", "fixture probe answering a string"
    return True, "fixture accelerator usable"
