# Review: the Pi 4 add-on against dual-norns NORNS mode

Date: 2026-11-08. Purpose: reuse everything from the Pi 4 work and decide what
changes now that NORNS mode hosts **two** norns.

Two codebases share the name "machinista-norns". Don't confuse them:
- **GitHub `snassen/machinista-norns`** (private, `441c52a`): the **Pi 4 add-on**
  reviewed here. Native norns build, installer, audio/screen/input bridges,
  script library. One norns.
- **Local folder `~/Github/machinista-norns`**: handoff notes for the Pi 5
  work. Not a git repository, and it never mentions the add-on, which is how
  the Pi 5 work came to rebuild the screen and input bridges.

Both target the same norns commit (`42df844`, v3.0.2-3) and the same Awake.

## Verdicts per component

**Reuse** = take over largely unchanged. **Adapt** = keep the design, change it
for two instances or Docker. **Decide** = the dual setup reopens a choice.

| Component (Pi 4 add-on) | What it does | Verdict |
|---|---|---|
| Audio bridge: `bridge/` (LV2 plug-in + `norns_bridged` + `bridge_shm.h`) | norns ↔ Machinista audio through shared memory; adaptive resampling absorbs clock drift; sidechain sends audio into norns; refuses a second copy | **Adapt** (A1) |
| Bridge tests (`bridge_test`, `guard_test`, `test.sh`) | Drift test at ±200 ppm, single-owner guard | **Reuse** |
| Screen bridge: matron patch + `screen/norns_screen.py` | Publishes every finished frame to `/dev/shm/norns-screen` (seqlock, no tearing) | **Decide** (D2) |
| Input bridge: `screen/norns_input.py` (K/E part) | Plug-in page: DISPLAY 5–7 = K1–K3, KNOB 5–7 = E1–E3 | **Adapt**: three lessons go into `app/norns_mode.py` (A3) |
| PARAMS and LOAD pages (`norns_input.py` + `norns_screen.panel`) | Script PARAMS 4 per page with names/values/bars; LOAD picks a script + PSET | **Decide** (D3) |
| norns mod `machinista` (`norns-mod/`) | Answers `/machinista/page`, `/delta`, `/load`; PSET-on-load logic | **Reuse** in every container (verify A4) |
| Script chooser `library/select.lua` + `make_library.py` + catalog survey | Virtual folders, favorites, scrolling descriptions | **Reuse** (D4 decides where its data lives) |
| `library/install_batch.py` | Installs scripts one by one, only keeps those that compile, load and stay within CPU | **Adapt**: runs against a container instead of a native norns |
| Script pack (`pack.txt`, 44 scripts) + mi-UGens | Pinned community scripts, tested on a Pi 4 | **Adapt**: the Docker image lacks `sc3-plugins` (A5) |
| Menu trimming + RESTART restarts only norns | Hosted-norns menus | **Adapt**: RESTART becomes a container restart |
| Sample sharing (`dust/audio/machinista`, `tape`) | norns sees Machinista samples; tape lands in Machinista | **Adapt**: Docker volume mounts instead of symlinks |
| `/home/we` link, `version.txt` | Script compatibility | `/home/we`: not needed, the image runs as `we`. `version.txt`: **needed** (scripts check the norns version); added to the norns-station image |
| `patches/norns-pi-debian13.patch` | Native build fixes on Debian 13 | **Not needed in Docker** (Ubuntu 22.04 image has its own ARM64 patch); kept for a native fallback |
| Grid support | USB grid worked natively in mlr | **Decide** (D5) |
| `install.sh` | Idempotent native installer that patches stock Machinista | **Adapt**: the reusable parts are plug-in upload via the WebUI API, mod enabling and the script pack. The patching part is replaced by the fork |
| `screen/apply_patches.py` (Machinista side) | Text patches into stock Machinista | **Replaced** by the fork's marked hooks |
| JACK helpers (`jk`, `peak`, `jack_connect`) | Readiness check, level meter | **Reuse** for diagnostics |

## A. Adaptations (no decision needed)

**A1. Audio bridge for two instances.** The shared-memory name is already a
compile-time setting (`NB_SHM_NAME`). Build it twice, as
`/norns-bridge-A` and `/norns-bridge-B`, with two plug-in URIs, **Norns
Bridge A** and **Norns Bridge B**, in one bundle. `norns_bridged` runs inside
each container. The container reaches the host's shared memory either through
a bind mount of that one `/dev/shm` file or through `--ipc=host` (the bind
mount is narrower). The containers also need JACK at the Pi 4's
`-p 256` instead of norns-lab's `-p 1024`, or latency goes up about 16 ms.

**A2. Unused MIDI port.** The plug-in already declares a MIDI input but ignores
it. That is the natural place for clock/MIDI from Machinista to norns later.

**A3. Input lessons for `app/norns_mode.py`** (the Pi 4 code got these right):
- reversing a knob clears its remainder, so a change of direction answers at
  once;
- a K-key release always reaches norns, even after leaving the mode while the
  button is held (today's NORNS mode would leave the norns key stuck);
- knob travel 8 there (10 here, now with pacing). The Pi 4 version had no
  pacing, so norns' acceleration applied there too.

**A4. Verify:** the mod replies to the sender's address. Through Docker's
published UDP port that reply has to find its way back to Machinista. It
should, but it isn't tested.

**A5. Image gaps:** the norns-lab image has no `sc3-plugins`, which many
scripts need, and no mi-UGens. Either add them to the image or build a derived
image for Machinista.

## D. Decisions for the dual setup

**D1. Docker or native for two norns?** Docker was chosen because two native
norns collide on ports (OSC 10111, sclang 57120, scsynth 57110), the JACK
server and `dust`. The Pi 4 work is native, so this is the moment to confirm
it. Docker costs: grid passthrough, patches go into an image build, and the
image needs the missing packages. It buys: isolation, two instances, and a
pinned, rebuildable norns.

**D2. Screen: shared memory (Pi 4) or PNG files (Pi 5)?** Shared memory sends
every frame as it is drawn, never shows half-written data, and doesn't write
10 files a second to the NVMe. It needs a small matron patch in the image,
and a per-instance name (`/norns-screen-A`, `-B`). PNG works today with an
unmodified norns.

**D3. Where do PARAMS and LOAD live?** Takeover mode uses both displays for A
and B, so the Pi 4 left-display PARAMS panel has no room. Options: keep the
plug-in page for working with one norns in depth (screen + PARAMS + LOAD) next
to takeover mode for playing both; or add a PARAMS view inside takeover mode,
e.g. SHIFT + DISPLAY 4/8 for the matching side.

**D4. One `dust` or two?** Shared `code` (one script library, installed once)
with separate `data` per instance (each norns keeps its own PSETs and state)?
Or fully separate?

**D5. Grid with two norns.** A USB grid has to be passed into one container.
Which one gets it: fixed to A, or switchable?

**D6. Where the code lives.** The fork already decided "fork, not patches" for
Machinista. Move the reusable add-on parts (bridge, mod, library, tests) into
the fork under `norns/`? Or keep the add-on repository as the norns-side
package and have the fork depend on it? The Pi 4 add-on stays as it is for
single-norns users on stock Machinista either way.

## Suggested order
1. D1 and D6 (they shape everything else).
2. Audio bridge for A and B (A1), since sound is the missing piece.
3. A3 input fixes (small).
4. D2 screen transport.
5. D3 PARAMS/LOAD, D4 dust layout, A5 image packages, then the script pack.
6. D5 grid.
