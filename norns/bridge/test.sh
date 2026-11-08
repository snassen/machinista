#!/usr/bin/env bash
# Runs the bridge tests in a throwaway container from the norns runtime image, so
# they need no JACK on the host and never touch a running norns.
#   norns/bridge/test.sh [seconds per drift run, default 20]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
secs="${1:-20}"
image="${NORNS_IMAGE:-norns-lab-runtime}"
docker run --rm -i --entrypoint bash \
  --shm-size=256m --ulimit memlock=-1:-1 --ulimit rtprio=95 --cap-add SYS_NICE \
  -v "$here:/src:ro" "$image" -s "$secs" <<'SCRIPT'
set -e
secs=$1; out=/tmp/bridge; mkdir -p $out
OUT=$out bash /src/build.sh tests >/dev/null
cd $out
./guard_test
jackd -R -P 15 -d dummy -r 48000 -p 256 >/tmp/jack.log 2>&1 &
sleep 2
mkdir -p /dev/shm/norns-test/1
./norns_bridged_test --no-crone /dev/shm/norns-test/1/bridge &
sleep 1
kill -0 $! || { echo "bridge daemon did not start"; exit 1; }
rc=0
for kind in instrument effect; do
  for ppm in 0 200 -200; do
    ./bridge_test ./test_plugin.so $kind $ppm $secs || rc=1
  done
done
echo "BRIDGE_TEST_RC=$rc"
exit $rc
SCRIPT
