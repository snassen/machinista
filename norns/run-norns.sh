#!/usr/bin/env bash
# Start (or restart) one numbered norns instance for Machinista.
#   norns/run-norns.sh 1   -> container norns-1, OSC on 127.0.0.1:10111
#   norns/run-norns.sh 2   -> container norns-2, OSC on 127.0.0.1:10112
#   norns/run-norns.sh stop 2
# Each instance has a RAM folder /dev/shm/norns/<n>, mounted as /frames in its
# container: screen.png (the norns screen) and bridge (audio to and from the
# Norns Instrument / Norns Effect plug-ins).
# Needs the norns-lab runtime image (github.com/snassen/norns-lab):
#   docker build -t norns-lab-runtime -f runtime/Dockerfile .
set -euo pipefail
if [[ "${1:-}" == stop ]]; then
  n="${2:?usage: run-norns.sh stop <1-8>}"
  docker rm -f "norns-$n" >/dev/null 2>&1 || true
  echo "norns $n stopped"; exit 0
fi
n="${1:?usage: run-norns.sh <1-8> | stop <1-8>}"
[[ "$n" =~ ^[1-8]$ ]] || { echo "instance must be 1-8: $n" >&2; exit 2; }
port=$((10110 + n))
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${NORNS_SHM_ROOT:-/dev/shm/norns}"
frames="$root/$n"
image="${NORNS_IMAGE:-norns-lab-runtime}"
mkdir -p "$frames"
docker rm -f "norns-$n" >/dev/null 2>&1 || true
# -i keeps stdin open: the runtime's Lua REPL exits on EOF.
# JACK needs the shm/memlock/rtprio settings inside Docker; period 256 keeps
# the bridge latency low (norns-lab's default is 1024).
docker run -d -i --name "norns-$n" --restart unless-stopped \
  --shm-size=256m --ulimit memlock=-1:-1 --ulimit rtprio=95 --cap-add SYS_NICE \
  -e NORNS_FRAME_EXPORT_MS="${NORNS_FRAME_EXPORT_MS:-100}" \
  -e NORN_LAB_JACK_PERIOD=256 \
  -e NORN_LAB_POST_READY=/opt/machinista/container/post-ready.sh \
  -p "127.0.0.1:$port:10111/udp" \
  -v "$frames:/frames" \
  -v "$here/bridge:/opt/machinista/bridge:ro" \
  -v "$here/container:/opt/machinista/container:ro" \
  -v "$here/mod/machinista_bridge:/home/we/dust/code/machinista_bridge:ro" \
  -v "$here/data/system.mods:/home/we/dust/data/system.mods:ro" \
  "$image" >/dev/null
echo "norns $n: OSC 127.0.0.1:$port, files in $frames"
