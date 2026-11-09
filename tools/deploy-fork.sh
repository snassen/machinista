#!/usr/bin/env bash
# Puts the norns-mode fork on a Pi that runs the official Machinista release
# the fork is built on, and restarts Machinista.
#   tools/deploy-fork.sh <host>            e.g. machinista@machinista.local
#   tools/deploy-fork.sh <host> --dry-run  list what would change
#
# The fork changes some of Machinista's own files and adds others. The base is
# the upstream release last merged into this branch (git merge-base with
# upstream/beta); only files that differ from it are copied, plus norns/.
# It refuses when the Pi runs a different version than that base, since the
# Python app must match the installed audio engine build.
# Run it again after every Machinista update: an update overwrites the files
# it ships, including the ones the fork changes.
# Left alone on the Pi: norns/bridge/build (built there), and pack.txt and
# results.json in norns/library (try-batch.py adds to them on the Pi).
set -euo pipefail
host="${1:?usage: tools/deploy-fork.sh <user@host> [--dry-run]}"
dry="${2:-}"
cd "$(git rev-parse --show-toplevel)"
git fetch -q upstream 2>/dev/null || true
base="$(git merge-base HEAD upstream/beta)"
want="$(git show "$base:app/branding.py" | sed -n "s/^VERSION *= *'\(.*\)'.*/\1/p")"
have="$(ssh "$host" "sed -n \"s/^VERSION *= *'\\(.*\\)'.*/\\1/p\" ~/Machinista/app/branding.py" 2>/dev/null)"
echo "fork base: ${base:0:7} ($want); $host runs: ${have:-unknown}"
if [[ "$have" != "$want" ]]; then
  echo "refusing: update $host to $want first (Machinista's updater), or merge its version into the fork" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain -- app tools web norns)" ]]; then
  echo "note: uncommitted changes in app/tools/web/norns are deployed as they are" >&2
fi
# Files the fork changes or adds relative to the release, outside norns/ and docs.
files=()
while IFS= read -r f; do files+=("$f"); done < <(git diff --name-only --diff-filter=AMR "$base" HEAD -- app tools web tests config | sort)
echo "${#files[@]} changed Machinista files, plus norns/"
opts=(-a --relative)
[[ "$dry" == --dry-run ]] && opts+=(--dry-run --itemize-changes)
rsync "${opts[@]}" "${files[@]}" "$host:Machinista/"
rsync -a ${dry:+--dry-run --itemize-changes} \
  --exclude 'bridge/build/' --exclude 'library/pack.txt' --exclude 'library/results.json' \
  --exclude '__pycache__/' norns/ "$host:Machinista/norns/"
[[ "$dry" == --dry-run ]] && exit 0
ssh "$host" 'sudo -n /usr/bin/systemctl restart machinista && sleep 6 && systemctl is-active machinista'
