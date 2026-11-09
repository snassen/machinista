#!/usr/bin/env bash
# Start (or restart) one numbered norns instance for Machinista.
#   norns/run-norns.sh 1   -> container norns-1, OSC on 127.0.0.1:10111
#   norns/run-norns.sh 2   -> container norns-2, OSC on 127.0.0.1:10112
#   norns/run-norns.sh stop 2
# Each instance has a RAM folder /dev/shm/norns/<n>, mounted as /frames in its
# container: screen.png (the norns screen) and bridge (audio to and from the
# Norns Instrument / Norns Effect plug-ins).
# Persistent files live in $NORNS_HOME (default ~/norns):
#   code/      the script library, shared by every instance
#              (norns/library/install-pack.sh fills it)
#   audio/     samples scripts load and record (dust/audio), shared; tape/<n>
#              is mounted over its tape folder
#   data/<n>/  this instance's settings, presets and script data
#   tape/<n>/  this instance's tape recordings
# Needs the norns-station image (norns/container/Dockerfile), built on the
# norns-lab runtime image (github.com/snassen/norns-lab).
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
image="${NORNS_IMAGE:-norns-station}"
home="${NORNS_HOME:-$HOME/norns}"
mkdir -p "$frames" "$home/code" "$home/audio" "$home/data/$n" "$home/tape/$n"
docker rm -f "norns-$n" >/dev/null 2>&1 || true
# docker rm -f is not a clean norns shutdown, and after one norns starts with
# no script (its guard against crash loops). This is a deliberate start, so
# reload the last script.
state="$home/data/$n/system.state"
if [[ -f "$state" ]]; then
  sed -i 's/^norns.state.clean_shutdown = false/norns.state.clean_shutdown = true/' "$state"
  # MIDI from Machinista: the virtual device on port 1 (unless port 1 was
  # given to something else) and MIDI as the clock source at every start.
  # The machinista_bridge mod does the same for a new instance with no state.
  sed -i "s/^midi.vports\[1\].name = 'none'/midi.vports[1].name = 'virtual'/" "$state"
  [[ "${NORNS_MIDI_CLOCK:-1}" == 0 ]] || sed -i 's/^norns.state.clock.source = [0-9]*/norns.state.clock.source = 2/' "$state"
fi
# -i keeps stdin open: the runtime's Lua REPL exits on EOF.
# JACK needs the shm/memlock/rtprio settings inside Docker; period 256 keeps
# the bridge latency low (norns-lab's default is 1024).
docker run -d -i --name "norns-$n" --restart unless-stopped \
  --shm-size=256m --ulimit memlock=-1:-1 --ulimit rtprio=95 --cap-add SYS_NICE \
  -e NORNS_FRAME_EXPORT_MS="${NORNS_FRAME_EXPORT_MS:-100}" \
  -e NORN_LAB_JACK_PERIOD=256 \
  -e NORN_LAB_POST_READY=/opt/machinista/container/post-ready.sh \
  ${NORNS_NO_MIDI:+--env NORNS_NO_MIDI=1} ${NORNS_NO_MIDI:---device /dev/snd/seq} \
  -p "127.0.0.1:$port:10111/udp" \
  -v "$frames:/frames" \
  -v "$home/code:/home/we/dust/code" \
  -v "$home/data/$n:/home/we/dust/data" \
  -v "$home/audio:/home/we/dust/audio" \
  -v "$home/tape/$n:/home/we/dust/audio/tape" \
  -v "$here/bridge:/opt/machinista/bridge:ro" \
  -v "$here/container:/opt/machinista/container:ro" \
  -v "$here/mod/machinista_bridge:/home/we/dust/code/machinista_bridge:ro" \
  -v "$here/data/system.mods:/home/we/dust/data/system.mods:ro" \
  "$image" >/dev/null
echo "norns $n: OSC 127.0.0.1:$port, files in $frames"
