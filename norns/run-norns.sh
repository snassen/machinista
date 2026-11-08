#!/usr/bin/env bash
# Start (or restart) one norns instance for Machinista's NORNS mode.
#   norns/run-norns.sh A   -> OSC on 127.0.0.1:10111, frames in ~/norns/A
#   norns/run-norns.sh B   -> OSC on 127.0.0.1:10112, frames in ~/norns/B
# Needs the norns-lab runtime image (github.com/snassen/norns-lab):
#   docker build -t norns-lab-runtime -f runtime/Dockerfile .
set -euo pipefail
side="${1:?usage: run-norns.sh A|B}"
case "$side" in
  A) port=10111 ;;
  B) port=10112 ;;
  *) echo "unknown instance: $side" >&2; exit 2 ;;
esac
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frames="${NORNS_FRAMES_ROOT:-$HOME/norns}/$side"
image="${NORNS_IMAGE:-norns-lab-runtime}"
mkdir -p "$frames"
docker rm -f "norns-$side" >/dev/null 2>&1 || true
# -i keeps stdin open: the runtime's Lua REPL exits on EOF.
# JACK needs the shm/memlock/rtprio settings inside Docker.
docker run -d -i --name "norns-$side" --restart unless-stopped \
  --shm-size=256m --ulimit memlock=-1:-1 --ulimit rtprio=95 --cap-add SYS_NICE \
  -e NORNS_FRAME_EXPORT_MS="${NORNS_FRAME_EXPORT_MS:-100}" \
  -p "127.0.0.1:$port:10111/udp" \
  -v "$frames:/frames" \
  -v "$here/mod/machinista_bridge:/home/we/dust/code/machinista_bridge:ro" \
  -v "$here/data/system.mods:/home/we/dust/data/system.mods:ro" \
  "$image"
echo "norns $side: OSC 127.0.0.1:$port, frames $frames/screen.png"
