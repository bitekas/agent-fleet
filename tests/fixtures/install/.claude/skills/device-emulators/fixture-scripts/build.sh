#!/bin/bash
# Fixture build script for the device-emulators tests. It builds nothing.
# installation/check needs build.script to be an executable file; config.test.mjs
# reads the two lines below as the JDK-floor twin and the javac predicate
# (SKILL.md, "The two scripts").
ANDROID_JDK_MIN_MAJOR_FALLBACK=17
# A JDK is qualified on "$JAVA_HOME/bin/javac", never on java.
echo "fixture build script: nothing is built" >&2
exit 2
