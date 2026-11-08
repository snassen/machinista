#!/usr/bin/env bash
# Installs the script pack into the shared script folder that every norns
# instance sees ($NORNS_HOME/code, default ~/norns/code).
#   norns/library/install-pack.sh           installs scripts that are missing
#   norns/library/install-pack.sh otis mlr  only these (reinstalls them)
# Each script is pinned to the commit in pack.txt. Restart the norns
# instances afterwards so SuperCollider compiles the new engines.
# Without git on the host (Machinista's Pi image has none), it runs itself
# inside the norns image, which has git.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
code="${NORNS_HOME:-$HOME/norns}/code"
mkdir -p "$code"
if ! command -v git >/dev/null; then
  exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e NORNS_HOME=/norns \
    -v "$code:/norns/code" -v "$here:/library:ro" \
    --entrypoint bash "${NORNS_IMAGE:-norns-station}" /library/install-pack.sh "$@"
fi
only=" $* "
ok=0; failed=()
while read -r dir url rev; do
  [[ -z "$dir" || "$dir" == \#* ]] && continue
  if [[ $# -gt 0 ]]; then
    [[ "$only" == *" $dir "* ]] || continue
    rm -rf "${code:?}/$dir"
  elif [[ -d "$code/$dir" ]]; then
    continue
  fi
  tmp="$code/.incoming-$dir"
  rm -rf "$tmp"
  if git clone -q "$url" "$tmp" 2>/dev/null \
     && git -C "$tmp" checkout -q --detach "$rev" 2>/dev/null \
     && git -C "$tmp" submodule update -q --init --recursive --depth 1 2>/dev/null; then
    mv "$tmp" "$code/$dir"; echo "installed $dir"; ok=$((ok + 1))
  else
    rm -rf "$tmp"; echo "FAILED $dir ($url @ $rev)" >&2; failed+=("$dir")
  fi
done < "$here/pack.txt"
echo "$ok installed, ${#failed[@]} failed${failed:+: ${failed[*]}}"
[[ ${#failed[@]} -eq 0 ]]
