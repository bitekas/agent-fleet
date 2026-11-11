"""fleetlib - the one Python implementation of every cross-skill lookup.

Modules:
  paths       where things are: the host settings file, the install root, a
              skill's install context, config-relative paths, the secrets dir.
  manifest    the install manifest (.claude/fleet.json): load and validate
              schema 1, and the settings view with the fleet defaults applied.
  transports  the chat-transport registry: every transport.json in the fleet
              tree, validated.
  expand      config-value expansion: ~, $VAR, ${VAR}, ${VAR:-default}.

A fleet script at .claude/skills/<skill>/<script> imports it with

    sys.path.insert(0, str(Path(os.path.realpath(__file__)).parents[3] / "lib"))

and `realpath`, never `abspath`: run through a personal skill link, abspath is
the link path under the agent's config directory, and three parents up from
there is not the fleet tree.

Every failure is a FleetError carrying the exit code a command reports for it
(the `fleet` command's codes: 0 ok, 1 drift or finding, 2 refused or usage
error with nothing changed, 3 environment fault) and, where one exists, the
environment variable that fixes it and the manifest key at fault. A caller that
prints `str(err)` and exits `err.exit_code` reports it correctly.
"""

OK = 0
DRIFT = 1
REFUSED = 2
FAULT = 3


class FleetError(Exception):
    """Base of every fleetlib failure.

    exit_code  what a command exits with for this failure.
    variable   the environment variable to set to fix it, or None.
    key        the dotted manifest or descriptor key at fault, or None.
    """

    exit_code = FAULT

    def __init__(self, message, *, variable=None, key=None):
        self.message = message
        self.variable = variable
        self.key = key
        super().__init__(message)

    def __str__(self):
        text = self.message
        if self.variable and self.variable not in text:
            text += f" (set {self.variable})"
        return text


class EnvironmentFault(FleetError):
    """The host or install is not in a state the lookup can work from (exit 3)."""

    exit_code = FAULT


class Refused(FleetError):
    """The input is invalid; nothing was changed (exit 2)."""

    exit_code = REFUSED


class ManifestError(Refused):
    """The install manifest violates schema 1; `key` names the offending key (exit 2)."""


class DescriptorError(EnvironmentFault):
    """A transport.json in the fleet tree violates schema 1 (exit 3): the fleet
    tree itself is broken, which no flag of the caller's can fix."""


__all__ = [
    "OK", "DRIFT", "REFUSED", "FAULT",
    "FleetError", "EnvironmentFault", "Refused", "ManifestError", "DescriptorError",
]
