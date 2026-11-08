#!/usr/bin/env bash
# Builds the norns bridge. Run from this directory.
#   ./build.sh plugin   on the Pi host: assembles the LV2 bundle build/norns.lv2 (no JACK needed)
#   ./build.sh daemon   inside a norns container: norns_bridged into $OUT (default .)
#   ./build.sh tests    inside a norns container: daemon, tests and a test copy of the plug-in
set -euo pipefail
cd "$(dirname "$0")"
F="-O2 -std=c++17 -Wall -Wextra"
OUT=${OUT:-.}
TEST_DIR='-DNB_DIR="/dev/shm/norns-test"'
case "${1:-}" in
  plugin)
    mkdir -p build/norns.lv2
    cp bundle/manifest.ttl bundle/norns.ttl build/norns.lv2/
    g++ $F -fPIC -shared -fvisibility=hidden norns_lv2.cpp -o build/norns.lv2/norns.so -static-libstdc++ -static-libgcc
    g++ $F bridge_stat.cpp -o bridge_stat
    echo PLUGIN_BUILD_OK ;;
  daemon)
    g++ $F norns_bridged.cpp -o "$OUT/norns_bridged" -ljack
    echo DAEMON_BUILD_OK ;;
  tests)
    mkdir -p "$OUT"
    g++ $F $TEST_DIR norns_bridged.cpp -o "$OUT/norns_bridged_test" -ljack
    g++ $F $TEST_DIR -fPIC -shared norns_lv2.cpp -o "$OUT/test_plugin.so"
    g++ $F $TEST_DIR bridge_test.cpp -o "$OUT/bridge_test" -ljack -ldl -lpthread
    g++ $F -DNB_DIR='"/dev/shm/norns-guard"' -fPIC -shared norns_lv2.cpp -o "$OUT/guard_test_plugin.so"
    g++ $F -DNB_DIR='"/dev/shm/norns-guard"' guard_test.cpp -o "$OUT/guard_test" -ldl
    echo TEST_BUILD_OK ;;
  *) echo "usage: build.sh plugin|daemon|tests" >&2; exit 2 ;;
esac
