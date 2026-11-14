"""Fixture hypervisor probe for the device-emulators tests.

The interface installation/check imports (SKILL.md, "The two scripts"):
check_hypervisor(<emulator path>) -> (ok, detail). It measures nothing: the
verdict comes from FIXTURE_HYPERVISOR, so check.test.py can drive each branch.

    unset or "ok"   (True, "fixture accelerator usable")
    "darwin"        (True, "not probed on darwin")
    "blocked"       (False, "android: fixture hypervisor BLOCKED ...")
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
    if mode == "darwin":
        return True, "not probed on darwin"
    return True, "fixture accelerator usable"
