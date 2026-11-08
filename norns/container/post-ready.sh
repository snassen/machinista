#!/usr/bin/env bash
# Runs inside a norns container once norns is ready (norns-lab's NORN_LAB_POST_READY):
# builds the audio bridge daemon from the mounted source and connects crone to
# this instance's bridge file, /frames/bridge.
set -euo pipefail
OUT=/tmp/machinista-bridge
mkdir -p "$OUT"
OUT=$OUT bash /opt/machinista/bridge/build.sh daemon
exec "$OUT/norns_bridged" /frames/bridge
