# Context: device-emulators, fixture install

FIXTURE for the fleet's own tests. Every value is synthetic.

## The project

**Example App** (`project.name`), a React Native app built with Expo. The scripts
`config.json` names are the stubs under `fixture-scripts/`: they build and serve
nothing, and exist so `installation/check` and `config.test.mjs` have real files
to measure.

## What the scripts add to the interface

Nothing: the stubs implement no subcommand. An install records here its build
script's timeout knobs and their defaults, its headless knob, its exact
attach-failure messages, the functions behind each step, what its dev script
leaves behind after a cgroup stop and what its `down` prints.

## Not ruled

1. Which device and AVD a change must be checked on: Ada rules it.
