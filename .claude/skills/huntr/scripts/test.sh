#!/bin/sh
# HU1/HU2 and slice manifests: synthetic Git and gh; no live reads or writes.
set -eu
exec node --test "$(dirname "$0")/gate.test.mjs" "$(dirname "$0")/manifest.test.mjs" "$(dirname "$0")/records.test.mjs" "$(dirname "$0")/controller.test.mjs"
